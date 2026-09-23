"""Selection and calibration-count regressions using the actual manifest schema."""
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from PLOT_RADIANCE_CALIBRATION import load_cases, plot_calibration


class CalibrationTests(unittest.TestCase):
    def manifest(self, root):
        path = root/'manifest.csv'
        pd.DataFrame({
            'case_id': ['before', 'clear', 'cloud', 'poor', 'missing', 'after'],
            'sounding_time': ['2024-05-31T23:59:59', '2024-06-01T00:00:00',
                              '2024-06-01T12:00:00', '2024-06-02T23:59:59',
                              '2024-06-02T18:00:00', '2024-06-03T00:00:00'],
            'asi_state': ['clear_sky', 'clear_sky', 'not_clear_sky', 'uncertain', 'uncertain', 'clear_sky'],
            # Deliberately contradict final category: colors must remain ASI-based.
            'category': ['uncertain']*6,
            'radiance_context_radiance_mean': [1., 5., 20., 6., None, 1.],
            'radiance_context_radiance_std': [1., .2, 2., .3, None, 1.],
            'radiance_context_adequate': ['True', 'True', 'True', 'False', 'False', 'True'],
        }).to_csv(path, index=False)
        (root/'policy.json').write_text(json.dumps({'wavenumber': 985., 'context_minutes': 60.}))
        return path

    def test_inclusive_dates_missing_and_independent_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.manifest(Path(tmp))
            df, _ = load_cases(path, '20240601', '2024-06-02')
            self.assertEqual(df.case_id.tolist(), ['clear', 'cloud', 'poor', 'missing'])
            self.assertEqual(df.plot_status.tolist(), ['adequate_coverage', 'adequate_coverage',
                                                      'insufficient_coverage', 'missing_mean_or_std'])
            self.assertEqual(df.asi_label.iloc[0], 'clear_sky')

    def test_plot_and_candidate_counts_exclude_poor_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = plot_calibration(self.manifest(root), '2024-06-01', '2024-06-02', root/'plots', mean_max=10., std_max=1.)
            summary = json.loads(paths['summary'].read_text())
            self.assertEqual(summary['plotted'], 3)
            self.assertEqual(summary['missing_mean_or_std'], 1)
            self.assertEqual(summary['candidate_counts_by_asi']['clear_sky'], {'eligible': 1, 'passes': 1})
            self.assertEqual(summary['candidate_counts_by_asi']['not_clear_sky'], {'eligible': 1, 'passes': 0})
            self.assertEqual(summary['candidate_counts_by_asi']['uncertain'], {'eligible': 0, 'passes': 0})
            self.assertGreater(paths['figure'].stat().st_size, 10000)
            self.assertEqual(len(pd.read_csv(paths['cases'])), 4)

    def test_empty_range_and_wrong_wavenumber(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = self.manifest(root)
            paths = plot_calibration(path, '2020-01-01', '2020-01-01', root/'empty')
            self.assertEqual(json.loads(paths['summary'].read_text())['plotted'], 0)
            (root/'policy.json').write_text(json.dumps({'wavenumber': 900}))
            with self.assertRaises(ValueError): load_cases(path, '2024-06-01', '2024-06-02')


if __name__ == '__main__':
    unittest.main()
