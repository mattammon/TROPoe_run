import unittest
import numpy as np
from dashboard_plots import skewed_profile_pair


class SkewedProfilesTests(unittest.TestCase):
    def test_physical_values_shared_legend_and_skew(self):
        p = dict(z=np.array([0., .5, 1.]), T=np.array([20., 20., 20.]), q=np.array([8.,8.,8.]))
        fig = skewed_profile_pair('case', ['Ch1'], {('case','Ch1'):p}, {'case':p}, (0.,1.))
        profiles = [t for t in fig.data if t.name == 'Ch1']
        self.assertEqual(len(profiles), 2)
        for trace, raw in zip(profiles, (p['T'], p['q'])):
            np.testing.assert_array_equal(trace.customdata, raw)
            self.assertGreater(trace.x[-1], trace.x[0])
            self.assertFalse(trace.connectgaps)
        self.assertEqual(sum(t.showlegend is True for t in fig.data), 2)
        self.assertEqual(fig.layout.yaxis.range, (0.,1.))
        self.assertEqual(fig.layout.yaxis2.range, (0.,1.))
        self.assertEqual(fig.layout.legend.groupclick, 'togglegroup')

    def test_missing_variable_and_layer(self):
        p = dict(z=np.array([0.,1.,2.]), T=np.array([20., np.nan, 10.]))
        fig = skewed_profile_pair('case', ['Ch1'], {('case','Ch1'):p}, {}, (0.,1.))
        trace = next(t for t in fig.data if t.name == 'Ch1')
        self.assertEqual(len(trace.y), 2)
        self.assertTrue(np.isnan(trace.x[-1]))
        self.assertTrue(any(a.text == 'No profile data in this layer' for a in fig.layout.annotations))
        with self.assertRaises(ValueError):
            skewed_profile_pair('case', [], {}, {}, (1.,0.))


if __name__ == '__main__':
    unittest.main()
