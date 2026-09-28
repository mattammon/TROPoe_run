import tempfile
import unittest
from types import SimpleNamespace
import numpy as np
import matplotlib
matplotlib.use('Agg')
from taylor_diagram import taylor_statistics, interpolate, plot_taylor_profiles

class TaylorTests(unittest.TestCase):
    def test_bias_centered_error_and_negative_correlation(self):
        obs=np.array([1.,2.,4.])
        s=taylor_statistics(obs,obs+3)
        self.assertAlmostEqual(s['correlation'],1.)
        self.assertAlmostEqual(s['centered_rmse'],0.)
        self.assertAlmostEqual(s['rmse'],3.)
        self.assertAlmostEqual(taylor_statistics(obs,-obs)['correlation'],-1.)
        self.assertIsNone(taylor_statistics(obs,np.ones(3))['correlation'])
        self.assertIsNone(taylor_statistics(np.ones(3),obs)['std_ratio'])
        s=taylor_statistics(obs,np.array([4.,1.,3.]))
        self.assertAlmostEqual(s['normalized_centered_rmse']**2,1+s['std_ratio']**2-2*s['std_ratio']*s['correlation'])

    def test_interpolation_preserves_missing_and_bounds(self):
        a=interpolate([0,1,2],[1,np.nan,3],[-1,0,.5,1,1.5,2,3])
        self.assertEqual(a[1],1.)
        self.assertTrue(np.isnan(a[[0,2,3,4,6]]).all())

    def test_paired_grids_exports_and_anomalies(self):
        obs={}; ret={}
        for i in range(3):
            k=str(i);obs[k]={'T':np.array([1.,2.,3.])+i}
            ret[k]={'Ch1':{'hgt':[0,1,2],'T':np.array([1.,2.,3.])+i},
                    'Ch2_B17':{'hgt':[0,.5,1,1.5,2],'T':np.linspace(1,3,5)+i+2}}
        e=SimpleNamespace(good_dts=list(obs),profile_data={'observed_snd':obs,'retrieval_snd':ret})
        with tempfile.TemporaryDirectory() as tmp:
            for anomalies in (False,True):
                rows=plot_taylor_profiles(e,['Ch1','Ch2_B17'],tmp,max_height=2,grid_step=.5,variables=('T',),anomalies=anomalies)
                self.assertEqual(rows[0]['n_samples'],15)
                self.assertAlmostEqual(rows[1]['centered_rmse'],0.)
                self.assertAlmostEqual(rows[1]['bias'],0 if anomalies else 2)
