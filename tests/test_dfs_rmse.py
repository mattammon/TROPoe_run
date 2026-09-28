import unittest
import tempfile
from types import SimpleNamespace
import numpy as np
import matplotlib
matplotlib.use('Agg')
from plot_dfs_rmse import plot_dfs_rmse

class DFSRMSETests(unittest.TestCase):
    def test_paired_information_and_rmse(self):
        obs={}; ret={}
        for k in ('a','b'):
            obs[k]={'T':[1.,2.,3.],'q':[1.,2.,3.]};ret[k]={}
            for model,offset in [('Ch1',0),('Ch2_B17',2)]:
                ret[k][model]={'hgt':[0.,1.,2.],'T':np.array([1.,2.,3.])+offset,'q':np.array([1.,2.,3.])+offset,
                              'information':{'height_km':np.array([0.,1.,2.]),'variables':{v:{'source':'Akernal','dfs_level':np.array([.2,.3,.5])} for v in ('T','q')}}}
        del ret['b']['Ch2_B17']['information']['variables']['q']
        e=SimpleNamespace(good_dts=['a','b'],profile_data={'observed_snd':obs,'retrieval_snd':ret})
        with tempfile.TemporaryDirectory() as out:
            data, summary=plot_dfs_rmse(e,['Ch1','Ch2_B17'],out,max_height=2,grid_step=.3)
        for row in summary:
            self.assertAlmostEqual(row['mean_layer_dfs'],1.)
            self.assertAlmostEqual(row['pooled_rmse'],0. if row['model']=='Ch1' else 2.)
            self.assertEqual(row['n_cases'],2 if row['variable']=='T' else 1)
