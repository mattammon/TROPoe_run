"""Diagnostics expose rejection causes without leaking ARM credentials."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import xarray as xr
from arm_download import ARMClient, CatalogError
from cloud_screening import ScreenPolicy, read_asi, window_stats

class LoggingTests(unittest.TestCase):
    def test_missing_qc_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'asi.nc'
            xr.Dataset({'near_zenith_percent_cloud': ('time', [0., 0., 0.]),
                        'percent_cloud': ('time', [0., 0., 0.])},
                       coords={'time': pd.date_range('2024-06-01T18:00', periods=3, freq='1min')}).to_netcdf(path)
            with self.assertLogs('cloud_screening', level='INFO') as logs:
                frame = read_asi(path, ScreenPolicy(asi_first_pass=False, asi_require_qc=True), 36.6, -97.5)
            self.assertFalse(frame.valid.any())
            output = '\n'.join(logs.output)
            for message in ('required QC field qc_percent_cloud MISSING', 'no recognized zenith QC or uncertainty', 'NO VALID OBSERVATIONS'):
                self.assertIn(message, output)

    def test_empty_window_records_all_failed_requirements(self):
        start = pd.Timestamp('2024-06-01T18:00')
        stats, _ = window_stats(pd.DataFrame(), start, start+pd.Timedelta(minutes=60), ['radiance'], ScreenPolicy(asi_first_pass=False))
        self.assertFalse(stats['adequate'])
        for cause in ('valid_samples=', 'coverage=', 'max_gap='):
            self.assertIn(cause, stats['adequacy_failures'])

    def test_network_exception_does_not_log_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict('os.environ', {'ARM_USERNAME': 'private-user', 'ARM_TOKEN': 'private-token'}):
                client = ARMClient()
            with patch('arm_download.urlopen', side_effect=RuntimeError('secret URL private-token')):
                with self.assertLogs('arm_download', level='INFO') as logs:
                    with self.assertRaises(CatalogError) as exc:
                        client.download('test', '2024-01-01', '2024-01-02', tmp)
            output = '\n'.join(logs.output)+str(exc.exception)
            self.assertNotIn('private-token', output)
            self.assertNotIn('private-user', output)
