"""Phone-length status. The ladder is only moved on the 1st of a month."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledger import calls_for, judged_days, registrations, unresolved
from signals import COSTS, LADDER_COST, shift_day

DUBAI = timezone(timedelta(hours=4))


def _package() -> None:
    root = Path(__file__).resolve().parents[2]
    pkg = str(root / "trading-matrix")
    if pkg not in sys.path:
        sys.path.insert(0, pkg)


def pretty_day(day: str) -> str:
    dt = datetime.strptime(day, "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%b')} {dt.year}"


def pretty_time(now: datetime) -> str:
    utc = now.astimezone(timezone.utc)
    dubai = now.astimezone(DUBAI)
    return (
        f"{dubai.day} {dubai.strftime('%b')} {dubai.year}, "
        f"{dubai.strftime('%H:%M')} Asia/Dubai ({utc.strftime('%H:%M')} UTC)"
    )


def _pct(value: float) -> str:
    return f"{value * 100:+.3f}%"


def _mean(calls: list[dict], cost: float) -> str:
    if not calls:
        return "n/a"
    key = f"{cost:.4f}"
    return _pct(sum(float(call["nets"][key]) for call in calls) / len(calls))


def evaluation_day(frozen: str, last_day: str | None) -> str | None:
    """The latest 1st of a month that has arrived after the freeze."""
    if not last_day:
        return None
    cursor = datetime.strptime(shift_day(frozen, 1), "%Y-%m-%d")
    end = datetime.strptime(last_day, "%Y-%m-%d")
    found = None
    while cursor <= end:
        if cursor.day == 1:
            found = cursor.strftime("%Y-%m-%d")
        cursor += timedelta(days=1)
    return found


def ladder_level(calls: list[dict], judged: list[str], as_of: str | None, k: int) -> tuple[str, str]:
    counted = calls
    if as_of:
        counted = [call for call in calls if call["day"] < as_of]
    n = len(counted)
    if as_of is None or n < 100:
        if n < 300:
            return "Observer", f"Too early: {n} of 300 calls."
        return "Observer", (
            f"Too early: {n} calls. The ladder is next scored on the 1st of the month."
        )
    _package()
    from src.verification.graduation import baselines_from_moves, evaluate_level, z_for_k

    moves = [int(call["move"]) for call in counted]
    prev = [0] + moves[:-1]
    baseline = baselines_from_moves(moves, prev)["baseline_hit"]
    calendar = [day for day in judged if day < as_of]
    shaped = []
    for call in counted:
        shaped.append(
            {
                "day": call["day"],
                "hit": bool(call["hit"]),
                "net": float(call["nets"][f"{LADDER_COST:.4f}"]),
                "since_rule_change": True,
                "risk": 0.0,
            }
        )
    level = evaluate_level(shaped, baseline, z_for_k(k), calendar=calendar or None)
    sentence = {
        "Observer": f"Still Observer after {n} calls. The ladder has not moved up.",
        "Learner": f"Learner: the direction has beaten doing nothing over {n} calls. Not Competent yet.",
        "Competent": f"Competent on paper over {n} calls. Still no real money.",
        "Advisor": f"Advisor on paper over {n} calls. Still no real money.",
        "Expert": f"Expert on paper over {n} calls. Still no real money.",
    }[level]
    if n < 300:
        sentence = f"Too early: {n} of 300 calls."
    return level, sentence


def render(rows: list[dict], specs: list[dict], now: datetime, waiting: dict[str, str], archive: list[str]) -> str:
    k = len(registrations(rows)) or len(specs)
    _package()
    from src.verification.graduation import z_for_k

    lines = [
        "No real money. Nothing here is proven until the ladder says Competent.",
        "",
        f"Last checked: {pretty_time(now)}.",
        "Next daily run: 06:00 UTC.",
        f"The ladder uses cost {LADDER_COST:.4f}. Nets at {COSTS[1]:.4f} and {COSTS[2]:.4f} are shown beside it.",
        f"{k} candidates are registered, so the luck bar is {z_for_k(k):.2f}.",
        "The ladder is scored on the 1st of each month, at every 100 calls.",
        "After this opening five, at most 3 new candidates can be frozen in one calendar month.",
        "",
    ]
    if archive:
        lines.append("Archive:")
        for note in archive:
            lines.append(note)
        lines.append("")
    last_days = []
    for spec in specs:
        judged = judged_days(rows, spec["id"])
        if judged:
            last_days.append(judged[-1])
    last_day = max(last_days) if last_days else None
    for spec in specs:
        judged = judged_days(rows, spec["id"])
        calls = calls_for(rows, spec["id"])
        as_of = evaluation_day(spec["frozen"], last_day)
        level, sentence = ladder_level(calls, judged, as_of, k)
        opens = unresolved(rows, spec["id"])
        lines.append(f"{spec['id']}. {spec['name']}")
        lines.append(
            f"Frozen {pretty_day(spec['frozen'])}. Days running: {len(judged)}. Calls: {len(calls)}."
        )
        lines.append(
            "Net per call: "
            + ", ".join(f"{_mean(calls, cost)} at {cost:.4f}" for cost in COSTS)
            + "."
        )
        lines.append(f"Ladder: {level}.")
        lines.append(sentence)
        if opens:
            lines.append(f"Trades still open: {len(opens)}. They are not counted yet.")
        if spec["id"] in waiting:
            lines.append(waiting[spec["id"]])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
