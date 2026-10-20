import csv
import json
import math
import os
import sqlite3
import statistics
import uuid
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime,timezone
from urllib.request import urlopen


ROOT=Path(__file__).resolve().parent.parent
def now():return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

SCHEMA='''
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
'''


class LabDB:
    def __init__(self,path=None):
        self.path=Path(path or os.environ.get('OPENSIGNAL_LEARNING_DB',ROOT/'data'/'learning.sqlite3')).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:db.execute('PRAGMA journal_mode=WAL');db.executescript(SCHEMA)
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:yield db
        finally:db.close()
    def query(self,sql,args=()):
        with self.connect() as db:return [dict(r) for r in db.execute(sql,args)]
    def setting(self,key,value=None):
        with self.connect() as db:
            if value is not None:db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,value))
            row=db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
            return row[0] if row else ('http://127.0.0.1:8808' if key=='collector_url' else '')
    def equipment(self,code,name):
        if not code.strip() or not name.strip():raise ValueError('설비 코드와 이름을 입력하세요.')
        with self.connect() as db:db.execute('INSERT INTO equipment VALUES(?,?)',(code.strip(),name.strip()))
    def item(self,code,name):
        if not code.strip() or not name.strip():raise ValueError('품목 코드와 이름을 입력하세요.')
        with self.connect() as db:db.execute('INSERT INTO items VALUES(?,?)',(code.strip(),name.strip()))
    def job(self,code,item,asset,lot,target):
        if not code or not lot or not isinstance(target,int) or target<=0:raise ValueError('작업지시·LOT·양의 정수 목표 수량이 필요합니다.')
        with self.connect() as db:return db.execute('INSERT INTO jobs(code,item_code,asset_code,lot,target,created_utc) VALUES(?,?,?,?,?,?)',(code,item,asset,lot,target,now())).lastrowid
    def jobs(self):
        return self.query('''SELECT j.*,coalesce(sum(e.good),0) good,coalesce(sum(e.bad),0) bad
          FROM jobs j LEFT JOIN pop_events e ON e.job_id=j.id GROUP BY j.id ORDER BY j.id DESC''')
    def event(self,job,kind,operator,good=0,bad=0,reason='',event_key=None):
        if not operator.strip():raise ValueError('작업자를 입력하세요.')
        if kind not in {'start','pause','resume','complete','report'}:raise ValueError('허용하지 않는 작업입니다.')
        if type(good)!=int or type(bad)!=int or min(good,bad)<0:raise ValueError('수량은 0 이상의 정수입니다.')
        if kind=='report' and good+bad==0:raise ValueError('추가 생산 수량을 입력하세요.')
        if kind=='pause' and not reason.strip():raise ValueError('비가동 사유를 입력하세요.')
        key=event_key or str(uuid.uuid4());stamp=now()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior=db.execute('SELECT * FROM pop_events WHERE event_key=?',(key,)).fetchone()
            if prior:
                if (prior['job_id'],prior['kind'],prior['good'],prior['bad'],prior['operator'],prior['reason'])!=(job,kind,good,bad,operator,reason):raise ValueError('같은 이벤트 ID의 내용이 다릅니다.')
                return prior['id']
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not row:raise ValueError('작업지시가 없습니다.')
            allowed={'start':'planned','pause':'running','resume':'paused','complete':('running','paused'),'report':'running'}
            states=allowed[kind] if isinstance(allowed[kind],tuple) else (allowed[kind],)
            if row['status'] not in states:raise ValueError('현재 작업 상태에서 실행할 수 없습니다.')
            if kind=='start' and db.execute("SELECT 1 FROM jobs WHERE asset_code=? AND status IN ('running','paused')",(row['asset_code'],)).fetchone():
                raise ValueError('이 설비에 진행 중이거나 일시 정지된 작업이 있습니다. 먼저 완료하세요.')
            if kind=='report' and good and db.execute('SELECT 1 FROM bindings WHERE asset_code=? AND active=1 AND counter_signal IS NOT NULL',(row['asset_code'],)).fetchone():
                raise ValueError('양품 카운터 연결 중에는 양품 수량을 수동 중복 입력할 수 없습니다. 불량 수량만 입력하세요.')
            if kind!='report' and good+bad:raise ValueError('실적 입력은 실적 등록 버튼을 사용하세요.')
            status={'start':'running','pause':'paused','resume':'running','complete':'completed'}.get(kind)
            if status:
                db.execute('UPDATE jobs SET status=?,started_utc=coalesce(started_utc,?),ended_utc=? WHERE id=?',(status,stamp,stamp if kind=='complete' else None,job))
            return db.execute('INSERT INTO pop_events(event_key,job_id,at_utc,kind,good,bad,operator,reason,origin) VALUES(?,?,?,?,?,?,?,?,?)',(key,job,stamp,kind,good,bad,operator,reason,'manual')).lastrowid
    def inspect(self,job,label):
        if label not in {'normal','defect','unknown'}:raise ValueError('판정을 확인하세요.')
        with self.connect() as db:db.execute('UPDATE jobs SET result_label=? WHERE id=?',(label,job))
    def node(self,name,role,asset,x=80,y=80):
        if role not in {'collector','mes','pop','ai'} or not name:raise ValueError('블록 이름과 역할을 확인하세요.')
        with self.connect() as db:return db.execute('INSERT INTO nodes(name,role,asset_code,x,y) VALUES(?,?,?,?,?)',(name,role,asset,float(x),float(y))).lastrowid
    def move(self,node,x,y):
        if not all(math.isfinite(v) for v in [x,y]):raise ValueError('잘못된 좌표입니다.')
        with self.connect() as db:db.execute('UPDATE nodes SET x=?,y=? WHERE id=?',(max(10,min(1800,x)),max(10,min(1000,y)),node))
    def edge(self,source,target):
        with self.connect() as db:
            a=db.execute('SELECT role FROM nodes WHERE id=?',(source,)).fetchone();b=db.execute('SELECT role FROM nodes WHERE id=?',(target,)).fetchone()
            if not a or not b or (a[0],b[0]) not in {('collector','mes'),('collector','ai'),('mes','pop'),('mes','ai'),('pop','ai')}:raise ValueError('연결 방향: 수집→MES/AI, MES→POP/AI, POP→AI만 가능합니다.')
            db.execute('INSERT OR IGNORE INTO edges VALUES(?,?)',(source,target))
    def bind(self,collector,asset,counter=None):
        links=self.query('SELECT * FROM edges e JOIN nodes a ON a.id=e.source JOIN nodes b ON b.id=e.target WHERE a.role=\'collector\' AND b.role=\'mes\' AND a.asset_code=? AND b.asset_code=?',(collector,asset))
        if not links:raise ValueError('먼저 배치 화면에서 해당 수집 블록→MES 블록을 연결하세요.')
        with self.connect() as db:
            db.execute('UPDATE bindings SET active=0 WHERE collector_asset=?',(collector,))
            return db.execute('INSERT INTO bindings(collector_asset,asset_code,counter_signal,created_utc) VALUES(?,?,?,?)',(collector,asset,counter,now())).lastrowid
    def catalog(self):return self.fetch('/v1/catalog')
    def fetch(self,suffix):
        with urlopen(self.setting('collector_url').rstrip('/')+suffix,timeout=4) as response:
            data=response.read(4*1024*1024+1)
            if len(data)>4*1024*1024:raise ValueError('응답 크기 초과')
            return json.loads(data)
    def sync(self,pages=5):
        catalog=self.catalog();dataset=catalog['dataset_id'];count=skipped=0
        for _ in range(pages):
            row=self.query('SELECT last_id FROM cursors WHERE dataset=?',(dataset,));after=row[0]['last_id'] if row else 0
            response=self.fetch(f'/v1/samples?after_id={after}&limit=500')
            if response['dataset_id']!=dataset:raise ValueError('수집 DB가 변경됐습니다. 다시 연결하세요.')
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                for s in response['samples']:
                    binding=db.execute('SELECT * FROM bindings WHERE collector_asset=? AND active=1',(s['asset_code'],)).fetchone()
                    if not binding:skipped+=1;continue
                    changed=db.execute('INSERT OR IGNORE INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (dataset,s['id'],binding['id'],binding['asset_code'],s['signal_id'],s['signal_name'],s['unit'],s['source_utc'],s['ingested_utc'],s['value'],s['quality'])).rowcount
                    if changed:
                        count+=1
                        if binding['counter_signal']==s['signal_id']:self._counter(db,binding,dataset,s)
                db.execute('INSERT INTO cursors VALUES(?,?) ON CONFLICT(dataset) DO UPDATE SET last_id=max(last_id,excluded.last_id)',(dataset,response['next_id']))
            if len(response['samples'])<500:break
        return {'imported':count,'unmapped':skipped,'dataset':dataset}
    def _counter(self,db,binding,dataset,s):
        if s['quality']!='good' or not isinstance(s['value'],(int,float)) or not math.isfinite(s['value']) or s['value']<0 or int(s['value'])!=s['value']:return
        job=db.execute('SELECT * FROM jobs WHERE asset_code=? AND started_utc<=? AND (ended_utc IS NULL OR ended_utc>?) ORDER BY started_utc DESC LIMIT 1',(binding['asset_code'],s['source_utc'],s['source_utc'])).fetchone()
        if not job:return
        phase=db.execute("SELECT kind FROM pop_events WHERE job_id=? AND kind IN ('start','pause','resume','complete') AND at_utc<=? ORDER BY at_utc DESC,id DESC LIMIT 1",(job['id'],s['source_utc'])).fetchone()
        if not phase:return
        prior=db.execute('SELECT * FROM counter_state WHERE binding_id=? AND dataset=? AND job_id=?',(binding['id'],dataset,job['id'])).fetchone()
        value=int(s['value']);delta=0;kind='baseline'
        if prior:
            if s['source_utc']<=prior['last_time']:kind='out_of_order'
            elif value<prior['last_value']:kind='reset'
            elif phase[0] in {'start','resume'}:delta=value-prior['last_value'];kind='increment'
            else:kind='paused'
        # After a pause, first resumed reading becomes a fresh baseline.
        if prior and kind=='increment':
            pause=db.execute("SELECT 1 FROM pop_events WHERE job_id=? AND kind='pause' AND at_utc>? AND at_utc<=?",(job['id'],prior['last_time'],s['source_utc'])).fetchone()
            if pause or prior['last_phase'] not in {'start','resume'}:delta=0;kind='baseline_after_pause'
        db.execute('INSERT OR IGNORE INTO counter_events(binding_id,dataset,sample_id,job_id,kind,delta) VALUES(?,?,?,?,?,?)',(binding['id'],dataset,s['id'],job['id'],kind,delta))
        if kind!='out_of_order':db.execute('INSERT INTO counter_state VALUES(?,?,?,?,?,?) ON CONFLICT(binding_id,dataset,job_id) DO UPDATE SET last_value=excluded.last_value,last_time=excluded.last_time,last_phase=excluded.last_phase',(binding['id'],dataset,job['id'],value,s['source_utc'],phase[0]))
        if delta:
            db.execute("INSERT OR IGNORE INTO pop_events(event_key,job_id,at_utc,kind,good,bad,operator,reason,origin) VALUES(?,?,?,'report',?,0,'device','counter increment','counter')",
                (f"counter:{binding['id']}:{dataset}:{s['id']}",job['id'],s['source_utc'],delta))
    def training_rows(self):
        return self.query('''SELECT s.*,j.id job_id,j.code work_order,j.lot,j.item_code,j.result_label,j.started_utc job_start
          FROM samples s LEFT JOIN jobs j ON j.asset_code=s.asset_code AND j.started_utc<=s.source_utc
          AND (j.ended_utc IS NULL OR j.ended_utc>s.source_utc) ORDER BY s.source_utc,s.sample_id''')
    def export_training(self,path,dataset=None):
        rows=[r for r in self.training_rows() if dataset is None or r['dataset']==dataset]
        if not rows:raise ValueError('연결·동기화한 센서 데이터가 없습니다.')
        columns=list(rows[0])
        with open(path,'w',encoding='utf-8-sig',newline='') as file:
            writer=csv.writer(file);writer.writerow(columns)
            for row in rows:writer.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for v in row.values()])
        return len(rows)
    def learn(self,dataset,signal_id,asset=None,sigma_factor=3):
        if not isinstance(sigma_factor,(int,float)) or not math.isfinite(sigma_factor) or not .5<=sigma_factor<=6:raise ValueError('민감도 배수는 0.5~6σ입니다.')
        rows=[r for r in self.training_rows() if r['dataset']==dataset and r['signal_id']==signal_id and (asset is None or r['asset_code']==asset) and r['job_id'] is not None and r['quality']=='good' and r['value'] is not None]
        jobs=sorted({(r['job_start'],r['job_id']) for r in rows})
        if len(jobs)<2:raise ValueError('서로 다른 작업/LOT 2개 이상이 필요합니다. 앞 구간 작업을 normal로 판정하세요.')
        split=max(1,min(len(jobs)-1,int(len(jobs)*.7)));train_ids={j[1] for j in jobs[:split]}
        train=[r for r in rows if r['job_id'] in train_ids and r['result_label']=='normal']
        test=[r for r in rows if r['job_id'] not in train_ids]
        if len(train)<2:raise ValueError('학습 구간의 normal 작업에 유효한 센서 표본이 2개 이상 필요합니다.')
        units={r['unit'] for r in train+test}
        if len(units)!=1:raise ValueError('단위가 다른 데이터는 한 모델에서 학습할 수 없습니다.')
        mean=statistics.mean(r['value'] for r in train);std=statistics.pstdev(r['value'] for r in train)
        threshold=max(sigma_factor*std,abs(mean)*.001,1e-6)
        actual_train_ids={r['job_id'] for r in train}
        metrics={'train_samples':len(train),'test_samples':len(test),'train_jobs':sorted(actual_train_ids),'excluded_train_jobs':sorted(train_ids-actual_train_ids),'test_jobs':[j[1] for j in jobs[split:]],'tp':0,'tn':0,'fp':0,'fn':0,'unlabeled':0}
        for r in test:
            predicted=abs(r['value']-mean)>threshold
            if r['result_label'] not in {'normal','defect'}:metrics['unlabeled']+=1;continue
            actual=r['result_label']=='defect';metrics['tp' if actual and predicted else 'fn' if actual else 'fp' if predicted else 'tn']+=1
        params={'dataset':dataset,'signal_id':signal_id,'asset_code':asset,'sigma_factor':sigma_factor,'mean':mean,'std':std,'threshold':threshold,'unit':next(iter(units)),'method':'normal baseline ± max(kσ, 0.1% of mean, 1e-6)','split':'chronological by job; labels excluded from input'}
        with self.connect() as db:db.execute('INSERT INTO models(created_utc,feature,parameters,metrics) VALUES(?,?,?,?)',(now(),f'{dataset}:{signal_id}',json.dumps(params),json.dumps(metrics)))
        return {'parameters':params,'metrics':metrics}

    def disconnect(self,source,target):
        with self.connect() as db:
            pair=db.execute('SELECT a.role ar,a.asset_code aa,b.role br,b.asset_code ba FROM nodes a JOIN nodes b ON b.id=? WHERE a.id=?',(target,source)).fetchone()
            db.execute('DELETE FROM edges WHERE source=? AND target=?',(source,target))
            if pair and pair['ar']=='collector' and pair['br']=='mes':
                remaining=db.execute("SELECT 1 FROM edges e JOIN nodes a ON a.id=e.source JOIN nodes b ON b.id=e.target WHERE a.role='collector' AND b.role='mes' AND a.asset_code=? AND b.asset_code=?",(pair['aa'],pair['ba'])).fetchone()
                if not remaining:db.execute('UPDATE bindings SET active=0 WHERE collector_asset=? AND asset_code=?',(pair['aa'],pair['ba']))

    def save_layout(self,path):
        payload={name:self.query('SELECT * FROM '+name) for name in ['equipment','items','nodes','edges']}
        payload['bindings']=self.query('SELECT collector_asset,asset_code,counter_signal FROM bindings WHERE active=1')
        payload['format']='opensignal-learning-layout-v1'
        Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')

    def load_layout(self,path):
        payload=json.loads(Path(path).read_text(encoding='utf-8'))
        if payload.get('format')!='opensignal-learning-layout-v1':raise ValueError('지원하는 실습 배치 파일이 아닙니다.')
        if any(len(payload.get(k,[]))>1000 for k in ['equipment','items','nodes','edges','bindings']):raise ValueError('실습 항목 수가 너무 많습니다.')
        # Validate the whole plan before mutating any state.
        nodes={n['id']:n for n in payload['nodes']}
        allowed={('collector','mes'),('collector','ai'),('mes','pop'),('mes','ai'),('pop','ai')}
        for n in nodes.values():
            if n['role'] not in {'collector','mes','pop','ai'} or not math.isfinite(n['x']) or not math.isfinite(n['y']) or not 10<=n['x']<=1800 or not 10<=n['y']<=1000:raise ValueError('배치 블록 설정을 확인하세요.')
        for e in payload['edges']:
            if (nodes[e['source']]['role'],nodes[e['target']]['role']) not in allowed:raise ValueError('허용하지 않는 연결입니다.')
        with self.connect() as db:
            for a in payload['equipment']:db.execute('INSERT OR IGNORE INTO equipment VALUES(?,?)',(a['code'],a['name']))
            for item in payload['items']:db.execute('INSERT OR IGNORE INTO items VALUES(?,?)',(item['code'],item['name']))
            ids={}
            for n in nodes.values():ids[n['id']]=db.execute('INSERT INTO nodes(name,role,asset_code,x,y) VALUES(?,?,?,?,?)',(n['name'],n['role'],n['asset_code'],n['x'],n['y'])).lastrowid
            for e in payload['edges']:db.execute('INSERT INTO edges VALUES(?,?)',(ids[e['source']],ids[e['target']]))
            for b in payload['bindings']:
                valid=any(nodes[e['source']]['role']=='collector' and nodes[e['target']]['role']=='mes' and nodes[e['source']]['asset_code']==b['collector_asset'] and nodes[e['target']]['asset_code']==b['asset_code'] for e in payload['edges'])
                if not valid:raise ValueError('실제 블록 연결이 없는 장치 매핑입니다.')
                db.execute('UPDATE bindings SET active=0 WHERE collector_asset=?',(b['collector_asset'],))
                db.execute('INSERT INTO bindings(collector_asset,asset_code,counter_signal,created_utc) VALUES(?,?,?,?)',(b['collector_asset'],b['asset_code'],b.get('counter_signal'),now()))

    def seed_lesson(self):
        from datetime import timedelta
        with self.connect() as db:
            if db.execute("SELECT 1 FROM samples WHERE dataset='synthetic-learning'").fetchone():return
            db.execute("INSERT OR IGNORE INTO equipment VALUES('EDU-CELL','교육용 가상 셀')")
            db.execute("INSERT OR IGNORE INTO items VALUES('EDU-PART','교육용 부품')")
            binding=db.execute("INSERT INTO bindings(collector_asset,asset_code,active,created_utc) VALUES('SYNTHETIC','EDU-CELL',0,?)",(now(),)).lastrowid
            base=datetime.now(timezone.utc)-timedelta(hours=2)
            for j in range(5):
                start=base+timedelta(minutes=j*10);end=start+timedelta(minutes=5)
                job=db.execute("INSERT INTO jobs(code,item_code,asset_code,lot,target,status,started_utc,ended_utc,result_label,created_utc) VALUES(?,'EDU-PART','EDU-CELL',?,30,'completed',?,?,?,?)",
                    (f'EDU-WO-{j+1}',f'EDU-LOT-{j+1}',start.isoformat(timespec='milliseconds'),end.isoformat(timespec='milliseconds'),'defect' if j==4 else 'normal',now())).lastrowid
                db.execute("INSERT INTO pop_events(event_key,job_id,at_utc,kind,good,bad,operator,reason,origin) VALUES(?,?,?,'report',?,?,'학습 예제','가상 데이터','synthetic')",(f'lesson-job-{job}',job,end.isoformat(timespec='milliseconds'),0 if j==4 else 30,30 if j==4 else 0))
                for i in range(30):
                    stamp=(start+timedelta(seconds=i*5)).isoformat(timespec='milliseconds')
                    value=(30 if j==4 else 20)+.2*math.sin(i)
                    db.execute("INSERT INTO samples VALUES('synthetic-learning',? ,?,'EDU-CELL',1,'온도','C',?,?,?,'good')",(j*30+i+1,binding,stamp,stamp,value))
