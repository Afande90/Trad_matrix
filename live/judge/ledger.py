"""Append-only paper ledger. A finished day is never written again."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class FrozenError(Exception):
    pass


OPENING = ("L1", "L2", "L3", "L4", "L5")
MAX_NEW_PER_MONTH = 3


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_frozen(path: Path, registered_hash: str) -> None:
    digest = file_hash(path)
    if digest != registered_hash:
        raise FrozenError(path.name)


def allow_new(registrations: list[dict], new_id: str, frozen: str) -> bool:
    """The opening five are already frozen. Later ids: at most 3 per month."""
    if new_id in OPENING:
        return True
    month = frozen[:7]
    count = 0
    for row in registrations:
        if row.get("id") in OPENING:
            continue
        if str(row.get("frozen", ""))[:7] == month:
            count += 1
    return count < MAX_NEW_PER_MONTH


def read_ledger(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def registrations(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("type") == "register"]


def judged_days(rows: list[dict], candidate_id: str) -> list[str]:
    days = [row["day"] for row in rows if row.get("type") == "progress" and row.get("id") == candidate_id]
    return sorted(set(days))


def calls_for(rows: list[dict], candidate_id: str) -> list[dict]:
    calls = [row for row in rows if row.get("type") == "call" and row.get("id") == candidate_id]
    calls.sort(key=lambda row: (row["entry_ts"], row["signal_ts"]))
    return calls


def call_keys(rows: list[dict]) -> set[tuple[str, int]]:
    return {(row["id"], int(row["entry_ts"])) for row in rows if row.get("type") == "call"}


def open_keys(rows: list[dict]) -> set[tuple[str, int]]:
    keys = set()
    for row in rows:
        if row.get("type") in ("open", "planned", "skipped"):
            keys.add((row["id"], int(row["entry_ts"])))
    return keys


def record_day(path: Path, candidate_id: str, day: str, items: list[dict]) -> int:
    """Append a day's new rows once. A second call for the same day writes nothing."""
    rows = read_ledger(path)
    if any(row.get("type") == "progress" and row.get("id") == candidate_id and row.get("day") == day for row in rows):
        return 0
    known_calls = call_keys(rows)
    known_rest = open_keys(rows)
    fresh = []
    for item in items:
        key = (item["id"], int(item["entry_ts"]))
        if item["type"] == "call":
            if key in known_calls:
                continue
            known_calls.add(key)
        else:
            if key in known_rest:
                continue
            known_rest.add(key)
        fresh.append(item)
    fresh.append({"type": "progress", "id": candidate_id, "day": day})
    append_rows(path, fresh)
    return len(fresh) - 1


def busy_until(rows: list[dict], candidate_id: str, day_start_ms: int) -> int:
    busy = 0
    for row in rows:
        if row.get("id") != candidate_id or row.get("type") not in ("open", "planned", "call"):
            continue
        exit_ts = int(row["exit_ts"])
        if exit_ts > day_start_ms:
            busy = max(busy, exit_ts)
    return busy


def unresolved(rows: list[dict], candidate_id: str) -> list[dict]:
    closed = call_keys(rows)
    skipped = {
        (row["id"], int(row["entry_ts"]))
        for row in rows
        if row.get("type") == "skipped"
    }
    seen = set()
    out = []
    for row in rows:
        if row.get("id") != candidate_id or row.get("type") not in ("open", "planned"):
            continue
        key = (row["id"], int(row["entry_ts"]))
        if key in closed or key in skipped or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def ready_prefix(days: list[str], present: set[str]) -> tuple[list[str], str | None]:
    """Judge in order. Stop at the first day whose files are not published yet."""
    ready = []
    for day in days:
        if day not in present:
            return ready, day
        ready.append(day)
    return ready, None


def days_to_judge(frozen: str, last_judged: str | None, yesterday: str) -> list[str]:
    from signals import shift_day

    start = shift_day(frozen, 1)
    if last_judged:
        start = max(start, shift_day(last_judged, 1))
    if start > yesterday:
        return []
    from signals import days_between

    return days_between(start, yesterday)
