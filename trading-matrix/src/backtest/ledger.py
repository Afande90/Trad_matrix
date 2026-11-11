"""Holdout ledger. A second run with a different rules hash on an overlapping
holdout is refused. The rules file is hashed, not the prose of the report.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class HoldoutRefused(RuntimeError):
    pass


def rules_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    if not path.exists():
        return {"runs": []}
    return json.loads(path.read_text())


def _overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return a_start <= b_end and b_start <= a_end


def register_holdout(ledger_path: Path, rules_path: Path, holdout_start: str, holdout_end: str, symbols: list[str]) -> dict:
    if not rules_path.exists():
        raise HoldoutRefused("holdout requires frozen_rules.json written before the run")
    digest = rules_hash(rules_path)
    ledger = _load(ledger_path)
    for run in ledger["runs"]:
        if _overlaps(run["holdout_start"], run["holdout_end"], holdout_start, holdout_end) and run["rules_hash"] != digest:
            raise HoldoutRefused(
                "overlapping holdout already ran under a different rules hash "
                f"{run['rules_hash'][:12]}"
            )
    record = {
        "rules_hash": digest,
        "holdout_start": holdout_start,
        "holdout_end": holdout_end,
        "symbols": list(symbols),
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    # Same hash + same window is a replay of the frozen rules, not a new try.
    if not any(
        r["rules_hash"] == digest and r["holdout_start"] == holdout_start and r["holdout_end"] == holdout_end
        for r in ledger["runs"]
    ):
        ledger["runs"].append(record)
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(json.dumps(ledger, indent=2))
    return record
