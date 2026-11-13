"""Daily paper judge. Downloads yesterday, scores that day, appends the ledger.

A file that is not published yet stops that candidate. The next run retries
the same day, then catches up. A day already in the ledger is not scored again.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from download import (  # noqa: E402
    ensure,
    head_ok,
    needed,
    plain_name,
    read_flow,
    read_funding,
    read_funding_interval,
    read_klines,
    read_metrics,
    shift_month,
    url_for,
)
from ledger import (  # noqa: E402
    FrozenError,
    allow_new,
    append_rows,
    assert_frozen,
    busy_until,
    call_keys,
    days_to_judge,
    file_hash,
    judged_days,
    read_ledger,
    record_day,
    registrations,
    unresolved,
)
from signals import (  # noqa: E402
    day_of,
    day_start,
    funding_boundaries,
    funding_covered,
    make_call,
    shift_day,
    signals_for,
)
from status import pretty_day, render  # noqa: E402

CANDIDATES = ROOT / "live" / "candidates"
LEDGER = ROOT / "live" / "ledger.jsonl"
STATUS = ROOT / "live" / "STATUS.md"
CACHE = ROOT / "live" / ".cache"


def load_specs() -> list[dict]:
    specs = []
    for path in sorted(CANDIDATES.glob("*.json")):
        specs.append(json.loads(path.read_text()))
    return specs


def register_missing(specs: list[dict], rows: list[dict]) -> list[dict]:
    known = {row["id"] for row in registrations(rows)}
    fresh = []
    for spec in specs:
        if spec["id"] in known:
            continue
        if not allow_new(registrations(rows) + fresh, spec["id"], spec["frozen"]):
            continue
        path = CANDIDATES / f"{spec['id']}.json"
        fresh.append(
            {
                "type": "register",
                "id": spec["id"],
                "frozen": spec["frozen"],
                "name": spec["name"],
                "sha256": file_hash(path),
            }
        )
    if fresh:
        append_rows(LEDGER, fresh)
    return fresh


def blocked(specs: list[dict], rows: list[dict]) -> dict[str, str]:
    registered = {row["id"]: row for row in registrations(rows)}
    reasons = {}
    for spec in specs:
        row = registered.get(spec["id"])
        path = CANDIDATES / f"{spec['id']}.json"
        if row is None:
            reasons[spec["id"]] = (
                f"Not registered. {spec['frozen'][:7]} already has 3 new candidates, "
                "so this one is not judged."
            )
            continue
        try:
            assert_frozen(path, row["sha256"])
        except FrozenError:
            reasons[spec["id"]] = (
                "This candidate file was edited after its frozen date. "
                "The judge will not use it. A change needs a new id."
            )
    return reasons


class Store:
    def __init__(self, cache: Path):
        self.cache = cache
        self.missing: set[tuple] = set()
        self.parsed: dict[tuple, object] = {}

    def path(self, key: tuple) -> Path | None:
        if key in self.missing:
            return None
        found = ensure(self.cache, key)
        if found is None:
            self.missing.add(key)
            return None
        return found

    def value(self, key: tuple):
        if key in self.parsed:
            return self.parsed[key]
        path = self.path(key)
        if path is None:
            self.parsed[key] = None
            return None
        kind = key[0]
        if kind == "funding":
            data = read_funding(path)
        elif kind == "metrics":
            data = read_metrics(path)
        elif kind == "agg":
            data = read_flow(path)
        else:
            data = read_klines(path)
        self.parsed[key] = data
        return data


def first_missing(spec: dict, day: str, store: Store) -> tuple | None:
    for key in needed(spec, day):
        if store.path(key) is None:
            return key
    return None


def build_book(spec: dict, day: str, store: Store) -> dict:
    book = {
        "fut": {},
        "spot": {},
        "xau": {},
        "index": {},
        "funding": [],
        "oi": [],
        "flow": [],
        "funding_months": set(),
    }
    gold = spec["rule"]["kind"] == "index_gap_below_percentile"
    for key in needed(spec, day):
        data = store.value(key)
        kind = key[0]
        if kind == "fut":
            target = book["xau"] if gold else book["fut"]
            target.update(data)
        elif kind == "spot":
            book["spot"].update(data)
        elif kind == "index":
            book["index"].update(data)
        elif kind == "funding":
            book["funding"].extend(data)
            book["funding_months"].add(key[2])
        elif kind == "metrics":
            book["oi"].extend(data)
        elif kind == "agg":
            book["flow"].extend(data)
    book["funding"].sort()
    book["oi"].sort()
    return book


def funding_hours(symbol: str, exit_ts: int, store: Store) -> tuple[int, ...] | None:
    """Print times from the newest funding file we can actually read."""
    month = day_of(exit_ts)[:7]
    for back in range(0, 4):
        path = store.path(("funding", symbol, shift_month(month, -back)))
        if path is None:
            continue
        interval = read_funding_interval(path)
        return tuple(range(0, 24, interval))
    return None


def funding_bundle(symbol: str, entry_ts: int, exit_ts: int, store: Store):
    """Events in the hold. A hold that crosses no known print needs no file."""
    hours = funding_hours(symbol, exit_ts, store)
    if hours is None:
        return None
    marks = funding_boundaries(entry_ts, exit_ts, hours)
    if not marks:
        return []
    events = []
    present = set()
    for month in sorted({day_of(mark)[:7] for mark in marks}):
        data = store.value(("funding", symbol, month))
        if data is None:
            return None
        events.extend(data)
        present.add(month)
    events.sort()
    if not funding_covered(entry_ts, exit_ts, present, hours):
        return None
    return events


def candle_lookup(symbol: str, ts: int, store: Store, yesterday: str):
    day = day_of(ts)
    if day > yesterday:
        return None, False
    data = store.value(("fut", symbol, day))
    if data is None:
        return None, False
    if ts not in data:
        return None, True
    return data[ts][0], True


def materialize(spec: dict, signal: dict, book: dict, store: Store, yesterday: str, day: str) -> dict:
    base = {
        "id": spec["id"],
        "day": day_of(signal["entry_ts"]),
        "signal_ts": signal["signal_ts"],
        "entry_ts": signal["entry_ts"],
        "exit_ts": signal["exit_ts"],
        "direction": signal["direction"],
    }
    symbol = spec["symbol"]
    candles = book["xau"] if spec["rule"]["kind"] == "index_gap_below_percentile" else book["fut"]
    entry_row = candles.get(signal["entry_ts"])
    exit_row = candles.get(signal["exit_ts"])
    if entry_row is None:
        if day_of(signal["entry_ts"]) > day:
            return {**base, "type": "planned"}
        return {**base, "type": "skipped", "reason": "entry minute is not in the published file"}
    entry_px = entry_row[0]
    exit_px = None if exit_row is None else exit_row[0]
    if exit_px is None and day_of(signal["exit_ts"]) <= yesterday:
        looked, published = candle_lookup(symbol, signal["exit_ts"], store, yesterday)
        if published and looked is None:
            return {**base, "type": "skipped", "reason": "exit minute is not in the published file"}
        exit_px = looked
    events = funding_bundle(symbol, signal["entry_ts"], signal["exit_ts"], store)
    if exit_px is None or events is None:
        return {**base, "type": "open", "entry": entry_px, "exit": exit_px}
    signal = {**signal, "direction": base["direction"]}
    return make_call(spec["id"], signal, entry_px, exit_px, events)


def settle(spec: dict, rows: list[dict], store: Store, yesterday: str) -> list[dict]:
    fresh = []
    known = call_keys(rows)
    for row in unresolved(rows, spec["id"]):
        if day_of(int(row["exit_ts"])) > yesterday:
            continue
        entry_px = row.get("entry")
        exit_px = row.get("exit")
        published_entry = True
        published_exit = True
        if entry_px is None:
            entry_px, published_entry = candle_lookup(spec["symbol"], int(row["entry_ts"]), store, yesterday)
        if exit_px is None:
            exit_px, published_exit = candle_lookup(spec["symbol"], int(row["exit_ts"]), store, yesterday)
        if published_entry and entry_px is None:
            fresh.append({**row, "type": "skipped", "reason": "entry minute is not in the published file"})
            continue
        if published_exit and exit_px is None:
            fresh.append({**row, "type": "skipped", "reason": "exit minute is not in the published file"})
            continue
        if entry_px is None or exit_px is None:
            continue
        events = funding_bundle(spec["symbol"], int(row["entry_ts"]), int(row["exit_ts"]), store)
        if events is None:
            continue
        key = (spec["id"], int(row["entry_ts"]))
        if key in known:
            continue
        signal = {
            "signal_ts": int(row["signal_ts"]),
            "entry_ts": int(row["entry_ts"]),
            "exit_ts": int(row["exit_ts"]),
            "direction": row["direction"],
        }
        fresh.append(make_call(spec["id"], signal, float(entry_px), float(exit_px), events))
        known.add(key)
    return fresh


def archive_notes(yesterday: str) -> list[str]:
    notes = [
        "BTC funding has no daily file on data.binance.vision. "
        "The judge reads the monthly funding file and waits when that month is not up yet."
    ]
    checks = [
        (("fut", "BTCUSDT", yesterday), f"BTC futures 1-minute file for {pretty_day(yesterday)}"),
        (("spot", "BTCUSDT", yesterday), f"BTC spot 1-minute file for {pretty_day(yesterday)}"),
        (("metrics", yesterday), f"BTC open interest for {pretty_day(yesterday)}"),
        (("agg", yesterday), f"BTC aggTrades for {pretty_day(yesterday)}"),
        (("fut", "XAUUSDT", yesterday), f"Gold perpetual 1-minute file for {pretty_day(yesterday)}"),
        (("index", "XAUUSDT", yesterday), f"Gold index 1-minute file for {pretty_day(yesterday)}"),
        (("funding", "BTCUSDT", yesterday[:7]), f"BTC funding file for {yesterday[:7]}"),
        (("funding", "XAUUSDT", yesterday[:7]), f"Gold funding file for {yesterday[:7]}"),
    ]
    for key, label in checks:
        try:
            ok = head_ok(url_for(key))
        except Exception as exc:
            notes.append(f"Could not check {label}: {exc.__class__.__name__}.")
            continue
        if not ok:
            notes.append(f"{label} is not published yet.")
    return notes


def judge(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    yesterday = (now.date() - timedelta(days=1)).isoformat()
    specs = load_specs()
    register_missing(specs, read_ledger(LEDGER))
    rows = read_ledger(LEDGER)
    refused = blocked(specs, rows)
    store = Store(CACHE)
    waiting = dict(refused)
    for spec in specs:
        if spec["id"] in refused:
            continue
        settled = settle(spec, rows, store, yesterday)
        if settled:
            append_rows(LEDGER, settled)
            rows = read_ledger(LEDGER)
        judged = judged_days(rows, spec["id"])
        last = judged[-1] if judged else None
        pending = days_to_judge(spec["frozen"], last, yesterday)
        if not pending:
            waiting[spec["id"]] = (
                f"No day after the freeze has finished yet. "
                f"The first day that counts is {pretty_day(shift_day(spec['frozen'], 1))}."
            )
            continue
        for day in pending:
            missing = first_missing(spec, day, store)
            if missing is not None:
                waiting[spec["id"]] = (
                    f"Waiting on {plain_name(missing)}. "
                    f"It is not published yet, so {pretty_day(day)} is not skipped. "
                    "The next run will try this day again, then catch up."
                )
                break
            book = build_book(spec, day, store)
            signals = signals_for(spec, day, book)
            busy = busy_until(rows, spec["id"], day_start(day))
            items = []
            for signal in signals:
                if signal["entry_ts"] < busy:
                    continue
                item = materialize(spec, signal, book, store, yesterday, day)
                items.append(item)
                if item["type"] != "skipped":
                    busy = signal["exit_ts"]
            record_day(LEDGER, spec["id"], day, items)
            rows = read_ledger(LEDGER)
    archive = archive_notes(yesterday)
    STATUS.write_text(render(read_ledger(LEDGER), specs, now, waiting, archive))


def main() -> None:
    judge()


if __name__ == "__main__":
    main()
