import os
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from shared_outputs import atomic_text, shared_csv, shared_output
from dashboard_classification import ClassificationRules, ReviewStore, save_run
from fix_catalog_permissions import repair

class SharedOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.previous_umask=os.umask(0o077)
    def tearDown(self):
        os.umask(self.previous_umask); self.tmp.cleanup()
    def mode(self,path): return path.stat().st_mode & 0o777
    def test_atomic_and_dataframe_csv_ignore_restrictive_umask(self):
        path=self.root/'new'/'nested'/'todo.csv'
        atomic_text(path,'case_id\nx\n')
        self.assertEqual(self.mode(path),0o777)
        self.assertEqual(self.mode(path.parent),0o755)
        self.assertEqual(self.mode(path.parent.parent),0o755)
        shared_csv(pd.DataFrame({'case_id':['y']}),path,index=False)
        self.assertEqual(path.read_text(),'case_id\ny\n')
        self.assertEqual(self.mode(path),0o777)
        with self.assertRaises(RuntimeError):
            with shared_output(path) as f:
                f.write('partial'); raise RuntimeError('interrupted')
        self.assertEqual(path.read_text(),'case_id\ny\n')
    def test_rule_names_repeated_runs_and_readable_metadata(self):
        master=self.root/'master.csv'
        frame=pd.DataFrame(dict(case_id=['x'],sounding_file=['x.cdf'],retrieval_time=['2025-01-01T00:00Z'],radiance_core_radiance_mean=[1.],radiance_core_radiance_std=[.1]))
        shared_csv(frame,master,index=False)
        store=ReviewStore(self.root/'shared'/'reviews')
        _,first=save_run(master,frame,ClassificationRules(),store)
        _,second=save_run(master,frame,ClassificationRules(),store)
        self.assertEqual(first.parent.name,'core_ASI-z0-t10_RAD-m7-s0.3_either')
        self.assertEqual(second.parent.name,first.parent.name+'__2')
        for path in [first,second]:
            self.assertEqual(self.mode(path),0o777)
            self.assertEqual(self.mode(path.parent),0o755)
            self.assertEqual(self.mode(path.parent.parent),0o755)
            self.assertEqual(self.mode(path.parent/'settings.json'),0o644)
        self.assertEqual(self.mode(store.db),0o600)
    def test_existing_catalog_repair_preserves_data_and_skips_symlinks(self):
        old=self.root/'old'; old.mkdir(); child=old/'run'; child.mkdir()
        csv=child/'classification.csv'; csv.write_text('case_id,category\nx,clear_sky\n')
        outside=self.root/'outside'; outside.mkdir(); (old/'link').symlink_to(outside, target_is_directory=True)
        before=csv.read_bytes()
        count,errors=repair(old)
        self.assertFalse(errors); self.assertGreater(count,0)
        self.assertEqual(self.mode(old),0o755); self.assertEqual(self.mode(child),0o755)
        self.assertEqual(self.mode(csv),0o777); self.assertEqual(csv.read_bytes(),before)
        self.assertEqual(self.mode(outside),0o700)

if __name__=='__main__': unittest.main()
