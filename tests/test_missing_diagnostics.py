import json
import unittest
import numpy as np
import pandas as pd
from cloud_screening import ScreenPolicy, evaluate_case, window_stats
from get_sgp_data import json_safe

class MissingDiagnosticsTests(unittest.TestCase):
    def frame(self, values):
        return pd.DataFrame({'time':pd.date_range('2024-06-01T18:00', periods=len(values), freq='1min'),
                             'valid':True,'file':'test.nc','zenith':values,'total':0.})

    def test_partial_and_missing_fields_serialize(self):
        for values, expected_n in (([0., np.nan, np.inf],1), ([np.nan]*3,0)):
            r=evaluate_case('2024-06-01T18:00',self.frame(values),pd.DataFrame(),ScreenPolicy())
            w=r['evidence']['asi']['context']
            self.assertEqual(w['zenith_n_finite'],expected_n)
            self.assertIsNone(w['zenith_std'])
            if not expected_n:
                self.assertIsNone(w['zenith_mean'])
            json.dumps(r,allow_nan=False)

    def test_statistics_use_finite_values_only(self):
        start=pd.Timestamp('2024-06-01T18:00')
        w,_=window_stats(self.frame([1.,3.,np.nan]),start,start+pd.Timedelta(minutes=3),['zenith'],ScreenPolicy())
        self.assertEqual(w['zenith_mean'],2.)
        self.assertAlmostEqual(w['zenith_std'],np.sqrt(2.))

    def test_nested_writer_safety_net(self):
        clean=json_safe([{'a':float('nan'),'b':[float('inf'),float('-inf'),1.]}])
        self.assertEqual(json.loads(json.dumps(clean,allow_nan=False)),[{'a':None,'b':[None,None,1.]}])
