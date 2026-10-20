import tempfile,threading,unittest,json
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from collector_api import CollectorAPI
from operations_db import OperationsDB
from learning.core import LabDB
from web_snapshot import snapshot
class WebTests(unittest.TestCase):
 def test_missing_stores_never_created(self):
  with tempfile.TemporaryDirectory() as root:
   a=Path(root)/'a.db';b=Path(root)/'b.db';result=snapshot(a,b)
   self.assertFalse(result['collector']['available']);self.assertFalse(result['learning']['available']);self.assertFalse(a.exists());self.assertFalse(b.exists())
 def test_readonly_projection_history_and_static(self):
  with tempfile.TemporaryDirectory() as root:
   root=Path(root);c=OperationsDB(root/'c.db');l=LabDB(root/'l.db')
   source=c.add_source('CELL','Cell','Lab','Demo','demo',{});c.add_signal(source,'temp','Temperature','C')
   src=c.sources()[0];signals=c.signals(source);run=c.begin(src,signals)
   for v in [21,22,23]:c.record(src,run,signals,{'temp':{'value':v,'quality':'good'}},1,{})
   l.equipment('CELL','Cell');l.item('PART','Part');job=l.job('WO','PART','CELL','LOT',10);l.event(job,'start','test');l.event(job,'report','test',3,1)
   before=c.path.read_bytes();server=CollectorAPI(c.path,0,l.path);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   base=f'http://127.0.0.1:{server.server_address[1]}'
   try:
    def get(path):return json.load(urlopen(base+path))
    result=get('/v1/web');self.assertTrue(result['collector']['available']);self.assertTrue(result['learning']['available']);self.assertEqual(result['collector']['sample_count'],3);self.assertEqual(result['learning']['jobs'][0]['good'],3)
    sid=result['collector']['signals'][0]['id'];self.assertEqual([r['value'] for r in get(f'/v1/history?signal_id={sid}&limit=2')['samples']],[22,23])
    for route in ['/','/dashboard.js','/style.css']:self.assertEqual(urlopen(base+route).status,200)
    with self.assertRaises(HTTPError) as error:get('/v1/history?signal_id=1&limit=999')
    self.assertEqual(error.exception.code,400)
    with self.assertRaises(HTTPError):urlopen(base+'/../README.md')
    self.assertEqual(c.path.read_bytes(),before)
   finally:server.shutdown();server.server_close();thread.join()
if __name__=='__main__':unittest.main()
