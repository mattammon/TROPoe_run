import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

from sounding_pwv import integrate_pwv, sounding_pwv, catalog_pwv
from dashboard_data import filter_radiance_cases


def sonde(path, top=50, pa=False, fraction=False):
    p = np.linspace(1000, top, 101)
    t = np.full(len(p), 20.)
    r = .01
    e = r*p/(.622+r)
    rh = e/(6.112*np.exp(17.67*20/(20+243.5)))*100
    ds = xr.Dataset(dict(pres=('level', p*(100 if pa else 1), {'units': 'Pa' if pa else 'hPa'}),
                         tdry=('level', t+(273.15 if pa else 0), {'units': 'K' if pa else 'degC'}),
                         rh=('level', rh/(100 if fraction else 1), {'units': 'fraction' if fraction else '%'}),
                         alt=('level', np.arange(len(p))*100., {'units': 'm'})))
    ds.to_netcdf(path)


class PWVTests(unittest.TestCase):
    def test_known_column_and_order(self):
        expected = .01/1.01*95000/9.80665
        self.assertAlmostEqual(integrate_pwv([1000, 50], [10, 10]), expected)
        self.assertAlmostEqual(integrate_pwv([50, 1000], [10, 10]), expected)
        with self.assertRaises(ValueError):
            integrate_pwv([1000, 1000], [10, 10])

    def test_units_and_shallow_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp)/'a.nc', Path(tmp)/'b.nc'
            sonde(a)
            sonde(b, pa=True, fraction=True)
            first, second = sounding_pwv(a), sounding_pwv(b)
            self.assertEqual(first['pwv_status'], 'ok')
            self.assertAlmostEqual(first['pwv_mm'], .01/1.01*95000/9.80665)
            self.assertAlmostEqual(first['pwv_mm'], second['pwv_mm'])
            sonde(a, top=500)
            partial = sounding_pwv(a)
            self.assertEqual(partial['pwv_status'], 'partial')
            self.assertTrue(np.isnan(partial['pwv_mm']))
            self.assertGreater(partial['pwv_observed_mm'], 0)

    def test_cache_reuses_unchanged_and_reads_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root/'sounding.nc'
            sonde(file)
            cases = pd.DataFrame([dict(case_id='one', sounding_file=str(file)), dict(case_id='missing', sounding_file='missing.nc')])
            out = root/'pwv.csv'
            first = catalog_pwv(cases, root/'manifest.csv', '', out)
            self.assertEqual(first.pwv_status.tolist(), ['ok', 'error'])
            with patch('sounding_pwv.sounding_pwv', side_effect=AssertionError('Should use cache')):
                second = catalog_pwv(cases, root/'manifest.csv', '', out)
            self.assertAlmostEqual(first.pwv_mm.iloc[0], second.pwv_mm.iloc[0])
            sonde(file, top=500)
            third = catalog_pwv(cases, root/'manifest.csv', '', out)
            self.assertEqual(third.pwv_status.iloc[0], 'partial')
            self.assertEqual(out.stat().st_mode & 0o777, 0o777)

    def test_gaps_and_descent(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'sounding.nc'
            sonde(file)
            with xr.open_dataset(file) as opened:
                ds = opened.load()
            ds['rh'][20:40] = np.nan
            ds.to_netcdf(file)
            self.assertEqual(sounding_pwv(file)['pwv_status'], 'partial')
            sonde(file)
            with xr.open_dataset(file) as opened:
                ds = opened.load()
            ds = xr.concat([ds, ds.isel(level=slice(None, None, -1))], dim='level')
            ds.to_netcdf(file)
            self.assertAlmostEqual(sounding_pwv(file)['pwv_mm'], .01/1.01*95000/9.80665)

    def test_filter_intersection_and_empty_selection(self):
        cases = pd.DataFrame(dict(case_id=['a','b','c','d'], sounding_time=pd.to_datetime([
            '2024-01-01T01:00Z','2024-07-01T13:00Z','2024-07-02T13:00Z','2024-07-03T19:00Z']),
            category=['clear_sky']*4, asi_state=['clear_sky','clear_sky','uncertain','clear_sky'],
            radiance_state=['clear_sky']*4, pwv_mm=[10,30,np.nan,45]))
        filtered = filter_radiance_cases(cases, ['Summer (JJA)'], ['12–18 UTC'], ['Clear sky'], (20,40))
        self.assertEqual(filtered.case_id.tolist(), ['b'])
        self.assertTrue(filter_radiance_cases(cases, seasons=[]).empty)
        self.assertEqual(filter_radiance_cases(cases, pwv_range=(30,30)).case_id.tolist(), ['b'])
        self.assertEqual(filter_radiance_cases(cases, pwv_range=(30,30), include_missing_pwv=True).case_id.tolist(), ['b','c'])
        self.assertEqual(len(cases), 4)

    def test_streamlit_filters(self):
        from streamlit.testing.v1 import AppTest
        script = '''
import pandas as pd
import streamlit as st
from dashboard_setup import plot_filter_controls
frame = pd.DataFrame(dict(case_id=['winter','summer'], sounding_time=pd.to_datetime(['2024-01-01T01:00Z','2024-07-01T13:00Z']), category=['clear_sky']*2, asi_state=['clear_sky','uncertain'], radiance_state=['clear_sky']*2, pwv_mm=[10.,40.]))
filtered = plot_filter_controls(frame, None, 'test')
st.text(','.join(filtered.case_id))
'''
        app = AppTest.from_string(script).run(timeout=30)
        self.assertFalse(app.exception)
        app.multiselect(key='test_seasons').set_value(['Summer (JJA)']).run()
        self.assertEqual(app.text[0].value, 'summer')
        app.multiselect(key='test_asi_filter').set_value(['Clear sky']).run()
        self.assertEqual(app.text[0].value, '')
        self.assertFalse(app.exception)
        app.multiselect(key='test_asi_filter').set_value(['Uncertain']).run()
        app.checkbox(key='test_pwv_enabled').check().run()
        app.number_input(key='test_pwv_max').set_value(30.).run()
        self.assertEqual(app.text[0].value, '')
        self.assertFalse(app.exception)

    def test_review_page_computes_pwv_and_handles_no_matches(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'sonde.nc'
            sonde(path)
            script = """
import pandas as pd
import streamlit as st
import dashboard_setup as setup
from dashboard_classification import ClassificationRules
frame = pd.DataFrame([dict(case_id='summer', sounding_time=pd.Timestamp('2024-07-01T13:00Z'), sounding_file=SONDE, category='clear_sky', automatic_category='clear_sky', classification_source='thresholds', asi_state='clear_sky', radiance_state='clear_sky', radiance_core_radiance_mean=5., radiance_core_radiance_std=.1)])
source = dict(master=MASTER, master_hash='test', sonde_root='', output=ROOT, cases=frame)
setup.inspect_case = lambda frame, *args: st.text('Inspect: '+','.join(frame.case_id))
setup.review_plot(frame, ClassificationRules(), '', None, source=source)
""".replace('SONDE', repr(str(path))).replace('MASTER', repr(str(Path(tmp)/'master.csv'))).replace('ROOT', repr(tmp))
            app = AppTest.from_string(script).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.text[0].value, 'Inspect: summer')
            self.assertEqual(len(list(Path(tmp).glob('sounding_pwv_*.csv'))), 1)
            app.multiselect(key='classification_seasons').set_value([]).run()
            self.assertFalse(app.exception)
            self.assertTrue(any('No cases match' in info.value for info in app.info))


if __name__ == '__main__':
    unittest.main()
