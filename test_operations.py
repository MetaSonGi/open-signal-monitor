import csv
import io
import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from operations_db import OperationsDB,utc
from acquisition import Engine
from adapters import Modbus,SerialJSON,RobotJSON,OPCUA
from protocol import start_demo


class DataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.db=OperationsDB(self.root/'manufacturing.sqlite3')
        self.sid=self.db.add_source('ROBOT-A','Robot A','LINE-1','Robot sensors','demo',{},.2)
        self.db.add_signal(self.sid,'temperature','온도','C',2,1,low=0,high=100)
        self.source=self.db.sources()[0];self.signals=self.db.signals(self.sid)
        self.run=self.db.begin(self.source,self.signals);self.previous={}
    def tearDown(self):self.temp.cleanup()
    def record(self,value,**kwargs):
        return self.db.record(self.source,self.run,self.signals,{'temperature':dict(value=value,**kwargs)},1,self.previous)[0]

    def test_quality_and_calibration(self):
        self.assertEqual(self.record(10)['value'],21)
        self.assertEqual(self.record(100)['quality'],'out_of_range')
        self.assertEqual(self.record(None)['quality'],'missing')
        self.assertEqual(self.record(float('nan'))['quality'],'invalid')
        self.assertEqual(self.record('broken')['quality'],'invalid')
        self.assertEqual(self.record(10,quality='device_bad')['quality'],'device_bad')
        self.assertEqual(self.record(10,timestamp='nonsense')['quality'],'invalid_time')
        old=(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()
        self.assertEqual(self.record(10,timestamp=old)['quality'],'stale')

    def test_time_order_and_missing_recovery(self):
        t=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        self.record(None)
        self.assertEqual(self.record(10,timestamp=t)['quality'],'good')
        self.assertEqual(self.record(11,timestamp=t)['quality'],'out_of_order')

    def test_lot_labels_features_parquet(self):
        asset=self.source['asset_id']
        job=self.db.start_job(asset,'WO-A','PART-A','LOT-A','cut','running')
        for value in [10,20,None]:self.record(value)
        self.db.stop_job(asset)
        self.db.start_job(asset,'WO-B','PART-B','LOT-B','cut','running');self.record(30)
        start=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        end=(datetime.now(timezone.utc)+timedelta(minutes=1)).isoformat()
        self.db.label(asset,start,end,'defect','dimension')
        self.db.label(asset,start,end,'maintenance','inspection')
        path=self.root/'raw.csv';self.assertEqual(self.db.export(path),4)
        with path.open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual(rows[0]['lot'],'LOT-A');self.assertEqual(rows[-1]['lot'],'LOT-B')
        self.assertIn('defect',rows[0]['target_labels']);self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['label_conflict'],'1');self.assertIn('dimension',rows[0]['label_notes'])
        fp=self.root/'features.parquet';self.assertEqual(self.db.export(fp,features=True,window=86400,parquet=True),2)
        import duckdb
        with duckdb.connect() as db:
            features=db.execute('SELECT lot,sample_count,good_count,mean,invalid_fraction FROM read_parquet(?) ORDER BY lot',[str(fp)]).fetchall()
        self.assertEqual(features[0][:4],('LOT-A',3,2,31.0))
        self.assertAlmostEqual(features[0][4],1/3)
        self.assertTrue(fp.with_suffix('.parquet.manifest.json').exists())
        self.assertEqual(self.db.export_daily(self.root/'lake'),4)
        self.assertEqual(len(list((self.root/'lake').rglob('telemetry.parquet'))),1)

    def test_engine_concurrency_and_stop(self):
        second=self.db.add_source('ARD-A','Arduino','LINE-1','Arduino','demo',{},.2)
        self.db.add_signal(second,'vibration','振動','g')
        engine=Engine(self.db);engine.start(self.sid);engine.start(second)
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            if self.db.query('SELECT count(*) n FROM telemetry')[0]['n']>=4:break
            time.sleep(.03)
        engine.stop();deadline=time.monotonic()+5
        while engine.active() and time.monotonic()<deadline:time.sleep(.03)
        self.assertFalse(engine.active())
        self.assertGreaterEqual(self.db.query('SELECT count(*) n FROM telemetry')[0]['n'],4)
        # The manual setUp session remains open; engine-owned sessions must close.
        self.assertEqual(self.db.query('SELECT count(*) n FROM acquisition_runs WHERE id!=? AND stopped_utc IS NULL',(self.run,))[0]['n'],0)

    def test_failure_stored_as_missing(self):
        sid=self.db.add_source('OFF','Offline','LINE-1','Offline','robot_json',{'host':'127.0.0.1','port':1,'timeout':.2},.2)
        self.db.add_signal(sid,'temperature','Temperature')
        engine=Engine(self.db);engine.start(sid)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            if self.db.query('SELECT count(*) n FROM incidents')[0]['n']:break
            time.sleep(.03)
        engine.stop()
        deadline=time.monotonic()+3
        while engine.active() and time.monotonic()<deadline:time.sleep(.03)
        self.assertTrue(self.db.query("SELECT * FROM telemetry WHERE quality='missing' AND value IS NULL"))

    def test_validation_and_empty_parquet(self):
        with self.assertRaises(ValueError):self.db.add_signal(self.sid,'bad','bad',low=10,high=0)
        with self.assertRaises(ValueError):self.db.label(self.source['asset_id'],utc(),'2020-01-01T00:00:00Z','normal','')
        with self.assertRaises(ValueError):self.db.add_source('X','X','','X','opcua',{'password':'secret'})
        self.assertEqual(self.db.export(self.root/'empty.parquet',parquet=True),0)

    def test_historical_metadata_and_single_instance(self):
        self.record(10)
        with self.db.connect() as db:
            db.execute("UPDATE signals SET name='Renamed',unit='F',scale=9,key='changed'")
            db.execute("UPDATE sources SET protocol='robot_json'")
        path=self.root/'history.csv';self.db.export(path)
        with path.open(encoding='utf-8-sig') as stream:row=next(csv.DictReader(stream))
        self.assertEqual((row['signal'],row['unit'],row['signal_key'],row['protocol']),('온도','C','temperature','demo'))
        from instance_lock import InstanceLock
        lock=InstanceLock(self.root/'instance.lock')
        try:
            with self.assertRaises(RuntimeError):InstanceLock(self.root/'instance.lock')
        finally:lock.close()


