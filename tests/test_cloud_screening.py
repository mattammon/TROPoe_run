"""Synthetic policy, NetCDF-reader, and non-destructive workflow regression tests."""
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

from arm_download import ARMClient, CatalogError
from cloud_screening import (ScreenPolicy, dataset_times, evaluate_case, read_asi,
                             read_radiance, selected_sounding_files, solar_zenith)
from get_sgp_data import SGP_DATA


T = pd.Timestamp('2024-06-01T18:00:00')


def frame(kind, center=T, value=0.):
    times = pd.date_range(center-pd.Timedelta(minutes=30), center+pd.Timedelta(minutes=30), freq='1min')
    d = {'time': times, 'valid': True, 'file': 'synthetic.nc', 'qc_fields': 'synthetic'}
    d.update({'zenith': value, 'total': value, 'uncertainty_fields': 'synthetic'} if kind == 'asi'
             else {'radiance': value, 'actual_wavenumber': 985.})
    return pd.DataFrame(d)


def asi_nc(path, center=T, value=0., qc=True):
    f = frame('asi', center, value)
    ds = xr.Dataset({name: ('time', f[field]) for name, field in
                     [('near_zenith_percent_cloud', 'zenith'), ('percent_cloud', 'total')]},
                    coords={'time': f.time.to_numpy()})
    if qc:
        for name in ('near_zenith_percent_cloud', 'percent_cloud'):
            ds['qc_'+name] = ('time', np.zeros(len(f), dtype=int))
    ds.to_netcdf(path)


def rad_nc(path, center=T, wave=985., units='mW/(m^2 sr cm^-1)'):
    f = frame('radiance', center, 12.)
    ds = xr.Dataset({'mean_rad': (('time', 'wnum'), np.full((len(f), 2), 12.), {'units': units}),
                     'missingDataFlag': ('time', np.zeros(len(f), dtype=int))},
                    coords={'time': f.time.to_numpy(), 'wnum': [wave, wave+1]})
    ds.wnum.attrs['units'] = 'cm-1'
    ds.to_netcdf(path)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.p = ScreenPolicy(asi_first_pass=False)
        self.empty = pd.DataFrame()

    def result(self, asi=None, rad=None, policy=None, time=T):
        return evaluate_case(time, asi if asi is not None else self.empty,
                             rad if rad is not None else self.empty, policy or self.p)

    def test_missing_evidence_never_clear(self):
        self.assertEqual(self.result()['category'], 'uncertain')

    def test_clear_context(self):
        r = self.result(asi=frame('asi'), rad=frame('radiance', value=20))
        self.assertEqual(r['category'], 'clear_sky')
        self.assertEqual(r['evidence']['radiance']['reason'], 'radiance_thresholds_not_configured')

    def test_repeated_cloud_detection_and_borderline(self):
        self.assertEqual(self.result(asi=frame('asi', value=80))['category'], 'not_clear_sky')
        self.assertEqual(self.result(asi=frame('asi', value=2))['category'], 'uncertain')
        a = frame('asi'); a.loc[30, 'zenith'] = 50
        self.assertEqual(self.result(asi=a)['category'], 'uncertain')
        a.loc[31, 'zenith'] = 50
        self.assertEqual(self.result(asi=a)['category'], 'not_clear_sky')

    def test_clouds_only_outside_core_are_uncertain(self):
        a = frame('asi'); a.loc[:5, 'total'] = 80
        self.assertEqual(self.result(asi=a)['category'], 'uncertain')

    def test_dense_burst_and_long_gap_not_clear(self):
        a = frame('asi').iloc[:10].copy()
        a.time = pd.date_range(T, periods=10, freq='1s')
        self.assertEqual(self.result(asi=a)['category'], 'uncertain')
        a = frame('asi').drop(index=range(10, 15))
        # Exercise a strict gap limit independently of operational defaults.
        self.assertEqual(self.result(asi=a, policy=replace(self.p, max_gap_seconds=180))['category'], 'uncertain')

    def test_bad_quality_excluded(self):
        a = frame('asi'); a.valid = False
        self.assertEqual(self.result(asi=a)['category'], 'uncertain')

    def test_radiance_rule_and_conflict(self):
        p = replace(self.p, clear_rule='radiance', radiance_clear_mean_max=15,
                    radiance_clear_std_max=1, radiance_cloud_mean_min=30)
        self.assertEqual(self.result(rad=frame('radiance', value=12), policy=p)['category'], 'clear_sky')
        self.assertEqual(self.result(rad=frame('radiance', value=20), policy=p)['category'], 'uncertain')
        self.assertEqual(self.result(rad=frame('radiance', value=40), policy=p)['category'], 'not_clear_sky')
        r = self.result(asi=frame('asi'), rad=frame('radiance', value=40), policy=p)
        self.assertEqual((r['category'], r['reason']), ('uncertain', 'conflicting_instrument_evidence'))
        self.assertEqual(self.result(asi=frame('asi'), policy=replace(p, clear_rule='both'))['category'], 'uncertain')

    def test_duplicates_do_not_increase_coverage_or_hide_disagreement(self):
        a = frame('asi')
        r = self.result(asi=pd.concat([a, a], ignore_index=True))
        self.assertEqual(r['evidence']['asi']['context']['n_valid'], len(a))
        b = a.iloc[[30]].copy(); b.zenith = 90
        r = self.result(asi=pd.concat([a, b], ignore_index=True))
        self.assertEqual(r['reason'], 'conflicting_duplicate_observations')

    def test_midnight_rounding_and_seconds(self):
        r = self.result(time=pd.Timestamp('2024-06-01T23:58:40'))
        self.assertEqual(r['retrieval_time'], '2024-06-02T00:00:00')
        self.assertEqual(r['windows']['context'][1], '2024-06-02T00:28:40')
        r = self.result(time=pd.Timestamp('2024-06-01T18:07:59'))
        self.assertEqual(r['retrieval_time'], '2024-06-01T18:00:00')

    def test_invalid_policy(self):
        for overrides in [dict(clear_rule='radiance'), dict(min_coverage=0),
                          dict(context_minutes=10), dict(asi_cloud_total_min=5)]:
            with self.assertRaises(ValueError):
                ScreenPolicy(**overrides)


