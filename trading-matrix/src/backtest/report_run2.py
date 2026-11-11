"""Run 2 report. The first line is the Step 4 mix of the six tracks."""

from __future__ import annotations

_STOP = {"STOP this track", "STOP as built", "NOT PROVEN"}
_EARLY = {"TOO EARLY", "RERUN"}


def step4_run2(track: dict, step1_ok: bool) -> str:
    if not step1_ok:
        return "RERUN"
    oracle_net = track.get("oracle_net")
    if oracle_net is None:
        return "RERUN"
    if oracle_net <= 0:
        return "STOP as built"
    counted = int(track.get("counted") or 0)
    days = int(track.get("days_with_calls") or 0)
    if counted < 300 or days < 60:
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
    if track.get("net_mean_x2") is None or track["net_mean_x2"] <= 0:
        return "NOT PROVEN"
    if not track.get("beats_baselines", False):
        return "NOT PROVEN"
    if track.get("unexplained_flags"):
        return "NOT PROVEN"
    if not track.get("profit_spread_over_months", False):
        return "NOT PROVEN"
    return "CONTINUE"


def headline(verdicts: list[str]) -> str:
    kinds = set(verdicts)
    if not kinds:
        return "No track was judged."
    if kinds <= _EARLY:
        if kinds == {"RERUN"}:
            return "Every track is RERUN. An honesty check failed. No conclusions."
        if kinds == {"TOO EARLY"}:
            return "Every track is TOO EARLY. There is no verdict yet."
        return "Every track is TOO EARLY or RERUN. There is no verdict yet."
    if kinds <= _STOP:
        return "Stop building trading features. Every track is STOP as built, STOP this track, or NOT PROVEN."
    if "CONTINUE" in kinds and kinds <= {"CONTINUE"}:
        n = len(verdicts)
        return f"{n} track(s) reached CONTINUE on the holdout. That is a ticket to paper calls with the frozen rules, not to money."
    parts = ", ".join(f"{name} x {verdicts.count(name)}" for name in sorted(kinds))
    return f"Holdout verdicts are mixed: {parts}."


