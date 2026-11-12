-- DO NOT EXECUTE.
-- Supabase project trading-matrix (ref dkjwchtrrduraddkvhbh) is already live.
-- This file is a reference copy of the spec's tables plus the measurement
-- columns the live project already has. It is not a migration.

CREATE TABLE candles (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    timestamp BIGINT NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume DOUBLE PRECISION NOT NULL,
    source TEXT NOT NULL,
    UNIQUE(symbol, timestamp)
);

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE predictions (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT now(),
    symbol TEXT NOT NULL,
    asset_class TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    prediction_direction TEXT NOT NULL,
    consensus_confidence DOUBLE PRECISION,
    lenses JSONB NOT NULL,
    data_trust JSONB,
    price_at_prediction DOUBLE PRECISION NOT NULL,
    verification_window_minutes INT NOT NULL,
    outcome TEXT,
    price_at_verification DOUBLE PRECISION,
    was_correct BOOLEAN,
    verified_at TIMESTAMPTZ,
    reasoning_embedding VECTOR(768),
    track TEXT,
    setup_class TEXT,
    event_tag TEXT,
    blackout BOOLEAN DEFAULT FALSE,
    cost_pct DOUBLE PRECISION,
    gross_return_pct DOUBLE PRECISION,
    net_return_pct DOUBLE PRECISION,
    breakeven_wr DOUBLE PRECISION,
    rule_version INT,
    explain_simple TEXT,
    checkpoints JSONB
);

CREATE TABLE lens_weights (
    asset_class TEXT PRIMARY KEY,
    weights JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE accuracy_stats (
    id BIGSERIAL PRIMARY KEY,
    symbol TEXT,
    asset_class TEXT,
    scope TEXT NOT NULL,
    correct INT DEFAULT 0,
    total INT DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE rule_versions (
    id SERIAL PRIMARY KEY,
    changed_at TIMESTAMPTZ DEFAULT now(),
    description TEXT NOT NULL
);

CREATE TABLE graduation_state (
    track TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    n INT,
    hit DOUBLE PRECISION,
    hit_lb DOUBLE PRECISION,
    baseline_hit DOUBLE PRECISION,
    net_mean DOUBLE PRECISION,
    net_lb DOUBLE PRECISION,
    updated_at TIMESTAMPTZ DEFAULT now()
);
