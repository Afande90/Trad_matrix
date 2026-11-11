"""Run 2 report. The first line comes from the Step 4 table and from nowhere else."""

from __future__ import annotations

_STOPPED = {"STOP this track", "STOP as built", "NOT PROVEN"}


def headline(verdicts: list[str]) -> str:
    kinds = set(verdicts)
    if not kinds:
        return "No track was judged."
    if kinds <= {"TOO EARLY", "RERUN"}:
        if kinds == {"RERUN"}:
            return "Every track is RERUN. An honesty check failed. No conclusions."
        if kinds == {"TOO EARLY"}:
            return "Every track is TOO EARLY. There is no verdict yet."
        return "Every track is TOO EARLY or RERUN. There is no verdict yet."
    if kinds <= _STOPPED:
        return "Every track is STOP or NOT PROVEN. Stop building trading features. The measuring rules still stand."
    if "CONTINUE" in kinds:
        n = sum(1 for verdict in verdicts if verdict == "CONTINUE")
        return (
            f"{n} track(s) reached CONTINUE on the holdout. "
            "That is a ticket to paper calls with the frozen rules, not to money."
        )
    parts = ", ".join(f"{verdict} x {verdicts.count(verdict)}" for verdict in sorted(kinds))
    return f"Holdout verdicts are mixed: {parts}."


def decision_section(verdicts: list[str], labels: list[str]) -> str:
    lines = ["## DECISION", ""]
    for label, verdict in zip(labels, verdicts):
        lines.append(f"- {label}: {verdict}")
    lines.append("")
    if verdicts and all(verdict in _STOPPED for verdict in verdicts):
        lines.append(
            "Stop building trading features. The measuring engine and Trader School still stand."
        )
        return "\n".join(lines)
    if verdicts and "CONTINUE" not in verdicts:
        lines.append("Tracks that are STOP or NOT PROVEN stop for good.")
        if any(verdict == "TOO EARLY" for verdict in verdicts):
            lines.append(
                "Tracks that are TOO EARLY are not rerun. They continue only as live paper tracking."
            )
    if any(verdict == "CONTINUE" for verdict in verdicts):
        lines.append("CONTINUE is a ticket to paper calls with the frozen rules, not to money.")
    lines.append("This is the final rerun. Stop and wait for the operator.")
    return "\n".join(lines)


def _num(value, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_run2(result: dict) -> str:
    tracks = result["tracks"]
    verdicts = [track["verdict"] for track in tracks]
    labels = [track["label"] for track in tracks]
    lines = [headline(verdicts), "", "## CEILING", ""]
    lines.append("| track | oracle gross | cost | oracle net | break-even hit rate |")
    lines.append("|---|---:|---:|---:|---:|")
    for track in tracks:
        ceiling = track["ceiling"]
        lines.append(
            "| {label} | {g} | {c} | {n} | {b} |".format(
                label=track["label"],
                g=_num(ceiling.get("gross_mean")),
                c=_num(ceiling.get("cost")),
                n=_num(ceiling.get("net_mean")),
                b=_num(ceiling.get("breakeven_hit_rate")),
            )
        )
    lines += ["", "## Step 1", ""]
    for row in result.get("step1", []):
        lines.append(f"- {row['check']}: {row['result']}")
    lines += ["", "## One-line summary", ""]
    lines.append("| track | counted | days | K | gross mean | net mean | net_lb daily | net mean cost x2 | RANDOM net | verdict |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for track in tracks:
        lines.append(
            "| {label} | {counted} | {days} | {k} | {g} | {n} | {lb} | {x2} | {r} | {v} |".format(
                label=track["label"],
                counted=track.get("counted", 0),
                days=track.get("days_with_calls", 0),
                k=result.get("K", 6),
                g=_num(track.get("gross_mean")),
                n=_num(track.get("net_mean")),
                lb=_num(track.get("net_lb")),
                x2=_num(track.get("net_mean_x2")),
                r=_num(track.get("random_net")),
                v=track["verdict"],
            )
        )
    lines += ["", "K = {k}. z = {z}. rule_sets_tried = {tried}.".format(
        k=result.get("K", 6), z=result.get("z", 3.09), tried=result.get("rule_sets_tried", 2)
    ), ""]
    for track in tracks:
        lines += [f"## {track['label']}", ""]
        base = track.get("baselines") or {}
        lines.append(
            "baselines: "
            + " ".join(f"{name}={_num(base.get(name))}" for name in ("ALWAYS_UP", "ALWAYS_DOWN", "PERSISTENCE", "COIN", "baseline_hit"))
        )
        lines.append(f"net_lb (daily): {_num(track.get('net_lb'))}")
        for extra in track.get("detail_lines") or []:
            lines.append(extra)
        lines.append("")
    lines += ["## Retired tracks", "", result.get("retired_note", ""), ""]
    lines += ["## SEEN PERIOD - not evidence", ""]
    for row in result.get("seen", []):
        lines.append(f"- {row.get('label', 'seen')}: net mean {_num(row.get('net_mean'))} (not a verdict)")
    lines += ["", "## Scope", "", result.get("scope", "Rule set 2. Dev months were a sanity check only."), ""]
    lines.append(decision_section(verdicts, labels))
    lines.append("")
    return "\n".join(lines)
