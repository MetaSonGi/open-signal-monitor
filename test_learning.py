import json
import tempfile
import time
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from collector_api import start_api
from operations_db import OperationsDB
from learning.core import LabDB,now


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.db=LabDB(self.root/'lab.sqlite3')
        self.db.equipment('CELL','Learning cell');self.db.item('PART','Part')
    def tearDown(self):self.temp.cleanup()
    def job(self,code='WO-1'):
        return self.db.job(code,'PART','CELL','LOT-'+code,100)
    def mapping(self,counter=None):
        a=self.db.node('Collector','collector','SOURCE');b=self.db.node('MES','mes','CELL');self.db.edge(a,b)
        return self.db.bind('SOURCE','CELL',counter),a,b

    def test_pop_state_machine_dedup_and_pauses(self):
        job=self.job()
        with self.assertRaises(ValueError):self.db.event(job,'report','operator',3)
        self.db.event(job,'start','operator',event_key='start-1')
        self.db.event(job,'report','operator',3,1,event_key='report-1')
        self.db.event(job,'report','operator',3,1,event_key='report-1')
        self.assertEqual((self.db.jobs()[0]['good'],self.db.jobs()[0]['bad']),(3,1))
        with self.assertRaises(ValueError):self.db.event(job,'report','operator',4,1,event_key='report-1')
        self.db.event(job,'pause','operator',reason='material shortage')
        with self.assertRaises(ValueError):self.db.event(job,'report','operator',1)
        second=self.job('WO-2')
        with self.assertRaises(Exception):self.db.event(second,'start','operator')
        self.db.event(job,'resume','operator');self.db.event(job,'complete','operator')
        self.db.event(second,'start','operator')
        with self.assertRaises(ValueError):self.db.event(job,'start','operator')

    def test_layout_rules_persistence_disconnect_and_import(self):
        binding,a,b=self.mapping()
        self.db.move(a,450,220)
        with self.assertRaises(ValueError):self.db.edge(b,a)
        saved=self.root/'layout.json';self.db.save_layout(saved)
        other=LabDB(self.root/'other.sqlite3');other.load_layout(saved)
        self.assertEqual(len(other.query('SELECT * FROM edges')),1)
        self.assertEqual(other.query("SELECT x FROM nodes WHERE role='collector'")[0]['x'],450)
        self.db.disconnect(a,b)
        self.assertEqual(self.db.query('SELECT active FROM bindings WHERE id=?',(binding,))[0]['active'],0)
        with self.assertRaises(ValueError):self.db.bind('SOURCE','CELL')

    def test_read_only_collector_api_and_idempotent_sync(self):
        collector=OperationsDB(self.root/'collector.sqlite3')
        source=collector.add_source('SOURCE','Source','Lab','Source','demo',{})
        collector.add_signal(source,'temp','Temperature','C')
        src=collector.sources()[0];signals=collector.signals(source);run=collector.begin(src,signals)
        self.mapping()
        job=self.job();self.db.event(job,'start','operator');time.sleep(.005)
        collector.record(src,run,signals,{'temp':{'value':23,'quality':'good'}},1,{})
        server=start_api(collector.path,0)
        try:
            self.db.setting('collector_url',f'http://127.0.0.1:{server.server_address[1]}')
            self.assertEqual(self.db.sync()['imported'],1)
            self.assertEqual(self.db.sync()['imported'],0)
            self.assertEqual(self.db.training_rows()[0]['job_id'],job)
            self.assertIsNone(collector.query('SELECT stopped_utc FROM acquisition_runs')[0]['stopped_utc'])
            try:urlopen(self.db.setting('collector_url')+'/v1/samples?limit=50000');self.fail('Expected HTTP 400')
            except HTTPError as error:self.assertEqual(error.code,400);error.close()
            self.assertNotIn('config_json',json.dumps(self.db.catalog()))
        finally:server.shutdown();server.server_close()

    def test_counter_baseline_reset_replay_and_manual_conflict(self):
        binding,_,_=self.mapping(7);job=self.job();self.db.event(job,'start','operator')
        start=datetime.now(timezone.utc)+timedelta(seconds=1)
        def sample(i,value):
            return {'id':i,'signal_id':7,'source_utc':(start+timedelta(seconds=i)).isoformat(timespec='milliseconds'),'quality':'good','value':value}
        b=self.db.query('SELECT * FROM bindings WHERE id=?',(binding,))[0]
        with self.db.connect() as db:
            self.db._counter(db,b,'dataset',sample(1,100))
            self.db._counter(db,b,'dataset',sample(2,103))
            self.db._counter(db,b,'dataset',sample(2,103))
            self.db._counter(db,b,'dataset',sample(3,1))
            self.db._counter(db,b,'dataset',sample(4,3))
        self.assertEqual(self.db.jobs()[0]['good'],5)
        self.assertEqual(self.db.query("SELECT count(*) n FROM counter_events WHERE kind='reset'")[0]['n'],1)
        with self.assertRaises(ValueError):self.db.event(job,'report','operator',1)
        self.db.event(job,'report','operator',0,1)
        self.assertEqual(self.db.jobs()[0]['bad'],1)

    def test_baseline_learning_held_out_jobs_and_export(self):
        self.db.seed_lesson();self.db.seed_lesson()
        self.assertEqual(len(self.db.query('SELECT * FROM samples')),150)
        result=self.db.learn('synthetic-learning',1,'EDU-CELL')
        metrics=result['metrics']
        self.assertFalse(set(metrics['train_jobs']) & set(metrics['test_jobs']))
        self.assertEqual(metrics['train_samples'],90);self.assertEqual(metrics['tp'],30);self.assertEqual(metrics['tn'],30)
        self.assertEqual(metrics['fp']+metrics['fn'],0)
        self.assertEqual(self.db.export_training(self.root/'learning.csv'),150)

    def test_counter_pause_rebaseline(self):
        binding,_,_=self.mapping(7);job=self.job();self.db.event(job,'start','operator')
        base=datetime.now(timezone.utc)
        stamp=lambda sec:(base+timedelta(seconds=sec)).isoformat(timespec='milliseconds')
        with self.db.connect() as db:
            db.execute("INSERT INTO pop_events(event_key,job_id,at_utc,kind,operator,reason,origin) VALUES('pause',?,?,'pause','operator','test','manual')",(job,stamp(2)))
            db.execute("INSERT INTO pop_events(event_key,job_id,at_utc,kind,operator,reason,origin) VALUES('resume',?,?,'resume','operator','','manual')",(job,stamp(4)))
            b=db.execute('SELECT * FROM bindings WHERE id=?',(binding,)).fetchone()
            for i,sec,value in [(1,1,100),(2,3,105),(3,5,110),(4,6,112)]:
                self.db._counter(db,b,'dataset',{'id':i,'signal_id':7,'source_utc':stamp(sec),'quality':'good','value':value})
        self.assertEqual(self.db.jobs()[0]['good'],2)

    def test_end_to_end_collector_mes_pop_and_learning(self):
        collector=OperationsDB(self.root/'collector.sqlite3')
        sid=collector.add_source('SOURCE','Source','Lab','Source','demo',{})
        collector.add_signal(sid,'temperature','Temperature','C')
        src=collector.sources()[0];signals=collector.signals(sid);run=collector.begin(src,signals)
        self.mapping();server=start_api(collector.path,0)
        try:
            self.db.setting('collector_url',f'http://127.0.0.1:{server.server_address[1]}')
            for j in range(3):
                job=self.job('E2E-'+str(j));self.db.event(job,'start','student');time.sleep(.005)
                for i in range(3):
                    collector.record(src,run,signals,{'temperature':{'value':20+.1*i if j<2 else 30+i,'quality':'good'}},1,{})
                    time.sleep(.005)
                self.db.event(job,'report','student',3 if j<2 else 0,0 if j<2 else 3)
                self.db.event(job,'complete','student');self.db.inspect(job,'normal' if j<2 else 'defect')
            self.assertEqual(self.db.sync()['imported'],9)
            rows=self.db.training_rows();self.assertTrue(all(r['job_id'] is not None for r in rows))
            result=self.db.learn(self.db.catalog()['dataset_id'],signals[0]['id'],'CELL')
            self.assertEqual(result['metrics']['train_samples'],6);self.assertEqual(result['metrics']['tp'],3)
            self.assertEqual(self.db.sync()['imported'],0)
        finally:server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
