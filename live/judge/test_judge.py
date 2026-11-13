"""Few checks for the paper judge. No network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from ledger import (  # noqa: E402
    FrozenError,
    allow_new,
    assert_frozen,
    file_hash,
    read_ledger,
    ready_prefix,
    record_day,
)
from signals import (  # noqa: E402
    below_past,
    day_start,
    funding_boundaries,
    l1_signals,
    percentile,
    quantile,
)


def test_frozen_file_is_rejected_after_edit(tmp_path):
    path = tmp_path / "L9.json"
    path.write_text('{"id": "L9", "frozen": "2026-11-13"}\n')
    digest = file_hash(path)
    assert_frozen(path, digest)
    path.write_text('{"id": "L9", "frozen": "2026-11-13", "changed": true}\n')
    with pytest.raises(FrozenError):
        assert_frozen(path, digest)

    registered = []
    for month_id in ("N1", "N2", "N3"):
        assert allow_new(registered, month_id, "2026-12-01")
        registered.append({"id": month_id, "frozen": "2026-12-01"})
    assert allow_new(registered, "N4", "2026-12-01") is False
    assert allow_new(registered, "L1", "2026-12-01") is True

    ledger = read_ledger(ROOT / "live" / "ledger.jsonl")
    by_id = {row["id"]: row for row in ledger if row["type"] == "register"}
    for candidate_id in ("L1", "L2", "L3", "L4", "L5"):
        spec_path = ROOT / "live" / "candidates" / f"{candidate_id}.json"
        spec = json.loads(spec_path.read_text())
        assert spec["frozen"] == "2026-11-13"
        assert_frozen(spec_path, by_id[candidate_id]["sha256"])


def test_a_day_is_not_counted_twice(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    call = {
        "type": "call",
        "id": "L1",
        "day": "2026-11-14",
        "entry_ts": 1,
        "exit_ts": 2,
        "signal_ts": 1,
        "direction": "UP",
        "entry": 1.0,
        "exit": 1.01,
        "gross": 0.01,
        "funding": 0.0,
        "nets": {"0.0012": 0.0088, "0.0010": 0.009, "0.0006": 0.0094},
        "hit": True,
        "move": 1,
    }
    assert record_day(ledger, "L1", "2026-11-14", [call]) == 1
    assert record_day(ledger, "L1", "2026-11-14", [call]) == 0
    rows = read_ledger(ledger)
    assert sum(1 for row in rows if row["type"] == "call") == 1
    assert sum(1 for row in rows if row["type"] == "progress" and row["day"] == "2026-11-14") == 1


def test_catch_up_stops_at_the_missing_day():
    days = ["2026-11-14", "2026-11-15", "2026-11-16"]
    done, waiting = ready_prefix(days, {"2026-11-14", "2026-11-16"})
    assert done == ["2026-11-14"]
    assert waiting == "2026-11-15"
    done, waiting = ready_prefix(days, set(days))
    assert done == days
    assert waiting is None
    from ledger import days_to_judge

    assert days_to_judge("2026-11-13", "2026-11-14", "2026-11-16") == [
        "2026-11-15",
        "2026-11-16",
    ]


def test_percentile_uses_previous_days_only():
    past = [0.01, 0.02, 0.03, 0.04, 0.05]
    current = 1.0
    past_only = percentile(past, 0.10)
    including = quantile(past + [current], 0.10)
    assert past_only != including
    probe = (past_only + including) / 2.0
    assert below_past(probe, past, 0.10) is False
    assert probe < including

    events = [(day_start("2026-11-13") + i * 3_600_000, rate) for i, rate in enumerate(past)]
    events.append((day_start("2026-11-14") + 1_000, probe))
    spec = {"hold_hours": 8, "rule": {"lookback_days": 90, "percentile": 0.10}}
    assert l1_signals(spec, "2026-11-14", events) == []


def test_gold_funding_clock_is_every_four_hours():
    entry = day_start("2026-11-14") + 3_600_000
    exit_ts = entry + 4 * 3_600_000
    assert funding_boundaries(entry, exit_ts, (0, 8, 16)) == []
    assert funding_boundaries(entry, exit_ts, (0, 4, 8, 12, 16, 20)) == [
        day_start("2026-11-14") + 4 * 3_600_000
    ]
