"""The holdout seal, and the cost arithmetic. No prices are read."""

import pytest

from src.backtest.cheap_futures_holdout import assert_sealed, nets_for


def test_2026_stays_sealed():
    assert_sealed("2024-12", "2025-12")
    with pytest.raises(RuntimeError):
        assert_sealed("2025-12", "2026-01")
    with pytest.raises(RuntimeError):
        assert_sealed("2026-01", "2026-01")


def test_triple_cost_charges_funding_once():
    net, doubled, tripled = nets_for(0.01, 0.001, 0.0004)
    assert net == pytest.approx(0.01 - 0.0004 - 0.001)
    assert doubled == pytest.approx(0.01 - 0.0008 - 0.001)
    assert tripled == pytest.approx(0.01 - 0.0012 - 0.001)
