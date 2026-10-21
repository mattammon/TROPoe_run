import json
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import xarray as xr
from case_collections import save_collection, restore_collection, selected_cases, save_bands, read_bands
from dashboard_classification import ClassificationRules, read_selection_manifest, saved_catalogs, ReviewStore
from catalog_retrievals import create_catalog
from retrieval_todo import profile_index, pending_retrievals, save_todo, read_todo, execute_todo

class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.output=self.root/'retrievals'; self.output.mkdir()
        self.frame=pd.DataFrame(dict(case_id=['a','b'],sounding_time=['2025-01-01T12:01Z','2025-01-01T13:01Z'],
            retrieval_time=['2025-01-01T12:00Z','2025-01-01T13:00Z'],sounding_file=['a.nc','b.nc'],
            radiance_core_radiance_mean=[99.,1.],radiance_core_radiance_std=[9.,.1]))
        self.master=self.root/'master.csv';self.frame.to_csv(self.master,index=False)
        self.rules=ClassificationRules(use_asi=False)
    def save(self,name='My cases',ids=('a',),models=('Ch2_B6',)):
        return save_collection(self.master,self.frame,ids,name,self.rules,self.root/'groups',models)
    def output_file(self):
        p=self.output/'old_group'/'tropoeOutput_Ch2_B6.20250101.120000.nc';p.parent.mkdir(exist_ok=True)
        xr.Dataset(dict(temperature=(('time','height'),[[10.,9.]]),waterVapor=(('time','height'),[[2.,1.]])),
            coords=dict(time=pd.to_datetime(['2025-01-01T12:00']),height=[0.,1.])).to_netcdf(p)
        return p
    def queue(self,path):
        frame=read_selection_manifest(path)
        result=pending_retrievals(frame,profile_index([]),[6],path,self.output,models=['Ch2_B6'])
        queue=path.parent/'retrieval_todo.csv';save_todo(queue,result)
        return queue
    def test_membership_is_independent_of_classification(self):
        path=self.save()
        source,active,_=restore_collection(path)
        self.assertEqual(active['cases'].category.tolist(),['not_clear_sky'])
        self.assertEqual(selected_cases(active['cases']).case_id.tolist(),['a'])
        self.assertEqual(len(source['cases']),2)
        ReviewStore(self.root/'groups').save('a','uncertain')
        self.assertEqual(selected_cases(restore_collection(path)[1]['cases']).case_id.tolist(),['a'])
        self.assertEqual(read_bands(path),['Ch2_B6'])
        catalog,errors=saved_catalogs(self.root/'groups')
        self.assertFalse(errors);self.assertEqual(catalog[0]['path'],str(path))
        self.assertEqual(read_todo(self.queue(path),self.output).model.tolist(),['Ch2_B6'])
    def test_validation_and_band_edits(self):
        path=self.save();queue=self.queue(path)
        save_bands(path,['Ch1'])
        with self.assertRaisesRegex(ValueError,'no longer selected'):
            read_todo(queue,self.output)
        with self.assertRaises(ValueError): self.save(ids=['absent'])
        with self.assertRaises(ValueError): self.save(models=[])
        self.master.write_text(self.master.read_text()+'\n')
        with self.assertRaisesRegex(ValueError,'master changed'): restore_collection(path)
    def test_shared_inventory_and_group_summaries(self):
        self.output_file()
        first=self.save();second=self.save('Other selection',ids=('a','b'))
        universal,summary,_=create_catalog(self.output)
        self.assertIsNone(summary['manifest'])
        original=(universal/'summary.json').read_bytes()
        for path,total in [(first,1),(second,2)]:
            group,summary,_=create_catalog(self.output,path,[6],False,output_dir=path.parent/'catalog',
                reuse_inventory=True,inventory_dir=universal)
            self.assertEqual(summary['completed_by_band']['Ch2_B6'],1)
            self.assertEqual(summary['case_completion']['total_cases'],total)
            self.assertTrue((group/'summary.json').exists())
        self.assertEqual((universal/'summary.json').read_bytes(),original)
        rows=pd.read_csv(universal/'profiles.csv').to_dict('records')
        pending=pending_retrievals(read_selection_manifest(second),profile_index(rows),[6],second,self.output,models=['Ch2_B6'])
        self.assertEqual(pending.case_id.tolist(),['b'])
    def test_overlapping_workers_execute_once(self):
        first=self.queue(self.save('one'));second=self.queue(self.save('two'))
        calls=[]
        def run(date,channel,band):
            calls.append((date,channel,band));self.output_file()
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda p:execute_todo(p,self.output,run),[first,second]))
        self.assertEqual(len(calls),1)
        self.assertEqual({r[0]['status'] for r in results},{'completed','already_complete'})

    def test_collection_editor_and_reopen(self):
        from streamlit.testing.v1 import AppTest
        script = r"""
from pathlib import Path
from unittest.mock import patch
import streamlit as st
import dashboard_data as data
from dashboard_classification import fingerprint
from dashboard_setup import classification_gate
master = MASTER
root = ROOT
if 'cloud_loaded' not in st.session_state:
    st.session_state.cloud_loaded = dict(master=master,master_hash=fingerprint(master),cases=data.read_manifest(master),
        root=root, sonde_root='', image_root=root, output=str(Path(root)/'groups'))
with patch('dashboard_setup.plot_filter_controls', side_effect=lambda preview,*args:preview), \
     patch('dashboard_setup.inspect_case'), \
     patch('dashboard_setup.persistent_scatter',return_value=st.session_state.get('pick_batch')):
    source, active = classification_gate(master,root,'',root,str(Path(root)/'groups'))
    st.write('Loaded '+str(len(active['cases']))+' cases')
""".replace('MASTER',repr(str(self.master))).replace('ROOT',repr(str(self.root)))
        app=AppTest.from_string(script).run(timeout=30)
        self.assertFalse(app.exception)
        app.checkbox(key='collection_mode').check().run(timeout=30)
        app.session_state.pick_batch = dict(case_ids=['a'],token='first')
        app.run(timeout=30)
        self.assertFalse(app.exception)
        draft_key = 'collection_draft:'+str(self.master)
        self.assertEqual(app.session_state.filtered_state.get(draft_key, []), [])
        next(b for b in app.button if b.label == 'Add selected cases to collection').click().run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a'])
        # Clicking a different point inspects it without adding it.
        app.session_state.pick_batch = dict(case_id='b',token='inspect-b')
        app.run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a'])
        self.assertEqual(app.session_state['classification_case'], 'b')
        app.button(key='classification_add_case').click().run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a','b'])
        # Repeated adds are idempotent.
        app.button(key='classification_add_case').click().run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a','b'])
        next(m for m in app.multiselect if m.label == 'Selected collection cases (remove to exclude)').set_value(['a']).run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a'])
        app.run(timeout=30)
        self.assertEqual(app.session_state[draft_key], ['a'])
        app.text_input(key='collection_name').set_value('Cloudy subset')
        app.multiselect(key='new_group_models').set_value(['Ch2_B6'])
        next(b for b in app.button if b.label == 'Save collection and open dashboard').click().run(timeout=30)
        self.assertFalse(app.exception)
        app._run()  # Flush stale pre-rerun widgets in the Streamlit test harness.
        active=app.session_state.cloud_active
        self.assertEqual(active['cases'].case_id.tolist(),['a'])
        self.assertEqual(read_bands(active['path']),['Ch2_B6'])
        next(b for b in app.button if b.label == 'Choose another saved classification').click().run(timeout=30)
        app._run()
        next(b for b in app.button if b.label == 'Open selected catalog in dashboard').click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.cloud_active['path'],active['path'])

if __name__ == '__main__':unittest.main()
