"""Run 3 report. The first line is the holdout Step 4 verdict and nothing else."""

from __future__ import annotations

from src.backtest.report_run2 import _num, baseline_line, drawdown_line, step4_run2

_STOP = {"STOP this track", "STOP as built", "NOT PROVEN"}


def headline(verdict: str) -> str:
    if verdict == "TOO EARLY":
        return "TOO EARLY. The holdout does not yet have 300 calls and 60 days."
    if verdict == "RERUN":
        return "RERUN. An honesty check failed. No conclusions."
    if verdict == "CONTINUE":
        return "CONTINUE on the holdout. That is a ticket to paper calls with the frozen rules, not to money."
    if verdict in _STOP:
        return f"Stop building trading features. The complete-sentence rule is {verdict}."
    return verdict


def render_run3(result: dict) -> str:
    track = result["track"]
    verdict = step4_run2(track, bool(result.get("step1_ok", True)))
    lines = [
        headline(verdict),
        "",
        f"K = {result.get('K', 2)}. z = {result.get('z', 2.88)}. rule_sets_tried = {result.get('rule_sets_tried', 3)}.",
        "K is the two train variants. z is z_for_k(2) = 2.88. rule_sets_tried = 3 counts this rule set after run 1 and run 2.",
        "",
        "## CEILING",
        "",
        "track | oracle gross | cost | oracle net | break-even hit rate",
        "| "
        + " | ".join(
            [
                str(track.get("label")),
                _num(track.get("oracle_gross")),
                _num(track.get("oracle_cost")),
                _num(track.get("oracle_net")),
                _num(track.get("breakeven_hit_rate")),
            ]
        ),
        "",
        "## Step 1",
        "",
    ]
    for row in result.get("step1") or []:
        lines.append(f"- {row.get('check')}: {row.get('result')}")
    lines += ["", "## TRAIN", ""]
    lines.append(f"Kept variant: {result.get('kept')}. {result.get('keep_reason')}")
    lines.append("")
    lines.append("variant | counted | days | gross mean | net mean")
    for name in ("WITH", "AGAINST"):
        row = (result.get("train") or {}).get(name) or {}
        lines.append(
            " | ".join(
                [
                    name,
                    str(row.get("counted")),
                    str(row.get("days_with_calls")),
                    _num(row.get("gross_mean")) if int(row.get("counted") or 0) else "n/a",
                    _num(row.get("net_mean")) if int(row.get("counted") or 0) else "n/a",
                ]
            )
        )
    lines += ["", "## HOLDOUT", ""]
    lines.append("track | counted | days | K | gross mean | net mean | net_lb (daily) | net mean cost x2 | RANDOM net | verdict")
    counted = int(track.get("counted") or 0)
    lines.append(
        " | ".join(
            [
                str(track.get("label")),
                str(counted),
                str(track.get("days_with_calls")),
                str(result.get("K", 2)),
                _num(track.get("gross_mean")) if counted else "n/a",
                _num(track.get("net_mean")) if counted else "n/a",
                "n/a" if counted == 0 else _num(track.get("net_lb")),
                _num(track.get("net_mean_x2")) if counted else "n/a",
                _num(track.get("random_net")),
                verdict,
            ]
        )
    )
    lines.append("")
    lines.append(f"### {track.get('label')}")
    lines.append("")
    lines.append(f"Step 4 verdict: **{verdict}**")
    lines.append(f"- Holdout dates: {track.get('holdout_dates')}")
    lines.append(f"- Counted calls: {counted}")
    lines.append(f"- Days containing calls: {track.get('days_with_calls')}")
    lines.append(f"- Gross mean per call: {_num(track.get('gross_mean')) if counted else 'n/a'}")
    lines.append(f"- Net mean per call: {_num(track.get('net_mean')) if counted else 'n/a'}")
    lines.append(f"- net_lb on daily totals: {'n/a' if counted == 0 else _num(track.get('net_lb'))}")
    lines.append(
        f"- TRAIN net mean: {_num((result.get('train') or {}).get(result.get('kept'), {}).get('net_mean'))}. "
        f"VALIDATE net mean: n/a. HOLDOUT net mean: {_num(track.get('net_mean')) if counted else 'n/a'}"
    )
    months = track.get("net_by_month") or {}
    if months:
        lines.append("- Net by month: " + ", ".join(f"{month} {_num(value)}" for month, value in sorted(months.items())))
    lines.append(f"- Baselines: {baseline_line(track)}")
    lines.append(
        "- Wins / losses / timeouts / blocked-by-cost / NOT_FILLED: "
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
    lines.append(drawdown_line(track))
    lines.append(
        f"- spread_assumed share: {_num(track.get('spread_assumed_share'), 3)}  "
        f"funding_ignored share: {_num(track.get('funding_ignored_share'), 3)}"
    )
    lines.append(f"- Ladder level the holdout would have reached: {track.get('level')}")
    lines.append(f"- RANDOM net mean: {_num(track.get('random_net'))}")
    lines.append(
        f"- Oracle gross / cost / net: {_num(track.get('oracle_gross'))} / {_num(track.get('oracle_cost'))} / {_num(track.get('oracle_net'))}"
    )
    lines.append(f"- Break-even hit rate: {_num(track.get('breakeven_hit_rate'), 4)}")
    if track.get("note"):
        lines.append(f"- Note: {track.get('note')}")
    lines += ["", "## Scope", ""]
    for note in result.get("scope") or []:
        lines.append(f"- {note}")
    lines += ["", "## DIAGNOSTIC - not evidence", ""]
    lines.append("Holdout calls and net mean with one role switched off. These rows do not feed the verdict.")
    lines.append("")
    lines.append("role switched off | counted | net mean")
    for row in result.get("diagnostic") or []:
        lines.append(f"| {row.get('role')} | {row.get('counted')} | {_num(row.get('net_mean'))}")
    lines += ["", "## DECISION", "", f"- {track.get('label')}: {verdict}", ""]
    if verdict in _STOP:
        lines.append(
            "Stop building trading features. The measuring engine and Trader School still stand. "
            "This is the only test of this rule. Do not try other variants. Wait for the operator."
        )
    elif verdict == "TOO EARLY":
        lines.append(
            "TOO EARLY is not rerun. It continues only as live paper tracking. "
            "This is the only test of this rule. Do not try other variants. Wait for the operator."
        )
    elif verdict == "CONTINUE":
        lines.append(
            "CONTINUE is a ticket to paper calls with the frozen rules, not to money. "
            "This is the only test of this rule. Do not try other variants. Wait for the operator."
        )
    else:
        lines.append("This is the only test of this rule. Do not try other variants. Wait for the operator.")
    lines.append("")
    return "\n".join(lines)
