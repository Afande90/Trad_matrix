"""Plain-words backtest report. The first line is the verdict.

Step 4 of BACKTEST_REVIEW_CHECKLIST is the decision rule.
"""

from __future__ import annotations

import json
from pathlib import Path


def step4_verdict(track: dict, step1_ok: bool) -> str:
    if not step1_ok:
        return "RERUN"
    n = int(track.get("counted") or 0)
    days = int(track.get("days_with_calls") or 0)
    if n < 300 or days < 60:
        return "TOO EARLY"
    gross = track.get("gross_mean")
    net = track.get("net_mean")
    net_lb = track.get("net_lb")
    if gross is None or net is None:
        return "TOO EARLY"
    if gross <= 0:
        return "STOP this track"
    if net <= 0:
        return "STOP as built"
    if net_lb is None or net_lb <= 0:
        return "NOT PROVEN"
    cost_x2 = track.get("net_mean_x2")
    if cost_x2 is None or cost_x2 <= 0:
        return "NOT PROVEN"
    if not track.get("beats_baselines", False):
        return "NOT PROVEN"
    if track.get("unexplained_flags"):
        return "NOT PROVEN"
    if not track.get("profit_spread_over_months", False):
        return "NOT PROVEN"
    return "CONTINUE"


def plain_sentence(track: dict, verdict: str) -> str:
    name = track.get("label") or track.get("track")
    n = int(track.get("counted") or 0)
    dates = track.get("holdout_dates") or "the holdout"
    if verdict == "RERUN":
        return f"On {dates} holdout data, {name} is not judged: an honesty check failed."
    if verdict == "TOO EARLY":
        return f"Too early to say. {n} of 300 calls so far on {name}."
    if verdict == "STOP this track":
        return f"On {dates} holdout data, {name} shows no signal before costs."
    if verdict == "STOP as built":
        return f"On {dates} holdout data, {name} lost to costs."
    if verdict == "NOT PROVEN":
        return f"After {n} calls on {name}, the Matrix is not yet better than doing nothing, after costs."
    return f"After {n} calls on {name}, the Matrix beats doing nothing by a small margin, after costs."


def overall_line(track_verdicts: list[str], step1_ok: bool) -> str:
    if not step1_ok:
        return "The backtest machine failed an honesty check. No track is judged. Fix the engine and rerun."
    if any(v == "CONTINUE" for v in track_verdicts):
        n = sum(1 for v in track_verdicts if v == "CONTINUE")
        return (
            f"{n} track(s) reached CONTINUE on holdout. That is a ticket to paper calls "
            "with the frozen rules, not to money."
        )
    return (
        "No track beats doing nothing after costs on the holdout. "
        "Stop building trading features. The measuring rules still stand."
    )


def _fmt(value, digits=6):
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _flag_lines(flags: list[str]) -> str:
    if not flags:
        return "- none"
    return "\n".join(f"- {f}" for f in flags)


