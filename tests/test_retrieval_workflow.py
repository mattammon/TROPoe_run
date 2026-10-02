import subprocess
import unittest
from unittest.mock import patch

from utils import completed_retrieval, rounded_retrieval_time
from SINGLE_TROPoe import run_tropoe


class RetrievalWorkflowTests(unittest.TestCase):
    def test_quarter_hour_lookup_and_midnight(self):
        self.assertEqual(rounded_retrieval_time('202405141859').strftime('%Y%m%d%H%M'),
                         '202405141900')
        self.assertEqual(rounded_retrieval_time('202405141908').strftime('%Y%m%d%H%M'),
                         '202405141915')
        self.assertEqual(rounded_retrieval_time('202405142359').strftime('%Y%m%d%H%M'),
                         '202405150000')
        files = {'tropoeOutput_Ch1.20240514.190000.nc',
                 'tropoeOutput_Ch2_B2.20240514.190000.nc'}
        self.assertTrue(completed_retrieval('202405141859', 1, files))
        self.assertTrue(completed_retrieval('202405141859', 2, files, 2))
        self.assertFalse(completed_retrieval('202405141859', 2, files, 6))
        self.assertFalse(completed_retrieval('202405141915', 1, files))

    def test_launcher_uses_next_day_at_midnight_and_reports_failure(self):
        class VIP:
            vip_file = '/tmp/retrieval_workflow_test.vip'

            def write_vip(self, **kwargs):
                pass

        with patch('SINGLE_TROPoe.subprocess.run') as run, patch('SINGLE_TROPoe.os.remove'):
            run_tropoe('202405142359', VIP(), channel=2, band=2)
            args = run.call_args.args[0]
            self.assertEqual(args[2], '20240515')
            self.assertIn('--shour=0.00', args)
            self.assertTrue(run.call_args.kwargs['check'])

        with patch('SINGLE_TROPoe.subprocess.run', side_effect=subprocess.CalledProcessError(1, 'TROPoe.py')):
            with self.assertRaises(subprocess.CalledProcessError):
                run_tropoe('202405141859', VIP())


if __name__ == '__main__':
    unittest.main()
