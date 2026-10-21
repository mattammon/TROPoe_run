import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from dashboard_data import load_retrieval, signature
from dashboard_diagnostics import dfs_profile_panels, case_diagnostic, rmsr_summary


class DiagnosticTests(unittest.TestCase):
    def test_uncertainty_units_and_rmsr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'retrieval.nc'
            ds = xr.Dataset(dict(temperature=(('time','height'), [[280.,281.]], {'units':'K'}),
                waterVapor=(('time','height'), [[.004,.005]], {'units':'kg/kg'}),
                sigma_temperature=(('time','height'), [[1.,2.]], {'units':'K'}),
                sigma_waterVapor=(('time','height'), [[.001,.002]], {'units':'kg/kg'}),
                rmsr=('time',[1.2]), rmsa=('time',[9.]), gamma=('time',[.25])),
                coords={'time':pd.to_datetime(['2025-01-01']), 'height':[0.,1.]})
            ds.to_netcdf(path)
            profile = load_retrieval(signature(path),0,pd.Timestamp('2025-01-01',tz='UTC'))
            np.testing.assert_allclose(profile['sigma_T'],[1.,2.])
            np.testing.assert_allclose(profile['sigma_q'],[1.,2.])
            self.assertEqual(profile['rmsr'],1.2)
            self.assertEqual(profile['rmsa'],9.)
            self.assertEqual(profile['gamma'],.25)
            self.assertAlmostEqual(profile['T'][0],6.85)

    def analysis(self):
        info = {}
        for case, base, band in [('a',0.,1.),('b',50.,2.),('c',51.,100.)]:
            for model, value in [('Ch1',base),('Ch2_B1',band)]:
                info[(case,model)] = dict(source='kernel',density=np.array([value,value]),
                    cumulative=np.array([0.,value,value*2]), full_edges=np.array([0.,1.,2.]),
                    full_cumulative=np.array([0.,value,value*2]))
        # No matching baseline source: must not enter the difference median.
        info[('unmatched','Ch2_B1')] = dict(info[('a','Ch2_B1')],density=np.array([10000.,10000.]))
        return dict(information=info,variable='T',edges=np.array([0.,1.,2.]),centers=np.array([.5,1.5]))

    def test_median_paired_differences_and_actual_ch1(self):
        panels = dfs_profile_panels(self.analysis(),['Ch2_B1'],'Density profiles',True)
        source, fig, counts = panels[0]
        actual, delta = fig.data[:2]
        np.testing.assert_allclose(np.asarray(actual.z)[:,0],[50.,50.])
        np.testing.assert_allclose(np.asarray(delta.z)[:,1],[1.,1.])
        self.assertTrue(np.isnan(np.asarray(actual.z)[:,1]).all())
        self.assertTrue(np.isnan(np.asarray(delta.z)[:,0]).all())
        self.assertEqual(counts.Cases.tolist(),[3,3])
        self.assertEqual(fig.layout.coloraxis2.cmin,-fig.layout.coloraxis2.cmax)
        self.assertEqual(fig.layout.coloraxis2.colorscale[-1][1],'rgb(103,0,31)')

    def test_source_mismatch_and_missing_baseline(self):
        analysis = self.analysis()
        analysis['information'] = {('a','Ch1'):analysis['information'][('a','Ch1')],
            ('a','Ch2_B1'):dict(analysis['information'][('a','Ch2_B1')],source='cdfs')}
        panels = dfs_profile_panels(analysis,['Ch2_B1'],'Cumulative profiles',True)
        self.assertTrue(all(p[2].loc[p[2].Band.eq('Ch2_B1'),'Cases'].iloc[0] == 0 for p in panels))

    def test_case_heatmap_and_rmsr_missing_values(self):
        profiles = {('case','Ch1'):dict(z=np.array([0.,1.,2.]),sigma_T=np.array([1.,2.,3.]), rmsr=2., rmsa=1., gamma=.5,
            information={'variables':{'T':dict(dfs_level=np.ones(3),source='kernel')}}),
            ('case','Ch2_B1'):dict(z=np.array([0.,1.,2.]),rmsr=1., rmsa=2.)}
        edges=np.array([0.,1.,2.])
        fig, export, issues = case_diagnostic('case', profiles,['Ch1','Ch2_B1'],'T',edges,'1-sigma uncertainty')
        np.testing.assert_allclose(export.Ch1,[1.5,2.5])
        self.assertTrue(export.Ch2_B1.isna().all())
        self.assertEqual(len(issues),1)
        _, export, _ = case_diagnostic('case',profiles,['Ch1'],'T',edges,'Cumulative DFS')
        np.testing.assert_allclose(export.Ch1,[1.5,3.])
        table, _ = rmsr_summary('case',profiles,['Ch1','Ch2_B1','Ch2_B2'])
        self.assertEqual(table.Band.tolist(),['Ch1','Ch2_B1','Ch2_B2'])
        self.assertTrue(pd.isna(table.Rank.iloc[-1]))

    def test_fixed_cumulative_scales(self):
        for variable, maximum in [('T', 5.), ('q', 3.)]:
            analysis = dict(self.analysis(), variable=variable)
            for difference in (False, True):
                fig = dfs_profile_panels(analysis, ['Ch1','Ch2_B1'], 'Cumulative profiles', difference)[0][1]
                self.assertEqual((fig.layout.coloraxis.cmin, fig.layout.coloraxis.cmax), (0., maximum))
                self.assertEqual(len(fig.layout.coloraxis.colorscale), 200)
            profiles = {('case','Ch1'): dict(z=np.array([0.,1.,2.]), information={'variables':{
                variable: dict(dfs_level=np.ones(3),source='kernel')}})}
            fig, _, _ = case_diagnostic('case',profiles,['Ch1'],variable,np.array([0.,1.,2.]),'Cumulative DFS')
            self.assertEqual((fig.layout.coloraxis.cmin, fig.layout.coloraxis.cmax), (0., maximum))

    def test_satellite_panel_handles_missing_images(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp:
            script = '''
import pandas as pd
from dashboard_satellite_panel import render_satellite_panel
cases = pd.DataFrame([dict(case_id='a', sounding_time=pd.Timestamp('2025-01-01',tz='UTC'), retrieval_time=pd.Timestamp('2025-01-01',tz='UTC'), category='clear_sky')])
render_satellite_panel(cases, {'image_root':ROOT})
'''.replace('ROOT',repr(tmp))
            app=AppTest.from_string(script).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='satellite_case_widget').value,'a')
            self.assertTrue(any('No matching satellite' in msg.value for msg in app.info))

    def test_dashboard_pages_with_satellite_panel(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp:
            master = Path(tmp)/'master.csv'
            master.write_text('test')
            script = r"""
import runpy
import numpy as np
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import streamlit as st
import config
import dashboard_data as data
from dashboard_classification import ClassificationRules
cases, models, profiles, observations = data.demo_data()
cases = cases.iloc[:2].copy()
cases['category'] = 'clear_sky'
case = cases.case_id.iloc[0]
models = ['Ch1','Ch2_B1']
for m in models:
    n = len(profiles[(case,m)]['z'])
    profiles[(case,m)]['smoothing'] = dict(kernel=np.eye(2*n), prior=np.r_[profiles[(case,m)]['T'], profiles[(case,m)]['q']], auxiliary_policy='prior (zero departure)')
    profiles[(case,m)].update(sigma_T=profiles[(case,m)]['T']*0+1., sigma_q=profiles[(case,m)]['q']*0+.1, rmsr=1., rmsa=2.)
root = ROOT
master = str(Path(root)/'master.csv')
source = dict(root=root, master=master, sonde_root='', image_root=root, output=root, cases=cases)
active = dict(path=master, cases=cases, rules=asdict(ClassificationRules()))
index = pd.DataFrame([dict(file=m, profile_index=0, time=cases.retrieval_time.iloc[0], status='usable', model=m) for m in models])
scope = ('shared_catalog_v2',master,root,(1,),60.,True)
st.session_state.loaded_source = dict(index=index,errors=pd.DataFrame(),manifest=master,root=root,catalog='',sonde_root='',scope=scope,saved_inventory=True,inventory_time='test')
if 'dashboard_view' not in st.session_state:
    st.session_state.dashboard_view='Information content'
with patch.multiple(config,RETRIEVAL_TODO_MANIFEST=None,RETRIEVAL_TODO_BANDS=[1],RETRIEVAL_TODO_TOLERANCE_SECONDS=60.), \
     patch('dashboard_setup.classification_gate',return_value=(source,active)), \
     patch.object(data,'signature',side_effect=lambda p:(str(p),1,1)), \
     patch.object(data,'load_retrieval',side_effect=lambda sig,*args,**kwargs:profiles[(case,sig[0])]), \
     patch.object(data,'sounding_path',return_value='sonde'), \
     patch.object(data,'load_sounding',return_value=observations[case]):
    runpy.run_path(APP,run_name='__main__')
""".replace('ROOT',repr(tmp)).replace('APP',repr(str(Path(__file__).resolve().parents[1]/'TROPoe_APP.py')))
            app=AppTest.from_string(script).run(timeout=30)
            self.assertFalse(app.exception)
            app.checkbox(key='show_dashboard_satellite').check().run(timeout=30)
            self.assertFalse(app.exception)
            app.checkbox(key='info_difference').check().run(timeout=30)
            self.assertFalse(app.exception)
            app.selectbox(key='dashboard_view').set_value('AK-smoothed RMSE').run(timeout=30)
            self.assertFalse(app.exception)
            app.selectbox(key='dashboard_view').set_value('Vertical profiles').run(timeout=30)
            self.assertFalse(app.exception)
            second = 'DEMO_20250101T1200'
            app.selectbox(key='dashboard_profile_case').select(second).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='satellite_case_widget').value, app.selectbox(key='dashboard_profile_case').value)
            chosen = app.session_state.dashboard_case
            app.checkbox(key='show_dashboard_satellite').uncheck().run(timeout=30)
            app.checkbox(key='show_dashboard_satellite').check().run(timeout=30)
            self.assertEqual(app.selectbox(key='satellite_case_widget').value, chosen)
            next(r for r in app.radio if r.label == 'Case profile shading').set_value('1-sigma uncertainty').run(timeout=30)
            self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
