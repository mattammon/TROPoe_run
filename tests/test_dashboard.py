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
        self.z = np.linspace(0, 3, 31)
        self.times = pd.date_range('2025-01-01T12:00', periods=2, freq='15min')
        # Filename time deliberately differs from BOTH actual record times.
        self.path = self.root/'tropoeOutput_Ch2_B6.20250101.115500.nc'
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

    def test_streamlit_radiance_controls(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'TROPoe_APP.py'), default_timeout=60).run()
        case_selector = next(s for s in app.selectbox if s.label == 'Case')
        self.assertIn('UTC', case_selector.options[0])
        self.assertNotIn('DEMO_', case_selector.options[0])
        next(s for s in app.selectbox if s.label == 'Plot').select('985 radiance scatter').run()
        self.assertFalse(app.exception)
        for group in ['Season', 'Month', 'Time of day (UTC)', 'Classification']:
            next(s for s in app.selectbox if s.label == 'Group cases by').select(group).run()
            self.assertFalse(app.exception)
        next(s for s in app.multiselect if s.label == 'Visible categories').set_value([]).run()
        self.assertTrue(any('No cases with finite' in i.value for i in app.info))
        next(s for s in app.multiselect if s.label == 'Visible categories').set_value(['Clear sky']).run()
        next(c for c in app.checkbox if c.label == 'Limit 985 radiance mean').set_value(True)
        next(c for c in app.checkbox if c.label == 'Limit 985 radiance standard deviation').set_value(True)
        next(b for b in app.button if b.label == 'Apply filters').click().run()
        next(c for c in app.checkbox if c.label == 'Include cases outside radiance limits').set_value(False).run()
        self.assertFalse(app.exception)
        # A nonexistent context window must give a helpful message, not crash.
        next(s for s in app.selectbox if s.label == 'Screening window').select('context')
        next(b for b in app.button if b.label == 'Apply filters').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('no context radiance' in w.value for w in app.warning))
        # No band selection is necessary for manifest-only radiance diagnostics.
        next(s for s in app.selectbox if s.label == 'Screening window').select('core')
        next(s for s in app.multiselect if s.label == 'Bands').set_value([])
        next(b for b in app.button if b.label == 'Apply filters').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any(s.label == 'Group cases by' for s in app.selectbox))

    def test_streamlit_demo_and_real_loader(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'TROPoe_APP.py'), default_timeout=60).run()
        self.assertFalse(app.exception)
        views = ['RMSE comparisons', 'Vertical errors', 'Taylor diagram', 'Information content', 'DFS vs RMSE', 'Cloud diagnostics', 'Case catalog']
        for view in views:
            next(s for s in app.selectbox if s.label == 'Plot').select(view).run()
            self.assertFalse(app.exception, msg=str(app.exception))
        next(s for s in app.multiselect if s.label == 'Bands').set_value(['Ch2_B6'])
        next(b for b in app.button if b.label == 'Apply filters').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.metric[1].value, '48')
        next(c for c in app.checkbox if c.label == 'Limit 985 radiance mean').set_value(True)
        next(b for b in app.button if b.label == 'Apply filters').click().run()
        self.assertFalse(app.exception)
        demo_cases = data.demo_data()[0]
        expected_count = int((demo_cases.radiance_core_radiance_mean <= 7).sum())
        self.assertEqual(app.metric[0].value, str(expected_count))
        next(s for s in app.selectbox if s.label == 'Variable').select('Td').run()
        next(s for s in app.selectbox if s.label == 'Plot').select('Information content').run()
        self.assertFalse(app.exception)
        self.assertTrue(any('DFS diagnostics' in i.value for i in app.info))
        next(s for s in app.selectbox if s.label == 'Variable').select('T').run()
        next(r for r in app.radio if r.label == 'Source').set_value('Retrieval files').run()
        next(t for t in app.text_input if t.label == 'Screening manifest CSV').set_value(str(self.manifest))
        next(t for t in app.text_input if t.label == 'Retrieval directory').set_value(str(self.root))
        next(b for b in app.button if b.label == 'Load / refresh data').click().run()
        self.assertFalse(app.exception, msg=str(app.exception))
        self.assertEqual(app.metric[1].value, '1')
        self.assertEqual(app.metric[2].value, '1')
        self.assertEqual(app.metric[3].value, '1')


if __name__ == '__main__':
    unittest.main()