def _num(value, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _baselines(track: dict) -> str:
    if int(track.get("counted") or 0) == 0:
        return "n/a"
    base = track.get("baselines") or {}
    if not base:
        return "n/a"
    return ", ".join(f"{name}={_num(base.get(name), 4)}" for name in ("ALWAYS_UP", "ALWAYS_DOWN", "PERSISTENCE", "COIN", "baseline_hit"))


def _net_lb(track: dict) -> str:
    if int(track.get("counted") or 0) == 0:
        return "n/a"
    return _num(track.get("net_lb"))


def retired_markdown(run1_text: str) -> str:
    needed = [
        "window-oracle net -0.000946",
        "gross 0.000387 net -0.001813",
        "ABSTAIN 4527, SIDEWAYS 9489",
        "blocked 210160, passed 0",
    ]
    missing = [line for line in needed if line not in (run1_text or "")]
    if missing:
        return "Run 1 report is missing published figures: " + ", ".join(missing)
    return "\n".join(
        [
            "These tracks are STOP as built. The figures are quoted from reports/backtest_2026-11-11.md.",
            "",
            "- BTC trend 15m. The published window oracle cannot beat costs: window-oracle net -0.000946. PEEK line: gross 0.000387 net -0.001813. Counted directional calls: 0.",
            "- BTC quick scalps and gold quick scalps. The cost gate blocked every bar: blocked 210160, passed 0.",
            "- The both-voters trend rule. It made 0 directional calls. Published holdout decisions: ABSTAIN 4527, SIDEWAYS 9489. The two voters are opposite by design.",
        ]
    )


def render_run2(result: dict) -> str:
    tracks = result.get("tracks") or []
    step1_ok = bool(result.get("step1_ok", True))
    verdicts = [step4_run2(track, step1_ok) for track in tracks]
    lines = [headline(verdicts), ""]
    lines.append(
        f"K = {result.get('K', 6)}. z = {result.get('z', 3.09)}. rule_sets_tried = {result.get('rule_sets_tried', 2)}."
    )
    lines.append("Reported K is the six tracks. z is z_for_k(6) = 3.09. rule_sets_tried = 2 is printed so the second try is visible.")
    lines.append("")
    lines.append("## CEILING")
    lines.append("")
    lines.append("track | oracle gross | cost | oracle net | break-even hit rate")
    for track in tracks:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(track.get("label")),
                    _num(track.get("oracle_gross")),
                    _num(track.get("oracle_cost")),
                    _num(track.get("oracle_net")),
                    _num(track.get("breakeven_hit_rate")),
                ]
            )
        )
    lines.append("")
    lines.append("## Step 1")
    lines.append("")
    for row in result.get("step1") or []:
        lines.append(f"- {row.get('check')}: {row.get('result')}")
    lines.append("")
    lines.append("## One-line summary")
    lines.append("")
    lines.append("track | counted | days | K | gross mean | net mean | net_lb (daily) | net mean cost x2 | RANDOM net | verdict")
    for track, verdict in zip(tracks, verdicts):
        lines.append(
            " | ".join(
                [
                    str(track.get("label")),
                    str(track.get("counted")),
                    str(track.get("days_with_calls")),
                    str(result.get("K", 6)),
                    _num(track.get("gross_mean")) if int(track.get("counted") or 0) else "n/a",
                    _num(track.get("net_mean")) if int(track.get("counted") or 0) else "n/a",
                    _net_lb(track),
                    _num(track.get("net_mean_x2")) if int(track.get("counted") or 0) else "n/a",
                    _num(track.get("random_net")),
                    verdict,
                ]
            )
        )
    lines.append("")
    for track, verdict in zip(tracks, verdicts):
        lines.append(f"## {track.get('label')}")
        lines.append("")
        lines.append(f"Step 4 verdict: **{verdict}**")
        lines.append(f"- Holdout dates: {track.get('holdout_dates')}")
        lines.append(f"- Counted calls: {track.get('counted')}")
        lines.append(f"- Days containing calls: {track.get('days_with_calls')}")
        lines.append(f"- Gross mean per call: {_num(track.get('gross_mean')) if int(track.get('counted') or 0) else 'n/a'}")
        lines.append(f"- Net mean per call: {_num(track.get('net_mean')) if int(track.get('counted') or 0) else 'n/a'}")
        lines.append(f"- net_lb on daily totals: {_net_lb(track)}")
        lines.append(
            f"- VALIDATE net mean: {_num(track.get('validate_net_mean'))}. HOLDOUT net mean: {_num(track.get('net_mean')) if int(track.get('counted') or 0) else 'n/a'}"
        )
        months = track.get("net_by_month") or {}
        if months:
            lines.append("- Net by month: " + ", ".join(f"{m} {_num(v)}" for m, v in sorted(months.items())))
        if track.get("flags"):
            lines.append("- Flags: " + "; ".join(track["flags"]))
        lines.append(f"- Baselines: {_baselines(track)}")
        lines.append(
            f"- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: "
            f"{track.get('wins')} / {track.get('losses')} / {track.get('timeouts')} / {track.get('blocked')} / {track.get('not_filled')}"
        )
        lines.append(
            f"- Maker fill rate, would-be winners vs losers: {track.get('maker_fill_winners')} vs {track.get('maker_fill_losers')}"
        )
        lines.append(
            f"- Same-candle: aggTrades {track.get('same_candle_trades', 0)}, counted as loss {track.get('same_candle_loss', 0)}"
        )
        lines.append(f"- Hit rate: {_num(track.get('hit_rate'), 4)}  hit_lb: {_num(track.get('hit_lb'), 4)}")
        lines.append(f"- Net mean at COST x2: {_num(track.get('net_mean_x2'))}  x3: {_num(track.get('net_mean_x3'))}")
        lines.append(f"- VALIDATE net mean: {_num(track.get('validate_net_mean'))}  HOLDOUT net mean: {_num(track.get('net_mean')) if int(track.get('counted') or 0) else 'n/a'}")
        lines.append(f"- Max drawdown in R: {_num(track.get('max_dd_r'), 3)}  longest losing streak: {track.get('losing_streak')}")
        lines.append(f"- spread_assumed share: {_num(track.get('spread_assumed_share'), 3)}  funding_ignored share: {_num(track.get('funding_ignored_share'), 3)}")
        lines.append(f"- Ladder level the holdout would have reached: {track.get('level')}")
        lines.append(f"- RANDOM net mean: {_num(track.get('random_net'))}")
        lines.append(f"- Oracle gross / cost / net: {_num(track.get('oracle_gross'))} / {_num(track.get('oracle_cost'))} / {_num(track.get('oracle_net'))}")
        lines.append(f"- Break-even hit rate: {_num(track.get('breakeven_hit_rate'), 4)}")
        lines.append(f"- Strategy ran: {track.get('ran')}")
        lines.append("- Net by month:")
        for month, value in (track.get("net_by_month") or {}).items():
            lines.append(f"  - {month}: {_num(value)}")
        lines.append(f"- Net by symbol: {track.get('symbol')} {_num(track.get('net_mean')) if int(track.get('counted') or 0) else 'n/a'}")
        flags = track.get("flags") or []
        lines.append("- Step 3 flags:")
        if flags:
            for flag in flags:
                lines.append(f"  - {flag}")
        else:
            lines.append("  - none")
        if track.get("note"):
            lines.append(f"- Note: {track.get('note')}")
        lines.append("")
    lines.append("## Retired tracks")
    lines.append("")
    lines.append(retired_markdown(result.get("run1_text") or ""))
    lines.append("")
    lines.append("## SEEN PERIOD - not evidence")
    lines.append("")
    lines.append("2026-06-08 to 2026-11-01. These numbers never feed a verdict.")
    for row in result.get("seen_tracks") or []:
        lines.append(
            f"- {row.get('label')}: counted {row.get('counted')} net mean {_num(row.get('net_mean'))} (not evidence)"
        )
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    for note in result.get("scope") or []:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("## DECISION")
    lines.append("")
    for track, verdict in zip(tracks, verdicts):
        lines.append(f"- {track.get('label')}: {verdict}")
    lines.append("")
    stopped = [verdict in _STOP for verdict in verdicts]
    if any(stopped):
        lines.append("Tracks that are STOP or NOT PROVEN stop for good.")
    if any(verdict == "TOO EARLY" for verdict in verdicts):
        lines.append("Tracks that are TOO EARLY are not rerun. They continue only as live paper tracking.")
    if any(verdict == "RERUN" for verdict in verdicts):
        lines.append("An honesty check failed on the RERUN tracks. No conclusions from those tracks.")
    if verdicts and all(verdict in _STOP for verdict in verdicts):
        lines.append(
            "Stop building trading features. The measuring engine and Trader School still stand. "
            "Wait for the operator."
        )
    elif any(verdict == "CONTINUE" for verdict in verdicts):
        lines.append("A track that cleared the ladder is a ticket to paper calls with the frozen rules, not to money.")
    else:
        lines.append("This is the final rerun. Wait for the operator.")
    lines.append("")
    return "\n".join(lines)
