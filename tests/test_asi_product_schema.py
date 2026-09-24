"""ASISKYCOVER uncertainty percentages are quality evidence, not zero-only flags."""
import tempfile
import unittest
from pathlib import Path
import pandas as pd
import xarray as xr
from cloud_screening import ScreenPolicy, read_asi

class ASIProductTests(unittest.TestCase):
    def read(self, uncertainty=True, qc=False, missing_total=False):
        data = {'near_zenith_percent_cloud': ('time', [0.]*3),
                'percent_cloud': ('time', [0.]*3)}
        if uncertainty:
            data['near_zenith_uncertainty_total'] = ('time', [2., 4., 1.])
            if not missing_total:
                data['uncertainty_total'] = ('time', [3., 11., float('nan')])
        if qc:
            data['qc_percent_cloud'] = ('time', [1, 0, 0])
            data['qc_near_zenith_percent_cloud'] = ('time', [0, 0, 0])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'asi.nc'
            xr.Dataset(data, coords={'time': pd.date_range('2024-06-01T18:00', periods=3, freq='15s')}).to_netcdf(path)
            return read_asi(path, ScreenPolicy(), 36.6, -97.5)

    def test_native_percentages_without_qc(self):
        result = self.read()
        self.assertEqual(result.valid.tolist(), [True, False, False])
        self.assertEqual(result.uncertainty_fields.iloc[0], 'near_zenith_uncertainty_total,uncertainty_total')

    def test_existing_qc_still_vetoes(self):
        self.assertFalse(self.read(qc=True).valid.any())

    def test_missing_quality_never_assumed_good(self):
        self.assertFalse(self.read(uncertainty=False).valid.any())
        self.assertFalse(self.read(missing_total=True).valid.any())

    def test_uncertainty_cannot_be_used_as_qc(self):
        with self.assertRaisesRegex(ValueError, 'not an uncertainty'):
            ScreenPolicy(asi_total_qc='uncertainty_total')
