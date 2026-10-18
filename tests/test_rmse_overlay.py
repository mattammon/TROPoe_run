import unittest
import numpy as np
import pandas as pd
from dashboard_plots import rmse_distributions, taylor_pair


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.models = ['Ch1', 'Ch2_B1']
        self.analyses = {}
        for v in ('T', 'q'):
            self.analyses[v] = dict(variable=v, edges=np.array([0., .5, 1.5]),
                metrics=pd.DataFrame([dict(case_id=c, model=m, rmse=r) for m in self.models
                                      for c, r in [('a', .5), ('b', 1.)]]),
                case_labels={'a':'Case A', 'b':'Case B'},
                curves={(c,m):dict(observed=np.array([1.,2.,3.]), retrieved=np.array([1.2,2.,3.1]))
                        for m in self.models for c in ('a','b')})

    def test_overlay_and_separate_points(self):
        fig = rmse_distributions(self.analyses, self.models)
        for i, model in enumerate(self.models):
            tbox, tpoints = fig.data[2*i:2*i+2]
            qbox, qpoints = fig.data[4+2*i:6+2*i]
            self.assertEqual(list(tbox.x), list(qbox.x))
            self.assertTrue(all(x < i-.15 for x in tpoints.x))
            self.assertTrue(all(x > i+.15 for x in qpoints.x))
            self.assertEqual(tpoints.marker.symbol, 'circle')
            self.assertEqual(qpoints.marker.symbol, 'diamond-open')
            self.assertNotEqual(tbox.fillcolor, qbox.fillcolor)
            self.assertEqual(list(tbox.y), [.5, 1.])
        self.assertEqual(sum(t.showlegend is True for t in fig.data), 2)
        self.assertEqual(fig.layout.legend.groupclick, 'togglegroup')
        self.assertEqual(fig.layout.boxmode, 'overlay')

    def test_variable_visibility_and_empty_cohort(self):
        fig = rmse_distributions(self.analyses, self.models, ['q'])
        self.assertTrue(all(t.legendgroup == 'q' for t in fig.data))
        self.assertEqual(len(fig.data), 4)
        self.analyses['T']['metrics'] = pd.DataFrame()
        fig = rmse_distributions(self.analyses, self.models)
        self.assertEqual(len(fig.data), 4)
        self.assertEqual(len(rmse_distributions(self.analyses, self.models, []).data), 0)

    def test_taylor_markers(self):
        fig, tables = taylor_pair(self.analyses, self.models)
        markers = [t for t in fig.data if t.name in self.models]
        self.assertEqual(len(markers), 4)
        self.assertTrue(all(t.marker.size == 11 and t.marker.symbol == 'cross-thin' for t in markers))
        self.assertEqual(len(tables['T']), 2)


if __name__ == '__main__':
    unittest.main()