class ReaderTests(unittest.TestCase):
    def test_time_decoding(self):
        ds = xr.Dataset({'base_time': xr.DataArray(np.datetime64('2024-06-01T18:00:00', 'ns')),
                         'time_offset': ('obs', [0., 60.], {'units': 'seconds'})})
        self.assertEqual(dataset_times(ds)[1], T+pd.Timedelta(minutes=1))
        ds['base_time'] = xr.DataArray(T.timestamp(), attrs={'units': 'seconds since 1970-01-01 00:00:00'})
        self.assertEqual(dataset_times(ds)[0], T)

    def test_asi_quality_and_night(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'a.nc'
            asi_nc(p)
            self.assertTrue(read_asi(p, ScreenPolicy(asi_first_pass=False), 36.60611, -97.484726).valid.all())
            asi_nc(p, qc=False)
            self.assertFalse(read_asi(p, ScreenPolicy(asi_first_pass=False), 36.60611, -97.484726).valid.any())
            asi_nc(p, center=pd.Timestamp('2024-06-01T06:00:00'))
            self.assertFalse(read_asi(p, ScreenPolicy(asi_first_pass=False), 36.60611, -97.484726).valid.any())
        self.assertGreater(solar_zenith([pd.Timestamp('2024-06-01T06:00:00')], 36.60611, -97.484726)[0], 90)

    def test_radiance_spectral_selection_units_and_qc(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'r.nc'; rad_nc(p, wave=984.9)
            f = read_radiance(p, ScreenPolicy(asi_first_pass=False))
            self.assertTrue(f.valid.all()); self.assertTrue((f.actual_wavenumber == 984.9).all())
            self.assertAlmostEqual(f.radiance.mean(), 12.)
            rad_nc(p, units='W/(m^2 sr cm^-1)')
            self.assertAlmostEqual(read_radiance(p, ScreenPolicy(asi_first_pass=False)).radiance.mean(), 12000.)
            rad_nc(p, wave=990.)
            with self.assertRaises(ValueError): read_radiance(p, ScreenPolicy(asi_first_pass=False))
            rad_nc(p, units='Kelvin')
            with self.assertRaises(ValueError): read_radiance(p, ScreenPolicy(asi_first_pass=False))


class DownloadTests(unittest.TestCase):
    def client(self):
        with patch.dict('os.environ', {'ARM_USERNAME': 'test-user', 'ARM_TOKEN': 'test-secret'}):
            return ARMClient()

    def test_atomic_download_existing_and_invalid_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample = root/'sample.nc'
            xr.Dataset({'value': ('time', [1.])}).to_netcdf(sample)
            payload = sample.read_bytes()
            name = 'sgpsondewnpnC1.b1.20240601.180000.cdf'
            catalog = json.dumps({'status': 'success', 'files': [name]}).encode()
            client = self.client()
            with patch('arm_download.urlopen', side_effect=[io.BytesIO(catalog), io.BytesIO(payload)]):
                records = client.download('sgpsondewnpnC1.b1', '2024-06-01', '2024-06-01', root/'out')
            self.assertEqual(records[0]['status'], 'downloaded')
            self.assertEqual((root/'out'/name).read_bytes(), payload)
            with patch('arm_download.urlopen', return_value=io.BytesIO(catalog)) as fetch:
                self.assertEqual(client.download('sgpsondewnpnC1.b1', '', '', root/'out')[0]['status'], 'existing')
                self.assertEqual(fetch.call_count, 1)
            with patch('arm_download.urlopen', side_effect=[io.BytesIO(catalog), io.BytesIO(b'<html>Unavailable</html>')]):
                records = client.download('sgpsondewnpnC1.b1', '', '', root/'bad')
            self.assertEqual(records[0]['status'], 'unavailable')
            self.assertEqual(list((root/'bad').iterdir()), [])

    def test_bad_catalog_rejected_without_exposing_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            for payload in [{'status': 'failure', 'files': []},
                            {'status': 'success', 'files': ['../bad.nc']}]:
                with patch('arm_download.urlopen', return_value=io.BytesIO(json.dumps(payload).encode())):
                    with self.assertRaises(CatalogError): self.client().download('sgpsondewnpnC1.b1', '', '', tmp)
            with patch('arm_download.urlopen', side_effect=RuntimeError('url?user=test-user:test-secret')):
                with self.assertRaises(CatalogError) as caught:
                    self.client().download('sgpsondewnpnC1.b1', '', '', tmp)
                self.assertNotIn('test-secret', str(caught.exception))


class WorkflowTests(unittest.TestCase):
    def test_inventory_categories_rerun_and_manifest_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dirs = {key: root/key for key in SGP_DATA.streams}
            for d in dirs.values(): (d/'ALL').mkdir(parents=True)
            for day, value in [('20240601', 0.), ('20240602', 80.)]:
                name = SGP_DATA.streams['sonde']+f'.{day}.180000.cdf'
                xr.Dataset({'temp': ('time', [20.])}, coords={'time': [pd.Timestamp(day+'T18:00:00')]}).to_netcdf(dirs['sonde']/'ALL'/name)
                asi_nc(dirs['asi']/'ALL'/(SGP_DATA.streams['asi']+f'.{day}.000000.nc'), center=pd.Timestamp(day+'T18:00:00'), value=value)
                rad_nc(dirs['ch1']/'ALL'/(SGP_DATA.streams['ch1']+f'.{day}.000000.cdf'), center=pd.Timestamp(day+'T18:00:00'))
            bad = dirs['sonde']/'ALL'/(SGP_DATA.streams['sonde']+'.20240603.180000.cdf')
            bad.write_bytes(b'broken source remains untouched')
            excluded = dirs['sonde']/'ALL'/(SGP_DATA.streams['sonde']+'.20240701.180000.cdf')
            excluded.write_bytes(b'out of range')
            # Duplicate legacy folder link must not create an extra case.
            (dirs['sonde']/'legacy').mkdir()
            source = next((dirs['sonde']/'ALL').glob('*20240601*'))
            (dirs['sonde']/'legacy'/source.name).symlink_to(source)
            original = {p: p.read_bytes() for p in root.glob('*/ALL/*')}
            obj = SGP_DATA('20240601', '2024-06-03', directories=dirs)
            first = obj.screen_cases(offline=True, output_dir=root/'runs')
            second = obj.screen_cases(offline=True, output_dir=root/'runs')
            self.assertNotEqual(first, second)
            df = pd.read_csv(first)
            self.assertEqual(df.category.tolist(), ['clear_sky', 'not_clear_sky', 'uncertain'])
            self.assertEqual(len(selected_sounding_files(dirs['sonde'], 'legacy', first)), 1)
            self.assertEqual(len(list(first.parent.glob('clear_sky/*'))), 1)
            for p, contents in original.items(): self.assertEqual(p.read_bytes(), contents)
            meta = json.loads((first.parent/'metadata.json').read_text())
            self.assertEqual(meta['scope'], 'locally_available_soundings')
            self.assertEqual(meta['counts'], dict(clear_sky=1, not_clear_sky=1, uncertain=1))
            with self.assertRaises(FileNotFoundError): selected_sounding_files(dirs['sonde'], 'legacy', root/'absent.csv')

    def test_failed_catalog_aborts_sounding_inventory(self):
        class Client:
            def download(self, *args): raise CatalogError('synthetic failure')
        with tempfile.TemporaryDirectory() as tmp:
            dirs = {key: Path(tmp)/key for key in SGP_DATA.streams}
            with self.assertRaises(CatalogError):
                SGP_DATA('20240601', '20240602', directories=dirs, client=Client()).screen_cases(output_dir=Path(tmp)/'runs')
            self.assertFalse((Path(tmp)/'runs').exists())

    def test_missing_catalog_sounding_is_retained_as_uncertain(self):
        class Client:
            def download(self, stream, start, end, directory):
                if 'sonde' in stream:
                    name = stream+'.20240601.180000.cdf'
                    return [{'filename': name, 'path': str(directory/name), 'status': 'unavailable'}]
                raise CatalogError('synthetic failure')
        with tempfile.TemporaryDirectory() as tmp:
            dirs = {key: Path(tmp)/key for key in SGP_DATA.streams}
            manifest = SGP_DATA('20240601', '20240601', directories=dirs, client=Client()).screen_cases(output_dir=Path(tmp)/'runs')
            df = pd.read_csv(manifest)
            self.assertEqual(df.category.tolist(), ['uncertain'])
            with self.assertRaises(FileNotFoundError): selected_sounding_files(dirs['sonde'], 'legacy', manifest, 'uncertain')


if __name__ == '__main__':
    unittest.main()
