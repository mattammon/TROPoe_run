import csv
import json
from unittest.mock import patch
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from catalog_retrievals import scan, expected_cases, main

class CatalogTests(unittest.TestCase):
    def test_inventory_and_expected_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            t=pd.date_range('2024-06-01T18:00',periods=2,freq='15min')
            def put(name, values):
                xr.Dataset({'temperature':(('time','height'),values),
                            'waterVapor':(('time','height'),np.ones((2,2)))},
                           coords={'time':t,'height':[0.,1.]}).to_netcdf(root/name)
            put('tropoeOutput_Ch2_B17.20240601.180000.nc',[[1.,2.],[np.nan,2.]])
            put('tropoeOutput_Ch2_B17.20240601.180001.nc',[[1.,2.],[np.nan,2.]])
            put('tropoeOutput_Ch2_B1.20240601.180000.nc',[[1.,2.],[1.,2.]])
            (root/'tropoeOutput_Ch1.20240601.180000.nc').write_text('broken')
            files,profiles=scan(root)
            self.assertEqual(len(files),4)
            self.assertEqual(sum(p['status']=='usable' for p in profiles),4)
            self.assertEqual(sum(f['status']=='unreadable' for f in files),1)
            manifest=root/'manifest.csv'
            with manifest.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['case_id','sounding_time','retrieval_time','category']);w.writeheader()
                for i,h in enumerate(['18:00:00','18:15:00','19:00:00']):
                    w.writerow(dict(case_id=str(i),sounding_time='2024-06-01T'+h,retrieval_time='2024-06-01T'+h,category='clear_sky'))
            rows=expected_cases(manifest,profiles,[17],True,'clear_sky',60)
            self.assertEqual([r['status'] for r in rows],['missing','duplicate','missing','invalid_output','missing','missing'])
            self.assertTrue(all(r['band'] in ('','17') for r in rows))
            rows=expected_cases(manifest,profiles,[1],False,'clear_sky',0)
            self.assertEqual([r['status'] for r in rows],['complete','complete','missing'])
            with patch('sys.argv', ['catalog_retrievals.py', '--retrieval-dir', str(root), '--manifest', str(manifest), '--bands', '1', '--no-ch1']):
                main()
            summary=json.loads((root/'catalog'/'summary.json').read_text())
            self.assertEqual(summary['cases'], {'complete':2, 'missing':1})
            with (root/'catalog'/'pending.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 1)

    def test_time_matching_does_not_use_filename_hour(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            xr.Dataset({'temperature':(('time','height'),[[1.,2.]]),'waterVapor':(('time','height'),[[1.,2.]])},
                       coords={'time':[np.datetime64('2024-06-01T18:00')],'height':[0.,1.]}).to_netcdf(root/'tropoeOutput_Ch1.20240601.000000.nc')
            _,p=scan(root)
            self.assertEqual(p[0]['time'],'2024-06-01T18:00:00')
            self.assertEqual(p[0]['status'],'usable')
