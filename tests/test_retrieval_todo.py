import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import xarray as xr
from catalog_retrievals import scan
from dashboard_classification import ClassificationRules, ReviewStore, save_run
from retrieval_todo import completion_matrix, pending_retrievals, profile_index, save_todo, execute_todo

class TodoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.outputs=self.root/'outputs'; self.outputs.mkdir()
        self.cases=pd.DataFrame(dict(case_id=['clear','cloudy'],sounding_time=pd.to_datetime(['2025-01-01T12:12Z','2025-01-01T13:12Z']),retrieval_time=pd.to_datetime(['2025-01-01T12:15Z','2025-01-01T13:15Z']),sounding_file=['sonde.cdf','other.cdf'],radiance_core_radiance_mean=[6.,8.],radiance_core_radiance_std=[.2,.4]))
        self.master=self.root/'master.csv'; self.cases.to_csv(self.master,index=False)
        self.classified,self.selection=save_run(self.master,self.cases,ClassificationRules(use_asi=False),ReviewStore(self.root/'reviews'))
        self.queue=self.root/'todo.csv'
    def tearDown(self): self.tmp.cleanup()
    def output(self,model='Ch2_B6',time='2025-01-01T12:15',partial=False,filename=None):
        path=self.outputs/(filename or ('tropoeOutput_'+model+'.20250101.115500.nc'))
        values=np.array([[10.,11.,12.]])
        if partial: values[0,1]=np.nan
        xr.Dataset({'temperature':(('time','height'),values),'waterVapor':(('time','height'),np.ones((1,3)))},coords={'height':[0.,1.,2.],'time':pd.to_datetime([time])}).to_netcdf(path)
        return path
    def plan(self,bands=(6,)):
        _,profiles=scan(self.outputs,target_times=self.classified.loc[self.classified.category=='clear_sky','retrieval_time'])
        todo=pending_retrievals(self.classified,profile_index(profiles),bands,self.selection,self.outputs)
        save_todo(self.queue,todo); return todo
    def test_clear_only_missing_bands_and_partial_outputs(self):
        self.output()
        todo=self.plan([1,6])
        self.assertEqual(set(todo.case_id),{'clear'})
        self.assertEqual(set(todo.model),{'Ch1','Ch2_B1'})
        self.output(partial=True)
        todo=self.plan([6])
        self.assertIn('Ch2_B6',todo.model.tolist())
        self.assertEqual(todo.set_index('model').loc['Ch2_B6','reason'],'incomplete_output')
        self.classified['category']='not_clear_sky'
        self.assertTrue(self.plan().empty)
    def test_completion_grid_uses_usable_records_and_selected_bands(self):
        cases=self.classified.copy()
        second=cases.loc[cases.category=='clear_sky'].iloc[0].copy()
        second['case_id']='second'
        second['retrieval_time']=pd.Timestamp('2025-01-01T14:15Z')
        cases=pd.concat([cases,pd.DataFrame([second])],ignore_index=True)
        index=pd.DataFrame({'model':['Ch2_B6','Ch1','Ch2_B6'],
                            'status':['usable','partial','usable'],
                            'time':pd.to_datetime(['2025-01-01T12:16:00Z','2025-01-01T12:15:00Z','2025-01-01T14:16:01Z'])})
        grid=completion_matrix(cases,index,['Ch1','Ch2_B6'],60.)
        self.assertEqual(grid.index.tolist(),['clear','second'])
        self.assertEqual(grid.to_numpy().tolist(),[[False,True],[False,False]])
        from dashboard_catalog import completion_summary
        table,all_complete,none_complete=completion_summary(grid[['Ch2_B6']])
        self.assertEqual((table['Completed retrievals'].tolist(),all_complete,none_complete),([1],1,1))
        _,all_complete,none_complete=completion_summary(grid)
        self.assertEqual((all_complete,none_complete),(0,1))
    def test_scanner_skips_profile_variables_outside_clear_times(self):
        self.output()
        # Outside the clear cohort: valid timestamp but no T/q variables at all.
        xr.Dataset(coords={'time':pd.to_datetime(['2025-01-01T13:15'])}).to_netcdf(self.outputs/'tropoeOutput_Ch1.20250101.131500.nc')
        files,profiles=scan(self.outputs,target_times=[pd.Timestamp('2025-01-01T12:15Z')])
        self.assertEqual(len(profiles),1)
        self.assertEqual(next(f['status'] for f in files if f['channel']==1),'outside_selection')
    def test_runner_rechecks_stale_plan_and_runs_only_missing_pair(self):
        todo=self.plan()
        self.assertEqual(set(todo.model),{'Ch1','Ch2_B6'})
        self.output() # Completed AFTER to-do creation, with a misleading filename time.
        calls=[]
        def run(date,channel,band):
            calls.append((date,channel,band))
            self.output('Ch1')
        results=execute_todo(self.queue,self.outputs,run)
        self.assertEqual(calls,[('202501011212',1,None)])
        self.assertEqual({r['status'] for r in results},{'completed','already_complete'})
        self.assertTrue(all(r['status']=='already_complete' for r in execute_todo(self.queue,self.outputs,run)))
        self.assertEqual(len(calls),1)
        self.assertTrue(self.queue.with_name('todo_last_run.csv').is_file())
    def test_group_entrypoint_uses_configured_queue(self):
        import runpy
        import types
        import config
        from unittest.mock import Mock
        self.output(); self.plan()
        fake_utils=types.ModuleType('utils')
        fake_vip=types.ModuleType('vip_gen'); fake_vip.VIP=Mock(return_value=object())
        fake_single=types.ModuleType('SINGLE_TROPoe')
        def run(date,vip,channel=None,band=None,verbose=None):
            self.assertEqual((date,channel,band),('202501011212',1,None))
            self.output('Ch1')
        fake_single.run_tropoe=Mock(side_effect=run)
        with patch.multiple(config, RETRIEVAL_TODO_MANIFEST=str(self.queue), RETRIEVAL_DIR=str(self.root), GROUP_NAME='outputs'), patch.dict(sys.modules, {'utils':fake_utils,'vip_gen':fake_vip,'SINGLE_TROPoe':fake_single}):
            runpy.run_path(str(Path(__file__).resolve().parents[1]/'GROUP_TROPoe.py'),run_name='__main__')
        fake_single.run_tropoe.assert_called_once()
        fake_vip.VIP.assert_called_once_with(in_group=True)

    def test_failure_empty_and_invalid_plans(self):
        self.output(); self.plan()
        def fails(*args): raise RuntimeError('retrieval failure')
        results=execute_todo(self.queue,self.outputs,fails)
        self.assertEqual(results[0]['status'],'failed')
        # No output created must not be reported as completed.
        self.assertEqual(execute_todo(self.queue,self.outputs,lambda *args:None)[0]['status'],'still_missing_or_incomplete')
        frame=pd.read_csv(self.queue).fillna(''); frame['category']='not_clear_sky'; save_todo(self.queue,frame)
        with self.assertRaisesRegex(ValueError,'only clear-sky'): execute_todo(self.queue,self.outputs,fails)
        save_todo(self.queue,frame.iloc[:0])
        self.assertEqual(execute_todo(self.queue,self.outputs,fails),[])
        with self.assertRaises(FileNotFoundError): execute_todo(self.root/'absent.csv',self.outputs,fails)

if __name__=='__main__': unittest.main()

