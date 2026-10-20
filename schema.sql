-- OpenSignal Monitor: new independent SQLite schema

PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS schema_meta(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_meta VALUES(1);
CREATE TABLE IF NOT EXISTS devices(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, host TEXT NOT NULL,
 port INTEGER NOT NULL, unit_id INTEGER NOT NULL, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 id INTEGER PRIMARY KEY, device_id INTEGER NOT NULL REFERENCES devices(id),
 started_utc TEXT NOT NULL, stopped_utc TEXT, function_code INTEGER NOT NULL,
 start_address INTEGER NOT NULL, register_count INTEGER NOT NULL,
 interval_seconds REAL NOT NULL, scale REAL NOT NULL, signed INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS channels(
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
 address INTEGER NOT NULL, label TEXT NOT NULL, UNIQUE(session_id,address));
CREATE TABLE IF NOT EXISTS readings(
 id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL REFERENCES channels(id),
 captured_utc TEXT NOT NULL, raw_u16 INTEGER NOT NULL CHECK(raw_u16 BETWEEN 0 AND 65535),
 value REAL NOT NULL, latency_ms REAL NOT NULL);
CREATE INDEX IF NOT EXISTS readings_channel_time ON readings(channel_id,captured_utc);
CREATE TABLE IF NOT EXISTS events(
 id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
 occurred_utc TEXT NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
