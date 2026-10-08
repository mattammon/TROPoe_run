import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import xarray as xr
import dashboard_data as data
from dashboard_aod import available_fields, read_aod, match_aod, combined_errors, correlations, scatter_plot, aod_files, aod_bins, histogram_plot


class AODTests(unittest.TestCase):
    def test_histogram_endpoints_missing_rmse_and_bin_means(self):
        cases = pd.DataFrame({'case_id': ['a', 'b', 'c', 'd', 'missing'], 'aod': [0., .25, .5, 1., np.nan]})
        binned, edges = aod_bins(cases, 2)
        self.assertEqual(binned.bin.tolist(), [0, 0, 1, 1])
        pairs = pd.DataFrame({'case_id': ['a', 'b', 'c', 'd', 'a'],
                              'model': ['Ch1']*4+['Ch2_B6'], 'total_rmse': [1., 3., np.nan, 6., 8.]})
        fig = histogram_plot(binned, edges, pairs, ['Ch1', 'Ch2_B6'], 'aod_500')
        self.assertEqual(list(fig.data[0].y), [2, 2])
        np.testing.assert_allclose(fig.data[1].y, [2., 6.])
        self.assertEqual(fig.data[2].y[0], 8.)
        self.assertTrue(np.isnan(fig.data[2].y[1]))
        self.assertEqual(fig.data[1].yaxis, 'y2')
        self.assertEqual(set(binned.case_id), {'a', 'b', 'c', 'd'})

    def test_reader_matching_qc_midnight_and_missing(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            times = pd.to_datetime(['2025-01-01T23:50', '2025-01-02T00:00', '2025-01-02T00:10', '2025-01-02T00:15'])
            path = root/'sgpcsphotaodfiltqav3C1.a1.20250101.000000.nc'
            xr.Dataset({'aod_500': ('time', [.1, .3, .9, -9999.]),
                        'aod_870': ('time', [.05]*4), 'qc_aod_500': ('time', [0, 0, 1, 0]),
                        'aod_500_uncertainty': ('time', [.01]*4)}, coords={'time': times}).to_netcdf(path)
            self.assertEqual(available_fields(data.signature(path)), ['aod_500', 'aod_870'])
            samples = read_aod(data.signature(path), 'aod_500', True)
            cases = pd.DataFrame({'case_id': ['midnight', 'missing'],
                                  'sounding_time': pd.to_datetime(['2025-01-02T00:00Z', '2025-01-02T12:00Z'])})
            self.assertEqual(aod_files(root, 'sgpcsphotaodfiltqav3C1.a1', cases, 30), [path])
            matched = match_aod(cases, pd.concat([samples, samples]), 30)
            self.assertAlmostEqual(matched.aod.iloc[0], .2)
            self.assertEqual(matched.aod_samples.tolist(), [2, 0])
            self.assertTrue(np.isnan(matched.aod.iloc[1]))
            self.assertEqual(read_aod(data.signature(path), 'aod_500', False).aod.notna().sum(), 3)
            empty = pd.DataFrame(columns=['time', 'aod', 'file'])
            self.assertTrue(match_aod(cases, empty, 30).aod.isna().all())

    def test_combined_rmse_scales_regression_and_unavailable_bands(self):
        cases, _, profiles, observations = data.demo_data()
        cases = cases.iloc[:4].copy()
        models = ['Ch1', 'Ch2_B1', 'Ch2_B18']
        for i, case in enumerate(cases.case_id):
            for model, factor in [('Ch1', 1), ('Ch2_B1', 2)]:
                profiles[(case, model)]['T'] = observations[case]['T']+(i+1)*factor
                profiles[(case, model)]['q'] = observations[case]['q']+(i+1)*factor
            profiles.pop((case, 'Ch2_B18'), None)
        edges = np.linspace(.1, 3, 30)
        metrics, scales = combined_errors(cases, models, profiles, observations, edges)
        self.assertEqual(len(metrics), 8)
        first = metrics.loc[(metrics.case_id == cases.case_id.iloc[0]) & metrics.model.eq('Ch1')].iloc[0]
        self.assertAlmostEqual(first.total_rmse, np.sqrt(.5*(1/scales['T']**2+1/scales['q']**2)))
        aod = pd.DataFrame({'case_id': cases.case_id, 'sounding_time': cases.sounding_time,
                            'aod': [.1, .2, .3, .4], 'aod_samples': [2]*4})
        pairs = metrics.merge(aod, on='case_id')
        table = correlations(pairs, models)
        self.assertEqual(table['Matched cases'].tolist(), [4, 4, 0])
        np.testing.assert_allclose(table['Pearson r'].iloc[:2], 1.)
        fig = scatter_plot(pairs, 'Ch1', 'AOD 500 nm', table)
        self.assertEqual(len(fig.data), 2)
        self.assertEqual(len(fig.data[0].x), 4)
        empty, _ = combined_errors(cases, models, profiles, observations, edges, paired=True)
        self.assertTrue(empty.empty)
        empty_pairs = empty.merge(aod, on='case_id')
        self.assertEqual(correlations(empty_pairs, models)['Matched cases'].tolist(), [0, 0, 0])
        self.assertEqual(len(scatter_plot(empty_pairs, 'Ch1', 'AOD', correlations(empty_pairs, models)).data), 1)
        pairs['aod'] = .2
        self.assertTrue(correlations(pairs, models)['Pearson r'].isna().all())


if __name__ == '__main__':
    unittest.main()
