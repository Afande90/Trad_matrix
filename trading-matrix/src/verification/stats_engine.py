"""Accuracy rows. ABSTAIN (was_correct None) is not counted."""

from __future__ import annotations


def empty_stats() -> dict:
    return {}


def _bump(stats: dict, key: str, correct: bool) -> None:
    row = stats.setdefault(key, {"correct": 0, "total": 0})
    row["total"] += 1
    if correct:
        row["correct"] += 1


def record_verification(
    stats: dict,
    *,
    symbol: str,
    asset_class: str,
    was_correct: bool | None,
    entropy_regime: str | None,
    trust_tag: str | None,
    lens_directions: dict[str, str],
    actual: str | None,
) -> dict:
    if was_correct is None:
        return stats
    _bump(stats, "overall", was_correct)
    _bump(stats, f"symbol:{symbol}", was_correct)
    _bump(stats, f"asset_class:{asset_class}", was_correct)
    if entropy_regime:
        _bump(stats, f"regime:{entropy_regime}", was_correct)
    if trust_tag:
        _bump(stats, f"trust:{trust_tag}", was_correct)
    for name, direction in lens_directions.items():
        if actual is None:
            continue
        _bump(stats, f"per_lens:{name}", direction == actual)
    return stats
