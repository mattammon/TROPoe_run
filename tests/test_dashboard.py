"""Dashboard integration checks; run with python -m unittest discover -s tests -p test_dashboard.py."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import xarray as xr

import dashboard_data as data
import dashboard_plots as plots


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        from unittest.mock import patch
        self.todo_patch = patch('config.RETRIEVAL_TODO_MANIFEST', str(self.root/'todo.csv'))
        self.todo_patch.start()
        self.addCleanup(self.todo_patch.stop)
        self.aod_patch = patch('config.AOD_DIR', str(self.root))
        self.aod_patch.start()
        self.addCleanup(self.aod_patch.stop)
        self.z = np.linspace(0, 3, 31)
        self.times = pd.date_range('2025-01-01T12:00', periods=2, freq='15min')
        # Filename time deliberately differs from BOTH actual record times.
        self.path = self.root/'tropoeOutput_Ch2_B6.20250101.115500.nc'
        xr.Dataset({'aod_500': ('time', [.1, .2]), 'aod_870': ('time', [.05, .1])},
                   coords={'time': self.times}).to_netcdf(self.root/'sgpcsphotaodfiltqav3C1.a1.20250101.000000.nc')
        temperature = np.stack([10-6*self.z, 12-6*self.z])
        ds = xr.Dataset(dict(temperature=(('time', 'height'), temperature, {'units': 'C'}),
                             waterVapor=(('time', 'height'), np.ones_like(temperature)*0.005, {'units': 'kg/kg'}),
                             dewpt=(('time', 'height'), temperature-5, {'units': 'C'}),
                             cdfs_temperature=(('time', 'height'), np.tile(np.arange(1, 32)*0.1, (2, 1))),
                             cdfs_waterVapor=(('time', 'height'), np.tile(np.arange(1, 32)*0.05, (2, 1)))),
                        coords={'time': self.times, 'height': ('height', self.z, {'units': 'km'})})
        ds.to_netcdf(self.path)
        self.sonde = self.root/'sonde.cdf'
        xr.Dataset(dict(alt=('sample', self.z*1000+237, {'units': 'm'}),
                        tdry=('sample', temperature[1], {'units': 'C'}),
                        rh=('sample', np.full(31, 50.), {'units': '%'}),
                        pres=('sample', 1000*np.exp(-self.z/8), {'units': 'hPa'}))).to_netcdf(self.sonde)
        self.manifest = self.root/'manifest.csv'
        pd.DataFrame([dict(case_id='case', retrieval_time='2025-01-01T12:15:00Z',
                           sounding_time='2025-01-01T12:12:00Z', sounding_file=str(self.sonde),
                           category='uncertain', asi_state='uncertain', radiance_state='clear_sky')]).to_csv(self.manifest, index=False)

    def tearDown(self):
        self.temp.cleanup()

    def test_actual_time_multi_record_and_units(self):
        index, errors = data.read_index(self.root)
        self.assertTrue(errors.empty)
        cases = data.read_manifest(self.manifest)
        matches = data.match_cases(cases, index, ['Ch2_B6'], 0)
        row = matches.iloc[0]
        self.assertEqual(row.profile_index, 1)
        self.assertEqual(row.offset_seconds, 0)
        profile = data.load_retrieval(data.signature(row.file), row.profile_index, row.matched_time)
        np.testing.assert_allclose(profile['T'], 12-6*self.z)
        np.testing.assert_allclose(profile['q'], 5)
        self.assertEqual(profile['information']['variables']['T']['source'], 'cdfs_temperature')
        with self.assertRaisesRegex(ValueError, 'Catalog time changed'):
            data.load_retrieval(data.signature(row.file), 0, row.matched_time)
        observation = data.load_sounding(data.signature(self.sonde))
        np.testing.assert_allclose(observation['z'], self.z)
        out = data.build_analysis(cases, ['Ch2_B6'], {('case', 'Ch2_B6'): profile}, {'case': observation}, 'T', np.linspace(0.1, 3, 30))
        self.assertAlmostEqual(out['metrics'].rmse.iloc[0], 0)
        self.assertGreater(out['metrics'].dfs.iloc[0], 0)

    def test_inclusive_dates_and_missing_cloud_values(self):
        cases, _, _, _ = data.demo_data()
        day = cases.sounding_time.iloc[0].date()
        bounds = {'asi_core_total_mean': (-np.inf, 100)}
        retained = data.filter_cases(cases, (day, day), {}, bounds, True)
        dropped = data.filter_cases(cases, (day, day), {}, bounds, False)
        self.assertEqual(len(retained), 2)
        self.assertEqual(len(dropped), 1)
        self.assertTrue(data.filter_cases(cases, (day, day), {'category': []}).empty)

    def test_paired_bands_no_extrapolation_and_dfs_without_sounding(self):
        cases, models, profiles, obs = data.demo_data()
        edges = np.linspace(.1, 3, 30)
        paired = data.build_analysis(cases, models, profiles, obs, 'T', edges, True)
        unpaired = data.build_analysis(cases, models, profiles, obs, 'T', edges, False)
        self.assertLess(len(paired['metrics']), len(unpaired['metrics']))
        self.assertEqual(paired['metrics'].groupby('model').size().nunique(), 1)
        beyond = data.build_analysis(cases, models, profiles, obs, 'T', np.linspace(.1, 7, 30), False)
        self.assertTrue(beyond['metrics'].empty)
        self.assertFalse(beyond['information'])
        no_obs = data.build_analysis(cases, [models[0]], profiles, {}, 'T', edges)
        self.assertTrue(no_obs['metrics'].empty)
        self.assertGreater(len(no_obs['information']), 0)
        for p in profiles.values():
            p['T'][15] = np.nan
        missing = data.build_analysis(cases, models, profiles, obs, 'T', edges, False)
        self.assertTrue(missing['metrics'].empty)

    def test_all_plot_types(self):
        cases, models, profiles, obs = data.demo_data()
        a = data.build_analysis(cases, models, profiles, obs, 'T', np.linspace(.1, 3, 30))
        figs = [plots.profile_plot(cases.case_id.iloc[0], models, profiles, obs, 'T', (.1, 3)),
                plots.taylor_plot(a, models)[0], plots.dfs_rmse_plot(a)[0],
                plots.screening_plot(cases, 'radiance_core_radiance_mean', 'asi_core_total_mean')]
        figs += [plots.rmse_plot(a, models, mode) for mode in ['Distributions', 'Timeline', 'Case heatmap']]
        figs.append(plots.rmse_plot(a, models, 'Case heatmap', 'Ch1'))
        figs += [plots.error_plot(a, models[0], mode) for mode in ['Case-height errors', 'Vertical RMSE']]
        figs += [plots.info_plot(a, mode) for mode in ['Layer distributions', 'Density profiles', 'Cumulative profiles']]
        for fig in figs:
            self.assertGreater(len(fig.data), 0)
            self.assertIn('plotly', fig.to_html(include_plotlyjs=False))

    def test_radiance_categories_thresholds_and_labels(self):
        cases, _, _, _ = data.demo_data()
        cases = cases.iloc[:4].copy()
        cases['sounding_time'] = pd.to_datetime(['2025-01-01T01:00Z', '2025-04-01T07:00Z',
                                               '2025-07-01T13:00Z', '2025-10-01T19:00Z'])
        cases['case_id'] = ['case_sounding_%d.nc' % n for n in range(4)]
        cases['radiance_core_radiance_mean'] = [1., 6., 8., np.inf]
        cases['radiance_core_radiance_std'] = [.1, .2, .4, .5]
        cases['radiance_context_radiance_mean'] = [2., 7., 9., 10.]
        cases['radiance_context_radiance_std'] = [.2, .3, .5, .6]
        meta = data.case_metadata(cases)
        self.assertEqual(meta.Season.tolist(), data.GROUP_ORDERS['Season'])
        self.assertEqual(meta['Time of day (UTC)'].tolist(), data.GROUP_ORDERS['Time of day (UTC)'])
        self.assertEqual(meta.Case.iloc[0], '01 Jan 2025 · 01:00 UTC')
        for group in ['Season', 'Month', 'Time of day (UTC)', 'Classification',
                      'ASI classification', 'Radiance classification', 'Year']:
            fig, frame = plots.radiance_plot(cases, 'core', group, 7., .3, True, True)
            self.assertEqual(len(frame), 3)  # inf is excluded; out-of-limit context remains
            self.assertEqual(sum(len(t.x) for t in fig.data), 3)
            self.assertEqual(len(fig.layout.shapes), 3)
            self.assertTrue(any(sh.x0 == 7 and sh.x1 == 7 for sh in fig.layout.shapes))
            self.assertTrue(any(sh.y0 == .3 and sh.y1 == .3 for sh in fig.layout.shapes))
            self.assertNotIn('.nc', fig.to_json())
        _, spring = plots.radiance_plot(cases, 'context', 'Season', 7., .3, categories=['Spring (MAM)'])
        self.assertEqual(spring['radiance_context_radiance_mean'].tolist(), [7.])
        fig, empty = plots.radiance_plot(cases, 'core', 'Season', 7., .3, categories=[])
        self.assertTrue(empty.empty)
        self.assertEqual(len(fig.data), 0)
        self.assertTrue(all('inactive' in a.text for a in fig.layout.annotations))
        # Display names never replace the actual identity, even for same-time cases.
        labels = dict(zip(cases.case_id, meta.Case))
        displayed = data.display_cases(cases, labels)
        self.assertNotIn('case_id', displayed)
        self.assertEqual(data.display_cases(cases, labels, keep_id=True).case_id.tolist(), cases.case_id.tolist())

    def test_vertical_joint_rmse_and_difference(self):
        from dashboard_vertical import compare_variables, case_error_panels, plotly_size_kwargs
        cases, models, profiles, obs = data.demo_data()
        cases = cases.iloc[:2]
        models = ['Ch1', 'Ch2_B1']
        for case in cases.case_id:
            for m, factor in zip(models, (1., 2.)):
                profiles[(case, m)]['T'] = obs[case]['T']+factor
                profiles[(case, m)]['q'] = obs[case]['q']+factor*3
        analyses, common, table, scales = compare_variables(cases, models, profiles, obs, np.linspace(.1, 3, 30))
        self.assertEqual(len(common), 2)
        self.assertAlmostEqual(table.loc['Ch1', 'Temperature RMSE (°C)'], 1)
        self.assertAlmostEqual(table.loc['Ch2_B1', 'Mixing ratio RMSE (g/kg)'], 6)
        self.assertAlmostEqual(table.loc['Ch2_B1', 'Combined normalized RMSE'], 2*table.loc['Ch1', 'Combined normalized RMSE'])
        fig, n, total = case_error_panels(analyses['T'], 'Ch2_B1', models, common[0], common)
        np.testing.assert_allclose(np.asarray(fig.data[1].z), 1.)
        self.assertEqual((n, total), (2, 2))
        reference_only, _, _, _ = compare_variables(cases, ['Ch2_B1'], profiles, obs, np.linspace(.1, 3, 30))
        self.assertFalse(any(m == 'Ch1' for _, m in reference_only['T']['curves']))
        _, n, total = case_error_panels(reference_only['T'], 'Ch2_B1', ['Ch2_B1'], common[0], common)
        self.assertEqual((n, total), (0, 2))
        del profiles[(common[0], 'Ch2_B1')]['q']
        _, common, _, _ = compare_variables(cases, models, profiles, obs, np.linspace(.1, 3, 30))
        self.assertEqual(len(common), 1)
        def legacy(figure, use_container_width=True, **kwargs): pass
        def modern(figure, width='stretch', **kwargs): pass
        self.assertEqual(plotly_size_kwargs(legacy), {'use_container_width': True})
        self.assertEqual(plotly_size_kwargs(modern), {'width': 'stretch'})

    def test_classification_first_and_real_dashboard(self):
        from streamlit.testing.v1 import AppTest
        frame = pd.read_csv(self.manifest)
        frame['radiance_core_radiance_mean'] = 6.
        frame['radiance_core_radiance_std'] = .2
        extra = frame.iloc[0].copy()
        extra['case_id'] = 'cloudy'
        extra['retrieval_time'] = '2025-01-01T13:15:00Z'
        extra['sounding_time'] = '2025-01-01T13:12:00Z'
        extra['radiance_core_radiance_mean'] = 20.
        extra['radiance_core_radiance_std'] = 2.
        frame = pd.concat([frame, pd.DataFrame([extra])], ignore_index=True)
        frame.to_csv(self.manifest, index=False)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'TROPoe_APP.py'), default_timeout=60).run()
        self.assertFalse(app.exception)
        self.assertFalse(any(s.label == 'Plot' for s in app.selectbox))
        for label, value in [('Master manifest CSV (legacy manifests can be imported)', str(self.manifest)),
                             ('Retrieval directory', str(self.root)),
                             ('Classification and manual-review directory', str(self.root/'reviews')),
                             ('Satellite PNG directory', str(self.root))]:
            next(t for t in app.text_input if t.label == label).set_value(value)
        next(b for b in app.button if b.label == 'Load / refresh master data').click().run()
        app._run()  # Flush stale pre-rerun elements in the Streamlit 1.50 test harness.
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[0].value, '1')
        next(b for b in app.button if b.label == 'Apply classification and open dashboard').click().run()
        app._run()  # Flush stale pre-rerun elements in the Streamlit 1.50 test harness.
        self.assertFalse(app.exception)
        pending = pd.read_csv(self.root/'todo.csv')
        self.assertEqual(set(pending.case_id), {'case'})
        self.assertEqual(len(pending), 18)  # Ch1 + 18 bands, with B6 already complete.
        self.assertNotIn('Ch2_B6', pending.model.tolist())
        self.assertEqual(next(s for s in app.selectbox if s.label == 'Plot').value, 'Case catalog')
        bands = next(s for s in app.multiselect if s.label == 'Bands')
        self.assertEqual(len(bands.value), 19)
        bands.set_value(['Ch2_B6']).run()
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric if m.label in ('Complete in all selected bands', 'No retrieval in selected bands')], ['1', '0'])
        self.assertEqual(next(s for s in app.multiselect if s.label == 'Bands').value, ['Ch2_B6'])
        next(s for s in app.selectbox if s.label == 'Plot').select('Aerosol / AOD').run()
        self.assertFalse(app.exception, msg=str(app.exception))
        self.assertEqual(next(s for s in app.selectbox if s.label == 'Band for AOD–RMSE scatter').value, 'Ch2_B6')
        self.assertEqual(next(s for s in app.selectbox if s.label == 'AOD field / wavelength').value, 'aod_500')
        next(s for s in app.selectbox if s.label == 'AOD field / wavelength').select('aod_870').run()
        self.assertFalse(app.exception, msg=str(app.exception))
        next(s for s in app.multiselect if s.label == 'Bands').set_value(['Ch1', 'Ch2_B6']).run()
        next(s for s in app.selectbox if s.label == 'Band for AOD–RMSE scatter').select('Ch2_B6').run()
        self.assertFalse(app.exception, msg=str(app.exception))
        next(s for s in app.selectbox if s.label == 'Plot').select('Case catalog').run()
        next(s for s in app.multiselect if s.label == 'Bands').set_value(['Ch1']).run()
        self.assertFalse(app.exception)
        self.assertEqual([m.value for m in app.metric if m.label in ('Complete in all selected bands', 'No retrieval in selected bands')], ['0', '1'])
        for view in ['Vertical errors', 'RMSE comparisons', 'Taylor diagram', 'Information content', 'DFS vs RMSE', 'Case catalog', '985 radiance scatter']:
            next(s for s in app.selectbox if s.label == 'Plot').select(view).run()
            self.assertFalse(app.exception, msg=str(app.exception))
        next(s for s in app.selectbox if s.label == 'Manual classification').select('not_clear_sky')
        next(b for b in app.button if b.label == 'Save persistent manual override').click().run()
        app._run()  # Flush stale pre-rerun elements in the Streamlit 1.50 test harness.
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['cloud_active']['cases'].category.iloc[0], 'not_clear_sky')
        self.assertTrue(pd.read_csv(self.root/'todo.csv').empty)
        self.assertTrue(app.session_state['loaded_source']['index'].empty)
        self.assertEqual(len(list((self.root/'reviews'/'runs').glob('*/classification.csv'))), 2)
        next(b for b in app.button if b.label == 'Review images / change classification thresholds').click().run()
        app._run()
        next(n for n in app.number_input if n.key == 'class_mean').set_value(100.).run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[1].value, '1')


if __name__ == '__main__':
    unittest.main()


