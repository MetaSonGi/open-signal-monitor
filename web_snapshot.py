"""Read-only browser projections; missing stores are reported independently."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime,timezone


def snapshot(collector,learning):
    result={'generated_utc':datetime.now(timezone.utc).isoformat(),'collector':{'available':False,'assets':[],'signals':[],'sample_count':0},'learning':{'available':False,'jobs':[],'events':[],'models':[]}}
    for name,path in [('collector',collector),('learning',learning)]:
        db=None
        try:
            db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=3);db.row_factory=sqlite3.Row
            db.execute('BEGIN')
            if name=='collector':
                result[name]={'available':True,'assets':[dict(r) for r in db.execute('SELECT id,code,name,kind,location FROM assets')],
                  'sample_count':db.execute('SELECT count(*) FROM telemetry').fetchone()[0],
                  'signals':[dict(r) for r in db.execute('''SELECT s.id,s.name,s.unit,a.code asset_code,so.name source_name,so.protocol,so.interval_s,
                    t.value,t.quality,t.source_utc,t.ingested_utc,
                    EXISTS(SELECT 1 FROM acquisition_runs ar WHERE ar.source_id=so.id AND ar.stopped_utc IS NULL) running
                    FROM signals s JOIN sources so ON so.id=s.source_id JOIN assets a ON a.id=so.asset_id
                    LEFT JOIN telemetry t ON t.id=(SELECT max(id) FROM telemetry WHERE signal_id=s.id) ORDER BY s.id''')]}
            else:
                jobs=[dict(r) for r in db.execute('''SELECT j.*,coalesce(sum(e.good),0) good,coalesce(sum(e.bad),0) bad FROM jobs j LEFT JOIN pop_events e ON e.job_id=j.id GROUP BY j.id ORDER BY j.id DESC LIMIT 100''')]
                models=[]
                for row in db.execute('SELECT * FROM models ORDER BY id DESC LIMIT 20'):
                    item=dict(row);item['parameters']=json.loads(item['parameters']);item['metrics']=json.loads(item['metrics']);models.append(item)
                result[name]={'available':True,'jobs':jobs,'events':[dict(r) for r in db.execute('SELECT * FROM pop_events ORDER BY id DESC LIMIT 50')],'models':models,
                              'sample_count':db.execute('SELECT count(*) FROM samples').fetchone()[0]}
        except (sqlite3.Error,OSError,ValueError):
            result[name]['error']='DB가 아직 없거나 읽을 수 없습니다.'
        finally:
            if db:db.close()
    return result
