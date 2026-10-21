import unittest
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from averaging_kernel_rmse import read_smoothing_state, smooth_sounding
from dashboard_data import build_analysis, load_retrieval, signature


def dataset(kernel=None):
    a = np.eye(5) if kernel is None else kernel
    return xr.Dataset(dict(
        height=('height',[0.,1.],{'units':'km'}),
        temperature=(('time','height'),[[11.,8.]],{'units':'degC'}),
        waterVapor=(('time','height'),[[5.,4.]],{'units':'g/kg'}),
        Xa=('arb_dim1',[10.,7.,4.,3.,0.]),
        arb1=('arb_dim1',[1,1,2,2,3]), arb2=('arb_dim2',[1,1,2,2,3]),
        Akernal=(('time','arb_dim1','arb_dim2'),a[None])),
        coords={'time':pd.to_datetime(['2025-01-01'])})


class KernelTests(unittest.TestCase):
    def profile(self, a=None):
        ds = dataset(a).isel(time=0)
        return dict(z=np.array([0.,1.]),T=np.array([11.,8.]),q=np.array([5.,4.]),
                    smoothing=read_smoothing_state(ds,[0.,1.]))

    def sonde(self):
        return dict(z=np.array([0.,1.]),T=np.array([12.,9.]),q=np.array([6.,5.]))

    def test_identity_and_zero(self):
        obs=self.sonde()
        identity=smooth_sounding(self.profile(),obs)
        np.testing.assert_allclose(identity['T'],obs['T'])
        np.testing.assert_allclose(identity['q'],obs['q'])
        zero=smooth_sounding(self.profile(np.zeros((5,5))),obs)
        np.testing.assert_allclose(zero['T'],[10.,7.])
        np.testing.assert_allclose(zero['q'],[4.,3.])

    def test_cross_terms_and_auxiliary_prior(self):
        a=np.eye(5)*.5
        a[0,2]=.25
        a[1,4]=100 # auxiliary departure is zero
        smoothed=smooth_sounding(self.profile(a),self.sonde())
        np.testing.assert_allclose(smoothed['T'],[11.5,8.])
        np.testing.assert_allclose(smoothed['q'],[5.,4.])

    def test_coverage_and_interior_missing(self):
        obs=self.sonde();obs['z']=np.array([0.,.5])
        with self.assertRaisesRegex(ValueError,'full retrieval depth'):
            smooth_sounding(self.profile(),obs)
        result=smooth_sounding(self.profile(),obs,True)
        self.assertEqual(result['prior_extension_levels'],1)
        self.assertEqual(result['T'][1],7.)
        obs=self.sonde();obs['q'][0]=np.nan
        with self.assertRaisesRegex(ValueError,'Nonfinite|nonfinite'):
            smooth_sounding(self.profile(),obs,True)

    def test_schema_rejections(self):
        ds=dataset().isel(time=0)
        ds.arb2.values[0]=2
        with self.assertRaisesRegex(ValueError,'ordering'):
            read_smoothing_state(ds,[0.,1.])
        ds=dataset().isel(time=0).drop_vars('Xa')
        with self.assertRaises(KeyError):
            read_smoothing_state(ds,[0.,1.])

    def test_loader_and_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.nc';dataset().to_netcdf(path)
            args=(signature(path),0,pd.Timestamp('2025-01-01',tz='UTC'))
            self.assertNotIn('smoothing',load_retrieval(*args))
            self.assertIn('smoothing',load_retrieval(*args,load_ak=True))

    def test_analysis_raw_and_smoothed_same_cohort(self):
        cases=pd.DataFrame([dict(case_id='a',sounding_time=pd.Timestamp('2025-01-01'),category='clear_sky')])
        profiles={('a','Ch1'):self.profile(np.eye(5)*.5)}
        args=(cases,['Ch1'],profiles,{'a':self.sonde()},'T',np.array([0.,.5,1.]))
        raw=build_analysis(*args)['metrics']
        smooth=build_analysis(*args,reference='ak_smoothed')['metrics']
        self.assertAlmostEqual(raw.rmse.iloc[0],1.)
        self.assertAlmostEqual(smooth.rmse.iloc[0],0.)
        self.assertAlmostEqual(smooth.raw_rmse.iloc[0],1.)
        profiles[('a','Ch1')].pop('smoothing')
        self.assertTrue(build_analysis(*args,reference='ak_smoothed')['metrics'].empty)
        self.assertFalse(build_analysis(*args)['metrics'].empty)

if __name__ == '__main__': unittest.main()
