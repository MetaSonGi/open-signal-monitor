"""New standalone schema. No legacy database or production data is used."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


SCHEMA = '''
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
'''


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db
        finally:
            db.close()

    def begin(self, config):
        with self.connect() as db:
            device = db.execute('INSERT INTO devices(name,host,port,unit_id,created_utc) VALUES(?,?,?,?,?)',
                (config['name'], config['host'], config['port'], config['unit'], now())).lastrowid
            session = db.execute('INSERT INTO sessions(device_id,started_utc,function_code,start_address,register_count,interval_seconds,scale,signed) VALUES(?,?,?,?,?,?,?,?)',
                (device, now(), config['function'], config['address'], config['count'], config['interval'], config['scale'], config['signed'])).lastrowid
            channels = [db.execute('INSERT INTO channels(session_id,address,label) VALUES(?,?,?)',
                (session, a, f'R{a}')).lastrowid for a in range(config['address'], config['address'] + config['count'])]
        return session, channels

    def record(self, channels, raw, values, latency):
        timestamp = now()
        with self.connect() as db:
            db.executemany('INSERT INTO readings(channel_id,captured_utc,raw_u16,value,latency_ms) VALUES(?,?,?,?,?)',
                [(c, timestamp, r, v, latency) for c, r, v in zip(channels, raw, values)])
        return timestamp

    def event(self, session, message):
        with self.connect() as db:
            db.execute('INSERT INTO events(session_id,occurred_utc,level,message) VALUES(?,?,?,?)', (session, now(), 'ERROR', message))

    def finish(self, session):
        with self.connect() as db:
            db.execute('UPDATE sessions SET stopped_utc=? WHERE id=?', (now(), session))

    def history(self, limit=1000):
        with self.connect() as db:
            return db.execute('''SELECT r.captured_utc,d.name,c.address,r.raw_u16,r.value,r.latency_ms
                FROM readings r JOIN channels c ON c.id=r.channel_id
                JOIN sessions s ON s.id=c.session_id JOIN devices d ON d.id=s.device_id
                ORDER BY r.id DESC LIMIT ?''', (limit,)).fetchall()

    def export(self, stream):
        import csv
        writer = csv.writer(stream)
        writer.writerow(['captured_utc','device','address_zero_based','raw_u16','value','latency_ms'])
        with self.connect() as db:
            for row in db.execute('''SELECT r.captured_utc,d.name,c.address,r.raw_u16,r.value,r.latency_ms
                FROM readings r JOIN channels c ON c.id=r.channel_id
                JOIN sessions s ON s.id=c.session_id JOIN devices d ON d.id=s.device_id ORDER BY r.id'''):
                # Device names can originate from user input; prevent spreadsheet formulas.
                row = list(row)
                if row[1].startswith(('=', '+', '-', '@', '\t', '\r', '\n')):
                    row[1] = "'" + row[1]
                writer.writerow(row)
