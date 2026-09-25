import unittest
from dataclasses import replace
import pandas as pd
from cloud_screening import ScreenPolicy, evaluate_case

T = pd.Timestamp('2024-06-01T18:00')

class RadianceFallbackTests(unittest.TestCase):
    def result(self, asi_kind='missing', rad_value=12., policy=None, sparse=False):
        times = pd.date_range(T-pd.Timedelta(minutes=30), T+pd.Timedelta(minutes=30), freq='1min')
        rad = pd.DataFrame({'time': times, 'valid': True, 'radiance': rad_value, 'file': 'r.nc'})
        if sparse:
            rad = rad.iloc[:1]
        asi = pd.DataFrame()
        if asi_kind != 'missing':
            value = {'clear': 0., 'cloudy': 100.}[asi_kind]
            asi = pd.DataFrame({'time': times, 'valid': True, 'zenith': value, 'total': value, 'file': 'a.nc'})
        return evaluate_case(T, asi, rad, policy or self.policy)

    def setUp(self):
        self.policy = ScreenPolicy(radiance_clear_mean_max=15., radiance_clear_std_max=1.)

    def test_uncertain_asi_uses_radiance_fallback(self):
        for strict in (False, True):
            r = self.result(policy=replace(self.policy, asi_first_pass=not strict))
            self.assertEqual(r['category'], 'clear_sky')
            self.assertEqual(r['reason'], 'asi_uncertain_radiance_clear_fallback')
            self.assertEqual(r['evidence']['asi']['state'], 'uncertain')

    def test_cloudy_asi_is_not_overridden(self):
        self.assertEqual(self.result(asi_kind='cloudy')['category'], 'not_clear_sky')

    def test_limits_and_coverage_required(self):
        for kwargs in ({'rad_value': 20.}, {'sparse': True}, {'policy': ScreenPolicy()}):
            self.assertEqual(self.result(**kwargs)['category'], 'uncertain')

    def test_explicit_both_rule_still_requires_both(self):
        self.assertEqual(self.result(policy=replace(self.policy, clear_rule='both'))['category'], 'uncertain')

    def test_clear_asi_stays_clear(self):
        self.assertEqual(self.result(asi_kind='clear', rad_value=20.)['category'], 'clear_sky')