def render_report(result: dict) -> str:
    tracks = result.get("tracks") or []
    step1_ok = bool(result.get("step1_ok"))
    verdicts = [step4_verdict(t, step1_ok) for t in tracks]
    lines = [overall_line(verdicts, step1_ok), ""]
    lines.append(f"K = {result.get('K')} (tracks {result.get('n_tracks')} × rule sets {result.get('rule_sets_tried')}). z = {result.get('z')}.")
    lines.append("AI/visual lenses excluded. Trend results are the 2-voter system (Markov + technical) and say nothing about the live 4-voter system.")
    lines.append("")
    lines.append("## Step 1 — is the machine honest?")
    lines.append("")
    for row in result.get("step1") or []:
        lines.append(f"- {row['check']}: {row['result']}")
    lines.append("")
    lines.append("## One-line summary (HOLDOUT)")
    lines.append("")
    lines.append("track | counted | days | K | gross mean | net mean | net_lb (daily) | net mean cost x2 | RANDOM net | verdict")
    for track, verdict in zip(tracks, verdicts):
        lines.append(
            " | ".join(
                [
                    str(track.get("label")),
                    str(track.get("counted")),
                    str(track.get("days_with_calls")),
                    str(result.get("K")),
                    _fmt(track.get("gross_mean")),
                    _fmt(track.get("net_mean")),
                    _fmt(track.get("net_lb")),
                    _fmt(track.get("net_mean_x2")),
                    _fmt(track.get("random_net")),
                    verdict,
                ]
            )
        )
    lines.append("")
    for track, verdict in zip(tracks, verdicts):
        lines.append(f"## {track.get('label')}")
        lines.append("")
        lines.append(plain_sentence(track, verdict))
        lines.append("")
        lines.append(f"Step 4 verdict: **{verdict}**")
        lines.append("")
        lines.append(f"- Split dates: train {track.get('train_dates')} | validate {track.get('validate_dates')} | holdout {track.get('holdout_dates')}")
        lines.append(f"- Days containing calls (holdout): {track.get('days_with_calls')}")
        lines.append(f"- Counted calls: {track.get('counted')}")
        if track.get("call_directions"):
            shown = ", ".join(f"{name} {n}" for name, n in sorted(track["call_directions"].items()))
            lines.append(f"- Holdout decisions by direction (SIDEWAYS and ABSTAIN are not counted): {shown}")
        if track.get("passed_cost_gate") is not None:
            lines.append(f"- Cost gate on the holdout: blocked {track.get('blocked')}, passed {track.get('passed_cost_gate')}, triggered 0 (no book, order flow stays silent)")
        lines.append(f"- K and z: {result.get('K')} / {result.get('z')}")
        lines.append(f"- Gross mean per call: {_fmt(track.get('gross_mean'))}")
        lines.append(f"- Net mean per call: {_fmt(track.get('net_mean'))}")
        lines.append(f"- net_lb on daily totals: {_fmt(track.get('net_lb'))}")
        lines.append(f"- Hit rate: {_fmt(track.get('hit_rate'), 4)}  hit_lb: {_fmt(track.get('hit_lb'), 4)}")
        bases = track.get("baselines") or {}
        lines.append(
            "- Baselines: "
            + ", ".join(f"{k}={_fmt(v, 4)}" for k, v in bases.items())
        )
        if track.get("breakeven_wr_mean") is not None:
            lines.append(f"- Scalp baseline (mean breakeven win rate): {_fmt(track.get('breakeven_wr_mean'), 4)}")
        lines.append(f"- Net mean at COST x2: {_fmt(track.get('net_mean_x2'))}  x3: {_fmt(track.get('net_mean_x3'))}")
        lines.append(f"- VALIDATE net mean: {_fmt(track.get('validate_net_mean'))}  HOLDOUT net mean: {_fmt(track.get('net_mean'))}")
        lines.append(f"- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: {track.get('wins')} / {track.get('losses')} / {track.get('timeouts')} / {track.get('blocked')} / {track.get('not_filled')}")
        lines.append(f"- Same-candle: aggTrades {track.get('same_candle_trades', 0)}, counted as loss {track.get('same_candle_loss', 0)}")
        lines.append(f"- Maker fill rate, would-be winners vs losers: {track.get('maker_fill_winners')} vs {track.get('maker_fill_losers')}")
        lines.append(f"- Max drawdown in R: {_fmt(track.get('max_dd_r'), 3)}  longest losing streak: {track.get('losing_streak')}")
        lines.append(f"- spread_assumed share: {_fmt(track.get('spread_assumed_share'), 3)}  funding_ignored share: {_fmt(track.get('funding_ignored_share'), 3)}")
        lines.append(f"- Ladder level the holdout would have reached: {track.get('level')}")
        lines.append(f"- RANDOM net mean: {_fmt(track.get('random_net'))}  PEEK net mean: {_fmt(result.get('peek_net'))}")
        lines.append("- Net by month:")
        for month, value in (track.get("net_by_month") or {}).items():
            lines.append(f"  - {month}: {_fmt(value)}")
        lines.append(f"- Net by symbol: {track.get('symbol')} {_fmt(track.get('net_mean'))}")
        lines.append("- Step 3 flags:")
        lines.append(_flag_lines(track.get("flags") or []))
        if track.get("flag_notes"):
            lines.append(f"- Flag notes: {track.get('flag_notes')}")
        lines.append("")
    lines.append("## Scope")
    lines.append("")
    for note in result.get("scope") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def write_report(result: dict, directory: Path, stem: str) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    md = directory / f"{stem}.md"
    js = directory / f"{stem}.json"
    md.write_text(render_report(result))
    js.write_text(json.dumps(result, indent=2, default=str))
    return md, js
