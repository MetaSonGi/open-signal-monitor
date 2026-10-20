
CREATE TABLE IF NOT EXISTS db_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO db_version VALUES(2);
CREATE TABLE IF NOT EXISTS assets(
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 location TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'equipment');
CREATE TABLE IF NOT EXISTS sources(
 id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id),
 name TEXT NOT NULL, protocol TEXT NOT NULL, config_json TEXT NOT NULL,
 interval_s REAL NOT NULL CHECK(interval_s>=0.2));
CREATE TABLE IF NOT EXISTS signals(
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
 key TEXT NOT NULL, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT '',
 scale REAL NOT NULL DEFAULT 1, offset REAL NOT NULL DEFAULT 0,
 low_limit REAL, high_limit REAL, stale_s REAL NOT NULL DEFAULT 30,
 UNIQUE(source_id,key));
CREATE TABLE IF NOT EXISTS acquisition_runs(
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
 started_utc TEXT NOT NULL, stopped_utc TEXT, config_snapshot TEXT NOT NULL,
 stop_reason TEXT);
CREATE TABLE IF NOT EXISTS production_runs(
 id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id),
 work_order TEXT NOT NULL, product TEXT NOT NULL, lot TEXT NOT NULL,
 process TEXT NOT NULL, operating_state TEXT NOT NULL,
 started_utc TEXT NOT NULL, ended_utc TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_production ON production_runs(asset_id) WHERE ended_utc IS NULL;
CREATE TABLE IF NOT EXISTS telemetry(
 id INTEGER PRIMARY KEY, signal_id INTEGER NOT NULL REFERENCES signals(id),
 run_id INTEGER NOT NULL REFERENCES acquisition_runs(id),
 production_id INTEGER REFERENCES production_runs(id),
 source_utc TEXT NOT NULL, ingested_utc TEXT NOT NULL,
 raw_json TEXT, value REAL, quality TEXT NOT NULL, detail TEXT NOT NULL,
 latency_ms REAL NOT NULL, unit TEXT NOT NULL, scale REAL NOT NULL, offset REAL NOT NULL,
 signal_key TEXT NOT NULL, signal_name TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS telemetry_signal_time ON telemetry(signal_id,source_utc);
CREATE INDEX IF NOT EXISTS telemetry_signal_id ON telemetry(signal_id,id);
CREATE INDEX IF NOT EXISTS telemetry_ingest ON telemetry(ingested_utc);
CREATE INDEX IF NOT EXISTS telemetry_production ON telemetry(production_id);
CREATE TABLE IF NOT EXISTS labels(
 id INTEGER PRIMARY KEY, asset_id INTEGER NOT NULL REFERENCES assets(id),
 started_utc TEXT NOT NULL, ended_utc TEXT NOT NULL, category TEXT NOT NULL,
 note TEXT NOT NULL, created_utc TEXT NOT NULL,
 CHECK(ended_utc>=started_utc));
CREATE INDEX IF NOT EXISTS labels_asset_time ON labels(asset_id,started_utc,ended_utc);
CREATE TABLE IF NOT EXISTS incidents(
 id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
 occurred_utc TEXT NOT NULL, message TEXT NOT NULL);
