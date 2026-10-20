"""Manufacturing metadata, acquisition lineage and quality-aware telemetry."""
import csv
import json
import math
import sqlite3
import tempfile
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('시각에는 시간대가 필요합니다.')
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds')


SCHEMA = '''
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
'''


class OperationsDB:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            # A previous process may have been terminated without closing sessions.
            db.execute("UPDATE acquisition_runs SET stopped_utc=?,stop_reason='interrupted' WHERE stopped_utc IS NULL",(utc(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def query(self, sql, params=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql,params)]

    def add_source(self, asset_code, asset_name, location, name, protocol, config, interval=1,kind='equipment'):
        if protocol not in {'demo','modbus_tcp','opcua','serial_json','robot_json'}:
            raise ValueError('지원하지 않는 연결 방식입니다.')
        if not asset_code.strip() or not name.strip() or not math.isfinite(interval) or not .2<=interval<=3600:
            raise ValueError('설비 코드·연결 이름과 수집 간격(0.2~3600초)을 확인하세요.')
        # Credentials must be supplied through environment variables, never DB/UI config.
        if any(k.lower() in {'password','token','secret'} for k in config):
            raise ValueError('비밀번호 값 대신 password_env 환경변수 이름을 사용하세요.')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO assets(code,name,location,kind) VALUES(?,?,?,?)',(asset_code,asset_name,location,kind))
            asset=db.execute('SELECT id FROM assets WHERE code=?',(asset_code,)).fetchone()[0]
            return db.execute('INSERT INTO sources(asset_id,name,protocol,config_json,interval_s) VALUES(?,?,?,?,?)',
                (asset,name,protocol,json.dumps(config,ensure_ascii=False),interval)).lastrowid

    def add_signal(self, source, key, name, unit='', scale=1, offset=0, low=None, high=None, stale=30):
        nums=[scale,offset,stale]+[v for v in [low,high] if v is not None]
        if not key or not name or not all(math.isfinite(v) for v in nums) or stale<=0 or (low is not None and high is not None and low>high):
            raise ValueError('센서 이름·주소·배율·허용 범위를 확인하세요.')
        with self.connect() as db:
            return db.execute('INSERT INTO signals(source_id,key,name,unit,scale,offset,low_limit,high_limit,stale_s) VALUES(?,?,?,?,?,?,?,?,?)',
                (source,str(key),name,unit,scale,offset,low,high,stale)).lastrowid

    def sources(self):
        return self.query('SELECT s.*,a.code asset_code,a.name asset_name,a.location,a.kind asset_kind FROM sources s JOIN assets a ON a.id=s.asset_id ORDER BY s.id')

    def signals(self, source):
        return self.query('SELECT * FROM signals WHERE source_id=? ORDER BY id',(source,))

    def begin(self, source, signals):
        snapshot=json.dumps({'source':source,'signals':signals},ensure_ascii=False)
        with self.connect() as db:
            return db.execute('INSERT INTO acquisition_runs(source_id,started_utc,config_snapshot) VALUES(?,?,?)',(source['id'],utc(),snapshot)).lastrowid

    def finish(self, run):
        with self.connect() as db:
            db.execute("UPDATE acquisition_runs SET stopped_utc=?,stop_reason='stopped' WHERE id=?",(utc(),run))

    def incident(self, source, message):
        with self.connect() as db:
            db.execute('INSERT INTO incidents(source_id,occurred_utc,message) VALUES(?,?,?)',(source,utc(),str(message)[:1000]))

    def record(self, source, run, signals, packet, latency, previous):
        ingested=utc(); output=[]
        with self.connect() as db:
            for sig in signals:
                item=packet.get(sig['key'],{})
                raw=item.get('value'); quality=item.get('quality','good'); detail=item.get('detail','')
                if not isinstance(quality,str) or quality not in {'good','missing','invalid','invalid_time','stale','out_of_order','out_of_range','device_bad'}:
                    quality='device_bad';detail='알 수 없는 장치 품질 코드'
                detail=str(detail)[:1000]
                try:
                    when=timestamp(item.get('timestamp') or ingested)
                except (ValueError,TypeError):
                    when=ingested;quality='invalid_time';detail='장치 시각 형식 오류'
                value=None
                if raw is None:
                    quality='missing' if quality=='good' else quality
                elif not isinstance(raw,(int,float)) or isinstance(raw,bool):
                    quality='invalid';detail='유한한 숫자가 아님'
                else:
                    try:
                        value=raw*sig['scale']+sig['offset']
                        if not math.isfinite(value) or abs(value)>1e150:
                            value=None;quality='invalid';detail='변환값이 유효한 수치 범위를 벗어남'
                    except OverflowError:
                        value=None;quality='invalid';detail='변환값 오버플로'
                    if quality=='good' and value is not None:
                        if (sig['low_limit'] is not None and value<sig['low_limit']) or (sig['high_limit'] is not None and value>sig['high_limit']):
                            quality='out_of_range'
                        elif (datetime.fromisoformat(ingested)-datetime.fromisoformat(when)).total_seconds()>sig['stale_s']:
                            quality='stale'
                        elif (datetime.fromisoformat(when)-datetime.fromisoformat(ingested)).total_seconds()>5:
                            quality='invalid_time';detail='장치 시각이 수집 시각보다 미래임'
                        elif sig['id'] in previous and when<=previous[sig['id']]:
                            quality='out_of_order'
                if value is not None and quality not in {'invalid_time','missing','invalid'}:
                    previous[sig['id']]=max(when,previous.get(sig['id'],when))
                job=db.execute('SELECT id FROM production_runs WHERE asset_id=? AND started_utc<=? AND (ended_utc IS NULL OR ended_utc>?) ORDER BY started_utc DESC LIMIT 1',
                    (source['asset_id'],when,when)).fetchone()
                try:raw_text=json.dumps(raw,ensure_ascii=False,default=str,allow_nan=False)
                except ValueError:raw_text=json.dumps({'invalid_value':str(raw)},ensure_ascii=False)
                db.execute('INSERT INTO telemetry(signal_id,run_id,production_id,source_utc,ingested_utc,raw_json,value,quality,detail,latency_ms,unit,scale,offset,signal_key,signal_name) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (sig['id'],run,job[0] if job else None,when,ingested,raw_text,value,quality,detail,latency,sig['unit'],sig['scale'],sig['offset'],sig['key'],sig['name']))
                output.append(dict(signal_id=sig['id'],source_id=source['id'],signal=sig['name'],source=source['name'],value=value,unit=sig['unit'],quality=quality,time=when))
        return output

    def start_job(self, asset, work_order, product, lot, process, state):
        if not all(str(v).strip() for v in [work_order,product,lot,process,state]):
            raise ValueError('작업지시·제품·LOT·공정·상태를 입력하세요.')
        with self.connect() as db:
            return db.execute('INSERT INTO production_runs(asset_id,work_order,product,lot,process,operating_state,started_utc) VALUES(?,?,?,?,?,?,?)',
                (asset,work_order,product,lot,process,state,utc())).lastrowid

    def stop_job(self, asset):
        with self.connect() as db:
            db.execute('UPDATE production_runs SET ended_utc=? WHERE asset_id=? AND ended_utc IS NULL',(utc(),asset))

    def label(self, asset, start, end, category, note):
        start,end=timestamp(start),timestamp(end)
        if end<start or category not in {'normal','defect','failure','maintenance'}:
            raise ValueError('판정 구간 또는 종류를 확인하세요.')
        with self.connect() as db:
            return db.execute('INSERT INTO labels(asset_id,started_utc,ended_utc,category,note,created_utc) VALUES(?,?,?,?,?,?)',
                (asset,start,end,category,note,utc())).lastrowid

    def export(self, path, start=None, end=None, features=False, window=60, parquet=False,source_id=None):
        if not isinstance(window,int) or not 1<=window<=86400:
            raise ValueError('집계 구간은 1~86400초입니다.')
        start=timestamp(start) if start else '0001-01-01T00:00:00.000+00:00'
        end=timestamp(end) if end else '9999-12-31T23:59:59.999+00:00'
        if end<start:raise ValueError('내보내기 종료 시각이 시작보다 빠릅니다.')
        base='''SELECT t.*,t.signal_name signal,so.id source_id,json_extract(ar.config_snapshot,'$.source.protocol') protocol,a.code asset,
          p.work_order,p.product,p.lot,p.process,p.operating_state,
          (SELECT group_concat(category, '|') FROM labels l WHERE l.asset_id=a.id AND l.started_utc<=t.source_utc AND l.ended_utc>=t.source_utc) target_labels,
          (SELECT group_concat(id, '|') FROM labels l WHERE l.asset_id=a.id AND l.started_utc<=t.source_utc AND l.ended_utc>=t.source_utc) label_ids,
          (SELECT group_concat(note, ' | ') FROM labels l WHERE l.asset_id=a.id AND l.started_utc<=t.source_utc AND l.ended_utc>=t.source_utc) label_notes
          FROM telemetry t JOIN signals s ON s.id=t.signal_id JOIN sources so ON so.id=s.source_id JOIN acquisition_runs ar ON ar.id=t.run_id
          JOIN assets a ON a.id=so.asset_id LEFT JOIN production_runs p ON p.id=t.production_id
          WHERE t.source_utc>=? AND t.source_utc<=?'''
        base_params=(start,end)
        if source_id is not None:
            base+=' AND so.id=?';base_params+=(int(source_id),)
        if features:
            # Separate production contexts, never mix different LOTs in a feature window.
            sql='''WITH dataset AS ('''+base+''') SELECT asset,source_id,signal_id,signal,unit,
              CAST(strftime('%s',source_utc) AS INTEGER)/?*? window_epoch,
              run_id,production_id,work_order,product,lot,process,operating_state,
              count(*) sample_count,sum(quality='good') good_count,
              avg(CASE WHEN quality='good' THEN value END) mean,
              min(CASE WHEN quality='good' THEN value END) minimum,
              max(CASE WHEN quality='good' THEN value END) maximum,
              avg(CASE WHEN quality='good' THEN value*value END) mean_square,
              1.0-sum(quality='good')*1.0/count(*) invalid_fraction,
              group_concat(DISTINCT target_labels) target_labels,
              group_concat(DISTINCT label_ids) label_ids,group_concat(DISTINCT label_notes) label_notes
              FROM dataset GROUP BY asset,source_id,signal_id,unit,window_epoch,run_id,production_id ORDER BY window_epoch,signal_id'''
            params=base_params+(window,window)
        else:
            sql='''WITH dataset AS ('''+base+''') SELECT id,asset,source_id,protocol,signal_id,signal,signal_key,run_id,unit,source_utc,ingested_utc,
               raw_json,value,quality,detail,latency_ms,scale,offset,production_id,work_order,product,lot,process,operating_state,target_labels,label_ids,label_notes
               FROM dataset ORDER BY source_utc,id'''
            params=base_params
        target=Path(path);temp=None;count=0
        if parquet:
            import duckdb
            temp=tempfile.NamedTemporaryFile(suffix='.csv',delete=False)
            temp.close();csv_path=Path(temp.name)
        else:csv_path=target
        try:
            with self.connect() as db, csv_path.open('w',encoding='utf-8-sig',newline='') as stream:
                cursor=db.execute(sql,params)
                columns=[c[0] for c in cursor.description]
                if features:columns+=['stddev','rms']
                columns+=['label_conflict']
                writer=csv.writer(stream);writer.writerow(columns)
                for row in cursor:
                    values=list(row)
                    if features:
                        mean,ms=row['mean'],row['mean_square']
                        values += [math.sqrt(max(0,ms-mean*mean)) if mean is not None else None,math.sqrt(max(0,ms)) if ms is not None else None]
                    import re
                    values += [int(len(set(filter(None,re.split('[|,]',row['target_labels'] or ''))))>1)]
                    # Parquet remains typed/raw. CSV text is made spreadsheet safe.
                    writer.writerow([("'"+v if not parquet and columns[i]!='raw_json' and isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for i,v in enumerate(values)])
                    count+=1
            if parquet:
                numeric={'id','source_id','signal_id','run_id','production_id','window_epoch','sample_count','good_count','label_conflict'}
                real={'value','latency_ms','scale','offset','mean','minimum','maximum','mean_square','invalid_fraction','stddev','rms'}
                projection=','.join(f'TRY_CAST("{c}" AS {"BIGINT" if c in numeric else "DOUBLE"}) AS "{c}"' if c in numeric|real else f'"{c}"' for c in columns)
                with duckdb.connect() as db:
                    db.read_csv(str(csv_path),header=True,all_varchar=True).project(projection).write_parquet(str(target),compression='zstd')
            manifest={'exported_utc':utc(),'rows':count,'start':start,'end':end,'source_id':source_id,'features':features,'window_seconds':window if features else None,
                      'label_policy':'explicit labels only; unlabeled is not normal; overlapping labels retained',
                      'quality_policy':'feature statistics use good samples only; all qualities remain in raw export',
                      'split_guidance':'split by time and LOT; exclude target_labels from model input features'}
            target.with_suffix(target.suffix+'.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
            return count
        finally:
            if temp:csv_path.unlink(missing_ok=True)

    def export_daily(self,directory,start=None,end=None,features=False,window=60):
        # Snapshot the day/source list first; never delete live SQLite records.
        start=timestamp(start) if start else '0001-01-01T00:00:00.000+00:00'
        end=timestamp(end) if end else '9999-12-31T23:59:59.999+00:00'
        parts=self.query('SELECT DISTINCT substr(t.source_utc,1,10) day,s.source_id FROM telemetry t JOIN signals s ON s.id=t.signal_id WHERE t.source_utc>=? AND t.source_utc<=? ORDER BY day,source_id',(start,end))
        rows=0
        for part in parts:
            folder=Path(directory)/f"source_id={part['source_id']}"/f"date={part['day']}"
            folder.mkdir(parents=True,exist_ok=True)
            rows+=self.export(folder/('features.parquet' if features else 'telemetry.parquet'),
                max(start,part['day']+'T00:00:00.000+00:00'),min(end,part['day']+'T23:59:59.999+00:00'),features,window,True,part['source_id'])
        return rows
