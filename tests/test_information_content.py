"""Scientific and workflow regression tests; no network or real data required."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import warnings
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import matplotlib
matplotlib.use('Agg')
import numpy as np
import xarray as xr

from information_content import read_information, native_edges, remap_dfs, information_depth
from PLOT_INFORMATION import plot_information_profiles
from compile_retrieval_data import Aggregate_Retrievals


def dataset(kernel=True, cumulative=True):
    z = np.array([0., 0.5, 1.5, 3., 4.])
    # Constant native density: T=1 DFS/km, q=0.5 DFS/km.
    t = np.diff(native_edges(z))
    q = t/2
    n = len(z)
    ds = xr.Dataset(coords={'time': np.array(['2025-01-01T12:00', '2025-01-01T12:10'], dtype='datetime64[ns]'),
                            'height': z})
    ds.height.attrs['units'] = 'km'
    for name in ('temperature', 'waterVapor', 'dewpt', 'pressure'):
        ds[name] = (('time', 'height'), np.ones((2, n)))
    ds['lwp'] = ('time', [0., 0.])
    ds['sigma_lwp'] = ('time', [0.1, 0.1])
    ds['qc_flag'] = ('time', [0, 0])
    if kernel:
        a = np.diag(np.r_[t, q, 0.9])
        # Off-diagonal cross-talk must not accidentally count as diagonal DFS.
        a[0, n] = 8.
        ds['Akernal'] = (('time', 'arb_dim1', 'arb_dim2'), np.stack([a, a/2]))
    if cumulative:
        ds['cdfs_temperature'] = (('time', 'height'), np.stack([np.cumsum(t), np.cumsum(t/2)]))
        ds['cdfs_waterVapor'] = (('time', 'height'), np.stack([np.cumsum(q), np.cumsum(q/2)]))
    return ds


class InformationTests(unittest.TestCase):
    def test_raw_kernel_order_time_and_trace(self):
        info = read_information(dataset(), time_index=1)
        self.assertEqual(info['variables']['T']['source'], 'Akernal')
        self.assertAlmostEqual(info['variables']['T']['dfs_level'].sum(), 2.)
        self.assertAlmostEqual(info['variables']['q']['dfs_level'].sum(), 1.)
        self.assertIn('12:10', info['time'])

    def test_cdfs_fallback_and_source_override(self):
        raw = read_information(dataset())
        fallback = read_information(dataset(kernel=False))
        forced = read_information(dataset(), source='cdfs')
        for var in ('T', 'q'):
            np.testing.assert_allclose(raw['variables'][var]['dfs_level'], fallback['variables'][var]['dfs_level'])
            np.testing.assert_allclose(raw['variables'][var]['dfs_level'], forced['variables'][var]['dfs_level'])
        self.assertEqual(fallback['variables']['q']['source'], 'cdfs_waterVapor')

    def test_kernel_nonpositive_is_not_replaced_by_cdfs(self):
        ds = dataset()
        ds.Akernal.values[0, 0, 0] = -0.1
        ds.Akernal.values[0, 1, 1] = 0.
        info = read_information(ds)
        self.assertEqual(info['variables']['T']['dfs_level'][0], -0.1)
        self.assertEqual(info['variables']['T']['dfs_level'][1], 0.)
        self.assertTrue(info['variables']['T']['has_negative_dfs'])
        self.assertTrue(np.isnan(information_depth(info['height_km'], info['variables']['T']['dfs_level'], 3., 0.9)))

    def test_missing_invalid_and_no_model(self):
        missing = read_information(dataset(kernel=False, cumulative=False))
        self.assertEqual(set(missing['errors']), {'T', 'q'})
        ds = dataset()
        ds.Akernal.values[0, 0, 0] = np.nan
        info = read_information(ds)
        self.assertIn('T', info['errors'])
        self.assertIn('q', info['variables'])
        self.assertEqual(set(read_information(dataset(), no_model=True)['errors']), {'T', 'q'})
        ds = dataset().rename({'Akernal': 'Akernal_no_model'})
        self.assertEqual(read_information(ds, no_model=True)['variables']['T']['source'], 'Akernal_no_model')

    def test_missing_units_default_and_metre_conversion(self):
        ds = dataset()
        ds = ds.assign_coords(height=ds.height.values*1000)
        ds.height.attrs['units'] = 'm'
        np.testing.assert_allclose(read_information(ds)['height_km'], dataset().height.values)
        ds.height.attrs['units'] = 'feet'
        self.assertIn('T', read_information(ds)['errors'])

    def test_conservative_remap_different_nonuniform_grids(self):
        target = np.array([0., 0.25, 0.9, 2., 3.])
        for z in (np.array([0., 0.5, 1.5, 3., 4.]), np.array([0., 1., 2., 4.])):
            local = np.diff(native_edges(z))
            result = remap_dfs(z, local, target)
            np.testing.assert_allclose(result['density'], 1.)
            np.testing.assert_allclose(result['cumulative'], target)
            self.assertAlmostEqual(result['dfs_bin'].sum(), 3.)
            full = remap_dfs(z, local, np.array([0., 4.]))
            self.assertAlmostEqual(full['dfs_bin'].sum(), local.sum())
            self.assertAlmostEqual(information_depth(z, local, 3., 0.9), 2.7)

    def test_no_extrapolation_zero_information(self):
        z = np.array([0., 1., 2.])
        result = remap_dfs(z, np.zeros(3), [0., 1., 2., 3.])
        np.testing.assert_array_equal(result['density'][:2], [0., 0.])
        self.assertTrue(np.isnan(result['density'][-1]))
        self.assertTrue(np.isnan(information_depth(z, np.zeros(3), 2., 0.9)))
        with self.assertRaises(ValueError):
            remap_dfs([0., 1., 1.], np.ones(3), [0., 1.])

    def test_paired_selection_sources_and_plot_outputs(self):
        records = {}
        for case in ('good', 'missing', 'mixed'):
            records[case] = {
                'Ch1': {'information': read_information(dataset())},
                'Ch2_B17': {'information': read_information(dataset(kernel=case != 'mixed'))},
            }
        records['missing']['Ch2_B17']['information'] = read_information(dataset(kernel=False, cumulative=False))
        ev = SimpleNamespace(good_dts=list(records), profile_data={'retrieval_snd': records},
                             information_source='auto', information_no_model=False)
        with tempfile.TemporaryDirectory() as directory:
            result = plot_information_profiles(ev, ['Ch1', 'Ch2_B17'], output_dir=directory, per_case=True)
            self.assertEqual(set(result['summary']['case']), {'good'})
            self.assertEqual(len(result['figures']), 6)
            np.testing.assert_allclose(result['summary']['delta_dfs_vs_ch1'], 0.)
            self.assertTrue(all(p.is_file() and p.stat().st_size > 1000 for p in result['figures']))
            self.assertEqual(result['manifest'].paired.sum(), 4)
            self.assertTrue(result['manifest'].reason.str.contains('Mixed').any())
            self.assertEqual(len(matplotlib.pyplot.get_fignums()), 0)

    def test_empty_diagnostics_graceful(self):
        ev = SimpleNamespace(good_dts=['empty'], profile_data={'retrieval_snd': {'empty': {'Ch1': {}}}})
        with tempfile.TemporaryDirectory() as directory, warnings.catch_warnings(record=True) as caught:
            result = plot_information_profiles(ev, ['Ch1'], output_dir=directory)
            self.assertTrue(result['summary'].empty)
            self.assertEqual(result['figures'], [])
            self.assertEqual(len(caught), 2)

    def test_real_netcdf_loader_preserves_rmse_and_full_diagnostic_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'retrieval.nc'
            dataset().to_netcdf(path)
            obj = Aggregate_Retrievals.__new__(Aggregate_Retrievals)
            obj.max_hgt = 1.5
            obj.include_information = False
            original = obj.tropoe_profiles(path, check_lwp=True)
            obj.include_information = True
            obj.information_source = 'auto'
            obj.information_no_model = False
            enhanced = obj.tropoe_profiles(path, check_lwp=True)
            for key in ('hgt', 'T', 'Td', 'q', 'P'):
                np.testing.assert_array_equal(original[key], enhanced[key])
            self.assertEqual(len(enhanced['information']['height_km']), 5)
            self.assertEqual(len(enhanced['hgt']), 4)
            self.assertEqual(enhanced['information']['time_index'], 0)

    def test_aggregate_and_plot_workflow(self):
        import compile_retrieval_data as module
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'sonde'/'test').mkdir(parents=True)
            (root/'retrieval'/'test').mkdir(parents=True)
            sonde = xr.Dataset({'alt': ('level', [0., 500., 1500., 3000., 4000.]),
                                'tdry': ('level', [20., 17., 11., 2., -4.]),
                                'rh': ('level', [60., 60., 60., 60., 60.]),
                                'pres': ('level', [1000., 950., 850., 700., 600.])})
            sonde.alt.attrs['units'] = 'm'
            sonde.to_netcdf(root/'sonde'/'test'/'sgpsondewnpnC1.b1.20250101.120000.cdf')
            for label in ('Ch1', 'Ch2_B17'):
                dataset().to_netcdf(root/'retrieval'/'test'/f'tropoeOutput_{label}.20250101.120000.nc')
            with patch.multiple(module, SONDE_DIR=str(root/'sonde'), RETRIEVAL_DIR=str(root/'retrieval'), GROUP_NAME='test'):
                ev = Aggregate_Retrievals(3., [17], include_information=True)
                self.assertEqual(ev.good_dts, ['202501011200'])
                result = plot_information_profiles(ev, ['Ch1', 'Ch2_B17'], output_dir=root/'plots')
                self.assertEqual(len(result['summary']), 4)
                np.testing.assert_allclose(result['summary'].query('variable == "T"').layer_dfs, 3.)


if __name__ == '__main__':
    unittest.main()
