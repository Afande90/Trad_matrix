from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field


@dataclass
class LensResult:
    lens_name: str  # "technical" | "markov" | "entropy" | "ai_model" | "visual"
    direction: str  # "UP" | "DOWN" | "SIDEWAYS"
    confidence: float  # 0.0–1.0
    reasoning: str
    raw_data: dict = field(default_factory=dict)


class PredictionRecord(BaseModel):
    id: Optional[str] = None
    symbol: str
    asset_class: str
    timeframe: str
    prediction_direction: str
    consensus_confidence: float
    lenses: dict
    data_trust: Optional[dict] = None
    price_at_prediction: float
    verification_window_minutes: int
    outcome: Optional[str] = None
    price_at_verification: Optional[float] = None
    was_correct: Optional[bool] = None
    verified_at: Optional[str] = None
    track: Optional[str] = None
    setup_class: Optional[str] = None
    event_tag: Optional[str] = None
    blackout: bool = False
    cost_pct: Optional[float] = None
    gross_return_pct: Optional[float] = None
    net_return_pct: Optional[float] = None
    breakeven_wr: Optional[float] = None
    counts_for_graduation: bool = False
    rule_version: Optional[int] = None
    spread_assumed: bool = False
    funding_ignored: bool = False
    checkpoints: dict = Field(default_factory=dict)
