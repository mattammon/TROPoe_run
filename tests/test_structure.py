import unittest
import numpy as np
from dashboard_structure import sonde_state, response, covariance_correlation


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.z = np.array([0., 1., 2.])
        self.state = dict(z=self.z, Xa=np.array([20.,15.,10.,8.,5.,2.,42.]))
        self.sonde = dict(z=self.z, T=np.array([21.,16.,11.]), q=np.array([9.,6.,3.]))

    def test_full_state_and_auxiliary_prior(self):
        values, count = sonde_state(self.state, self.sonde)
        self.assertEqual(count, 0)
        self.assertEqual(values[-1], 42.)
        np.testing.assert_allclose(values[:3], self.sonde['T'])

    def test_cross_variable_and_prior_response(self):
        a = np.eye(7)*.5
        a[3,0] = .2
        delta, out = response(a,self.z,'T',0.,.2,1.)
        self.assertAlmostEqual(out[3], .2)
        _, prior = response(a,self.z,'T',0.,.2,1.,'Prior-mean feature (fixed A)')
        np.testing.assert_allclose(out+prior,delta)

    def test_coverage_and_interior_missing(self):
        short = dict(z=np.array([.5,1.5]),T=np.array([18.,13.]),q=np.array([7.,3.]))
        with self.assertRaises(ValueError): sonde_state(self.state,short)
        values,count=sonde_state(self.state,short,True)
        self.assertEqual(count,2)
        self.assertEqual(values[0],self.state['Xa'][0])
        self.sonde['T'][1]=np.nan
        with self.assertRaises(ValueError): sonde_state(self.state,self.sonde,True)

    def test_covariance_correlation_zero_variance(self):
        c=covariance_correlation(np.array([[4.,2.,0.],[2.,4.,0.],[0.,0.,0.]]))
        self.assertAlmostEqual(c[0,1],.5)
        self.assertTrue(np.isnan(c[2]).all())


if __name__ == '__main__': unittest.main()
