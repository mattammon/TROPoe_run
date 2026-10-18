import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from catalog_retrievals import scan, create_catalog
from dashboard_catalog import qc_matrix, qc_grid, completion_summary, qc_style
from retrieval_todo import completion_matrix


class CatalogQCTests(unittest.TestCase):
    def test_time_specific_qc_and_incomplete_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ds = xr.Dataset(dict(temperature=(('time','height'), [[1.,2.],[np.nan,np.nan],[1.,2.]]),
                                 waterVapor=(('time','height'), np.ones((3,2))), qc_flag=('time',[0,2,3])),
                            coords=dict(time=pd.date_range('2025-01-01', periods=3, freq='15min'), height=[0.,1.]))
            ds.to_netcdf(root/'tropoeOutput_Ch1.20250101.000000.nc')
            _, profiles = scan(root)
            self.assertEqual([p['qc_flag'] for p in profiles], [0,2,3])
            self.assertEqual([p['status'] for p in profiles], ['usable','partial','usable'])
            out, _, _ = create_catalog(root, bands=[])
            self.assertEqual(pd.read_csv(out/'profiles.csv').qc_flag.tolist(), [0,2,3])
            _, summary, _ = create_catalog(root, bands=[], reuse_inventory=True)
            self.assertEqual(summary['inventory_mode'], 'saved')
            # Legacy saved inventory remains usable until explicitly refreshed.
            old = pd.read_csv(out/'profiles.csv').drop(columns='qc_flag')
            old.to_csv(out/'profiles.csv', index=False)
            create_catalog(root, bands=[], reuse_inventory=True)
            create_catalog(root, bands=[])
            self.assertIn('qc_flag', pd.read_csv(out/'profiles.csv'))

    def test_counts_colors_and_duplicate_preference(self):
        times = pd.date_range('2025-01-01', periods=5, freq='15min', tz='UTC')
        cases = pd.DataFrame(dict(case_id=list('abcde'), retrieval_time=times, category='clear_sky'))
        index = pd.DataFrame([dict(file=str(i), profile_index=0, time=t, model='Ch1', status=status, qc_flag=flag)
            for i,(t,status,flag) in enumerate(zip(times[:4], ['usable','partial','usable','usable'], [0,2,3,np.nan]))])
        duplicate = index.iloc[[0]].copy()
        duplicate['file'] = 'duplicate'
        duplicate['status'] = 'partial'
        duplicate['qc_flag'] = 2
        index = pd.concat([index, duplicate], ignore_index=True)
        matrix = completion_matrix(cases,index,['Ch1'],60.)
        flags = qc_matrix(cases,index,['Ch1'],60.)
        summary, all_complete, none = completion_summary(matrix,flags)
        self.assertEqual(summary['QC 2 · not converged'].iloc[0],1)
        self.assertEqual(summary['QC 3 · spectral RMS too large'].iloc[0],1)
        self.assertEqual(all_complete,3)
        self.assertEqual(none,2)
        grid = qc_grid(matrix, flags)
        self.assertEqual(grid.Ch1.tolist(), ['Complete · QC 0','Not converged · QC 2','Complete · QC 3',
                                            'Complete · QC unknown/other','Missing / incomplete'])
        self.assertIn('#dc2626', qc_style(grid.loc['b','Ch1']))
        self.assertIn('#facc15', qc_style(grid.loc['c','Ch1']))
        self.assertIn('#20854e', qc_style(grid.loc['a','Ch1']))
        empty = qc_matrix(cases, index, [], 60.)
        self.assertEqual(empty.shape,(5,0))

    def test_invalid_record_qc_from_errors(self):
        cases = pd.DataFrame([dict(case_id='a', retrieval_time='2025-01-01T00:00:00Z', category='clear_sky')])
        index = pd.DataFrame(columns=['file','profile_index','time','model','status'])
        errors = pd.DataFrame([dict(file='bad', profile_index=0, time='2025-01-01T00:00:00Z',
                                   channel=1, band='', status='invalid', qc_flag=2)])
        self.assertEqual(qc_matrix(cases,index,['Ch1'],60.,errors).loc['a','Ch1'],2)
        self.assertTrue(qc_matrix(cases,index,['Ch1'],60.).isna().all().all())


if __name__ == '__main__':
    unittest.main()