class AdapterTests(unittest.TestCase):
    def test_modbus_adapter(self):
        server=start_demo(0)
        try:
            adapter=Modbus({'host':'127.0.0.1','port':server.server_address[1]})
            self.assertTrue(900<=adapter.read([{'key':'0'}])['0']['value']<=1100)
        finally:server.shutdown();server.server_close()

    def test_serial_json_with_real_pyserial_loop(self):
        adapter=SerialJSON({'port':'loop://','baud':115200,'timeout':1})
        try:
            adapter.connect();adapter.stream.write(b'{"values":{"temperature":23.5,"running":true}}\n')
            result=adapter.read([{'key':'temperature'},{'key':'running'},{'key':'missing'}])
            self.assertEqual(result['temperature']['value'],23.5)
            self.assertEqual(result['running']['value'],1)
            self.assertIsNone(result['missing']['value'])
        finally:adapter.close()

    def test_robot_json_fragmented_tcp(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
        port=listener.getsockname()[1]
        def send():
            with listener:
                conn,_=listener.accept()
                with conn:
                    conn.sendall(b'{"values":{"joint1":');time.sleep(.03);conn.sendall(b'12.5}}\n')
        thread=threading.Thread(target=send);thread.start()
        adapter=RobotJSON({'host':'127.0.0.1','port':port})
        try:self.assertEqual(adapter.read([{'key':'joint1'}])['joint1']['value'],12.5)
        finally:adapter.close();thread.join(2)

    def test_opcua_real_local_server(self):
        from asyncua.sync import Server
        from asyncua import ua
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        server=Server();server.set_endpoint(f'opc.tcp://127.0.0.1:{port}/test/')
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        ns=server.register_namespace('urn:opensignal:test')
        node=server.nodes.objects.add_variable(ns,'Temperature',23.5)
        server.start()
        adapter=OPCUA({'endpoint':f'opc.tcp://127.0.0.1:{port}/test/'})
        try:
            key=node.nodeid.to_string();result=adapter.read([{'key':key}])[key]
            self.assertEqual(result['value'],23.5);self.assertEqual(result['quality'],'good')
            self.assertIsNotNone(result['timestamp'])
        finally:adapter.close();server.stop()


if __name__=='__main__':unittest.main()
