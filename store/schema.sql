-- Local/Postgres schema. Idempotent: safe to run on every start.
-- expires_at is epoch seconds, same meaning as the DynamoDB `ttl` attribute.

CREATE TABLE IF NOT EXISTS pnd_events (
    event_id   TEXT PRIMARY KEY,
    expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS pnd_events_expires_idx ON pnd_events (expires_at);

CREATE TABLE IF NOT EXISTS pnd_sessions (
    group_id   TEXT PRIMARY KEY,
    data       JSONB NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS pnd_sessions_expires_idx ON pnd_sessions (expires_at);

CREATE TABLE IF NOT EXISTS pnd_counters (
    key        TEXT PRIMARY KEY,
    value      BIGINT NOT NULL,
    expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS pnd_counters_expires_idx ON pnd_counters (expires_at);
