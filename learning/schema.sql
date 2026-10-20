-- Separate MES/POP learning database

CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equipment(code TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS items(code TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY,code TEXT UNIQUE NOT NULL,item_code TEXT NOT NULL REFERENCES items(code),
 asset_code TEXT NOT NULL REFERENCES equipment(code),lot TEXT NOT NULL,target INTEGER NOT NULL CHECK(target>0),
 status TEXT NOT NULL DEFAULT 'planned',started_utc TEXT,ended_utc TEXT,result_label TEXT,
 created_utc TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_job ON jobs(asset_code) WHERE status IN ('running','paused');
CREATE TABLE IF NOT EXISTS pop_events(
 id INTEGER PRIMARY KEY,event_key TEXT NOT NULL UNIQUE,job_id INTEGER NOT NULL REFERENCES jobs(id),
 at_utc TEXT NOT NULL,kind TEXT NOT NULL,good INTEGER NOT NULL DEFAULT 0 CHECK(good>=0),
 bad INTEGER NOT NULL DEFAULT 0 CHECK(bad>=0),operator TEXT NOT NULL,reason TEXT NOT NULL,origin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS nodes(id INTEGER PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,asset_code TEXT NOT NULL,x REAL NOT NULL,y REAL NOT NULL);
CREATE TABLE IF NOT EXISTS edges(source INTEGER REFERENCES nodes(id),target INTEGER REFERENCES nodes(id),PRIMARY KEY(source,target));
CREATE TABLE IF NOT EXISTS bindings(id INTEGER PRIMARY KEY,collector_asset TEXT NOT NULL,asset_code TEXT NOT NULL REFERENCES equipment(code),counter_signal INTEGER,active INTEGER NOT NULL DEFAULT 1,created_utc TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_binding ON bindings(collector_asset) WHERE active=1;
CREATE TABLE IF NOT EXISTS cursors(dataset TEXT PRIMARY KEY,last_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS samples(
 dataset TEXT NOT NULL,sample_id INTEGER NOT NULL,binding_id INTEGER NOT NULL REFERENCES bindings(id),
 asset_code TEXT NOT NULL REFERENCES equipment(code),signal_id INTEGER NOT NULL,signal_name TEXT NOT NULL,unit TEXT NOT NULL,
 source_utc TEXT NOT NULL,ingested_utc TEXT NOT NULL,value REAL,quality TEXT NOT NULL,PRIMARY KEY(dataset,sample_id));
CREATE INDEX IF NOT EXISTS samples_time ON samples(asset_code,source_utc);
CREATE TABLE IF NOT EXISTS counter_state(binding_id INTEGER,dataset TEXT,job_id INTEGER,last_value INTEGER,last_time TEXT,last_phase TEXT,PRIMARY KEY(binding_id,dataset,job_id));
CREATE TABLE IF NOT EXISTS counter_events(id INTEGER PRIMARY KEY,binding_id INTEGER,dataset TEXT,sample_id INTEGER,job_id INTEGER,kind TEXT,delta INTEGER,UNIQUE(binding_id,dataset,sample_id));
CREATE TABLE IF NOT EXISTS models(id INTEGER PRIMARY KEY,created_utc TEXT NOT NULL,feature TEXT NOT NULL,parameters TEXT NOT NULL,metrics TEXT NOT NULL);
