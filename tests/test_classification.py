import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from dashboard_classification import *

class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.frame = pd.DataFrame(dict(case_id=['a','b','c','d'], sounding_file=['a.cdf']*4,
            retrieval_time=['2025-01-01T12:00Z']*4, sounding_time=['2025-01-01T11:59Z']*4,
            category=['uncertain']*4, reason=['old']*4, asi_state=['uncertain']*4,
            asi_core_zenith_mean=[0,1,np.nan,0], asi_core_total_mean=[10,20,np.nan,0],
            radiance_core_radiance_mean=[7,6,np.nan,8], radiance_core_radiance_std=[.3,.2,.2,.4]))
        self.source=self.root/'old.csv'; self.frame.to_csv(self.source,index=False)
        self.master=prepare_master(self.source)
        self.store=ReviewStore(self.root/'reviews')
    def tearDown(self): self.tmp.cleanup()
    def test_import_preserves_diagnostics_and_source(self):
        clean=pd.read_csv(self.master)
        self.assertFalse(set(clean)&CLASS_COLUMNS)
        self.assertIn('category',pd.read_csv(self.source))
        self.assertEqual(prepare_master(self.source),self.master)
        pd.testing.assert_series_equal(clean.asi_core_total_mean,self.frame.asi_core_total_mean)
    def test_rules_missing_equality_and_combination(self):
        self.assertEqual(classify(self.frame,ClassificationRules()).category.tolist(),['clear_sky','clear_sky','uncertain','clear_sky'])
        self.assertEqual(classify(self.frame,ClassificationRules(combine='both')).category.tolist(),['clear_sky','not_clear_sky','uncertain','not_clear_sky'])
        self.assertEqual(classify(self.frame,ClassificationRules(use_asi=False)).category.tolist(),['clear_sky','clear_sky','uncertain','not_clear_sky'])
    def test_restore_saved_catalog_and_later_manual_decisions(self):
        rules=ClassificationRules(use_asi=False,radiance_mean_max=6.5)
        original,path=save_run(self.master,self.frame,rules,self.store)
        catalogs,errors=saved_catalogs(self.store.root)
        self.assertEqual([c['path'] for c in catalogs],[str(path)])
        self.assertEqual(errors,[])
        base,active,updated=restore_saved_catalog(path)
        self.assertFalse(updated)
        self.assertEqual(active['path'],str(path))
        self.assertEqual(active['rules']['radiance_mean_max'],6.5)
        self.assertEqual(active['cases'].category.tolist(),original.category.tolist())
        self.assertNotIn('category',base['cases'])
        self.assertEqual(len(list((self.store.root/'runs').glob('*/classification.csv'))),1)
        self.store.save('a','clear_sky','New satellite review')
        _,active,updated=restore_saved_catalog(path)
        self.assertTrue(updated)
        self.assertNotEqual(active['path'],str(path))
        self.assertEqual(active['cases'].set_index('case_id').loc['a','category'],'clear_sky')
        self.assertEqual(pd.read_csv(path).category.tolist(),original.category.tolist())
        self.master.write_text(self.master.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Master has changed'):
            restore_saved_catalog(path)

    def test_catalog_discovery_ignores_unpublished_and_reports_bad_settings(self):
        pending=self.store.root/'runs'/'.pending_example'
        pending.mkdir(parents=True)
        (pending/'classification.csv').write_text('case_id,category\n')
        broken=self.store.root/'runs'/'broken'
        broken.mkdir()
        (broken/'classification.csv').write_text('case_id,category\n')
        catalogs,errors=saved_catalogs(self.store.root)
        self.assertFalse(catalogs)
        self.assertEqual(len(errors),1)
        self.assertIn('broken',errors[0]['path'])
    def test_audit_persistence_immutable_runs_and_join(self):
        self.store.save('a','not_clear_sky','Cloud visible','202501011159.png','reviewer')
        store=ReviewStore(self.store.root)
        out, first=save_run(self.master,self.frame,ClassificationRules(),store)
        before=first.read_bytes()
        self.assertEqual(out.category.iloc[0],'not_clear_sky')
        self.assertEqual(list(pd.read_csv(first)),['case_id','category'])
        self.assertEqual(read_selection_manifest(first).category.iloc[0],'not_clear_sky')
        store.save('a',None,'Reconsidered')
        out, second=save_run(self.master,self.frame,ClassificationRules(),store)
        self.assertNotEqual(first,second)
        self.assertEqual(first.read_bytes(),before)
        self.assertEqual(out.category.iloc[0],'clear_sky')
        self.assertEqual(len(store.history()),2)
        self.master.write_text(self.master.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'Master has changed'): read_selection_manifest(first)
    def test_unclassified_requires_selection_and_satellite_matching(self):
        with self.assertRaisesRegex(ValueError,'Master is unclassified'): read_selection_manifest(self.master)
        for name in ['202501011159_visible.png','202501011200_visible.png','202501011159_readme.txt']:
            (self.root/name).touch()
        self.assertEqual([p.name for p in satellite_images(self.root,'2025-01-01T06:59-05:00')],['202501011159_visible.png'])
    def test_collection_diagnostics_only(self):
        from cloud_screening import evaluate_case, ScreenPolicy
        case=evaluate_case(pd.Timestamp('2025-01-01'),pd.DataFrame(),pd.DataFrame(),ScreenPolicy(),diagnostics_only=True)
        self.assertNotIn('category',case)
        self.assertNotIn('state',case['evidence']['asi'])
        self.assertIn('coverage',case['evidence']['asi']['core'])

    def test_offline_collection_writes_unclassified_master(self):
        import xarray as xr
        from get_sgp_data import SGP_DATA
        directories={key:self.root/key for key in SGP_DATA.streams}
        for directory in directories.values(): directory.mkdir()
        (directories['sonde']/'ALL').mkdir()
        sounding=directories['sonde']/'ALL'/'sgpsondewnpnC1.b1.20250101.115900.cdf'
        xr.Dataset({'temperature': ('time',[1.])},coords={'time':pd.to_datetime(['2025-01-01T11:59'])}).to_netcdf(sounding)
        manifest=SGP_DATA('20250101','20250101',directories=directories).screen_cases(offline=True,output_dir=self.root/'collected')
        frame=pd.read_csv(manifest)
        self.assertEqual(len(frame),1)
        self.assertFalse(set(frame)&CLASS_COLUMNS)
        case=json.loads((manifest.parent/'cases.json').read_text())[0]
        self.assertNotIn('category',case)
        self.assertNotIn('state',case['evidence']['radiance'])
        self.assertFalse((manifest.parent/'clear_sky').exists())
        self.assertEqual(json.loads((manifest.parent/'metadata.json').read_text())['counts'],{'cases':1})

    def test_retrieval_and_catalog_use_compact_selection(self):
        from unittest.mock import patch
        from cloud_screening import selected_sounding_files
        from catalog_retrievals import expected_cases
        (self.root/'a.cdf').touch()
        _, selection=save_run(self.master,self.frame,ClassificationRules(),self.store)
        with patch('config.CLOUD_CLASSIFICATION_MANIFEST',str(selection)):
            self.assertEqual(selected_sounding_files(self.root,'unused',self.master),[str(self.root/'a.cdf')])
        rows=expected_cases(selection,[],[6],True,'clear_sky',60)
        self.assertEqual(len(rows),6)  # Three clear cases, each with Ch1 and B6.
        self.assertTrue(all(r['status']=='missing' for r in rows))

if __name__=='__main__': unittest.main()

