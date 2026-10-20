import math
import tempfile
import unittest
from pathlib import Path
from learning.core import LabDB
from learning.scenarios import SCENARIOS,seed_scenario,bottleneck,retrieve,export_example


class LessonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=LabDB(Path(self.temp.name)/'lessons.sqlite3')
    def tearDown(self):self.temp.cleanup()
    def lesson(self,key,sid=1,sigma=3):
        spec=seed_scenario(self.db,key)
        return self.db.learn(spec['dataset'],sid,spec['asset'],sigma)
    def test_sizes_and_repeat_generation(self):
        counts={'quality':480,'drift':240,'energy':720,'data_quality':240}
        for key,count in counts.items():
            first=seed_scenario(self.db,key);second=seed_scenario(self.db,key)
            self.assertEqual(first['rows'],count);self.assertEqual(second['rows'],count)
            self.assertEqual(len(self.db.query('SELECT * FROM samples WHERE dataset=?',(first['dataset'],))),count)
    def test_sensitivity_tradeoff(self):
        normal=self.lesson('quality')['metrics'];sensitive=self.lesson('quality',sigma=.5)['metrics']
        self.assertEqual(normal['tp'],48);self.assertEqual(normal['tn'],24)
        self.assertGreater(sensitive['fp'],normal['fp'])
    def test_drift_is_not_defect(self):
        metrics=self.lesson('drift')['metrics']
        self.assertEqual(metrics['fp'],72);self.assertEqual(metrics['tp']+metrics['fn'],0)
    def test_energy_context_reduces_false_alarms(self):
        raw=self.lesson('energy')['metrics'];specific=self.lesson('energy',sid=3)['metrics']
        self.assertEqual(raw['fp'],24);self.assertEqual(specific['fp'],0)
        self.assertEqual(specific['tp'],48)
    def test_quality_mask_and_disjoint_lots(self):
        metrics=self.lesson('data_quality')['metrics']
        self.assertEqual(metrics['train_samples'],126);self.assertEqual(metrics['test_samples'],54)
        self.assertFalse(set(metrics['train_jobs']) & set(metrics['test_jobs']))
        self.assertEqual(metrics['fp'],0)
    def test_bottleneck_and_validation(self):
        base=bottleneck([30,60,45]);faster_non_bottleneck=bottleneck([10,60,45]);faster_bottleneck=bottleneck([30,40,45])
        self.assertEqual(base['expected_good'],faster_non_bottleneck['expected_good'])
        self.assertGreater(faster_bottleneck['expected_good'],base['expected_good']);self.assertEqual(faster_bottleneck['bottleneck'],3)
        for values in [[],[0,1],[-1,2],[math.inf]]:
            with self.assertRaises(ValueError):bottleneck(values)
    def test_retrieval_evidence_and_abstention(self):
        docs=retrieve('진동과 오탐을 확인하고 싶어요')
        self.assertEqual({d['id'] for d in docs},{'EDU-M01','EDU-M04'})
        self.assertTrue(all(d['matched'] and d['text'] for d in docs))
        self.assertEqual(retrieve('외계 행성의 이름'),[])
        with self.assertRaises(ValueError):retrieve(' ')
    def test_sigma_validation(self):
        spec=seed_scenario(self.db,'quality')
        for sigma in [0,7,math.nan,math.inf]:
            with self.assertRaises(ValueError):self.db.learn(spec['dataset'],1,spec['asset'],sigma)
    def test_example_export_isolated_and_marked_synthetic(self):
        import csv,json
        seed_scenario(self.db,'drift')
        path=Path(self.temp.name)/'quality.csv'
        self.assertEqual(export_example(self.db,'quality',path),480)
        with path.open(encoding='utf-8-sig') as stream:rows=list(csv.DictReader(stream))
        self.assertEqual({r['dataset'] for r in rows},{'lesson-quality-v1'})
        self.assertTrue(json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8'))['synthetic'])


if __name__=='__main__':unittest.main()
