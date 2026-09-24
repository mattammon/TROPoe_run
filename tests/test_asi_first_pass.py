import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from cloud_screening import ScreenPolicy, read_asi, evaluate_case

class FirstPassTests(unittest.TestCase):
    def test_quality_and_coverage_do_not_block_single_clear_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'asi.nc'
            xr.Dataset({
                'near_zenith_percent_cloud': ('time', [0.]),
                'percent_cloud': ('time', [2.]),
                'qc_percent_cloud': ('time', [255]),
                'uncertainty_total': ('time', [99.]),
            }, coords={'time': [np.datetime64('2024-06-01T17:40')]}).to_netcdf(p)
            a = read_asi(p, ScreenPolicy(), 36.6, -97.5)
        r = evaluate_case('2024-06-01T18:00', a, pd.DataFrame(), ScreenPolicy())
        self.assertEqual(r['category'], 'clear_sky')
        self.assertFalse(r['evidence']['asi']['context']['adequate'])

    def case(self, z, total, valid=True, offsets=None):
        n=len(z)
        times=[pd.Timestamp('2024-06-01T18:00')+pd.Timedelta(minutes=i) for i in (offsets or [0]*n)]
        a=pd.DataFrame({'time':times,'zenith':z,'total':total,'valid':valid,'file':'a.nc'})
        return evaluate_case('2024-06-01T18:00',a,pd.DataFrame(),ScreenPolicy())

    def test_clear_wins_over_clouds_and_duplicate_conflicts(self):
        self.assertEqual(self.case([0,90],[0,90])['category'],'clear_sky')

    def test_limits_must_pass_on_same_sample(self):
        self.assertNotEqual(self.case([0,1],[50,0])['category'],'clear_sky')

    def test_rejected_solar_angle_missing_values_and_outside_window(self):
        self.assertNotEqual(self.case([0],[0],valid=False)['category'],'clear_sky')
        self.assertNotEqual(self.case([np.nan],[0])['category'],'clear_sky')
        self.assertNotEqual(self.case([-9999],[0])['category'],'clear_sky')
        self.assertNotEqual(self.case([0],[0],offsets=[31])['category'],'clear_sky')
