import json
from datetime import datetime
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from retrieval_debug import run_debug


class FakeVIP:
    clobber = 0

    def __init__(self, root):
        self.output_dir = str(root/'shared')
        self.vip_file = str(root/'original.txt')
        self.lbl_temp_dir = str(root/'original_work')

    def write_vip(self, **kwargs):
        Path(self.vip_file).write_text(json.dumps(vars(self)))


class DebugTests(unittest.TestCase):
    def test_attempt_isolation_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vip = FakeVIP(root)
            original = vars(vip).copy()
            counter = []

            def solver(command, cwd, check):
                self.assertIn('--debug', command)
                self.assertTrue(Path(command[1]).is_absolute())
                settings = json.loads(Path(command[3]).read_text())
                counter.append(1)
                Path(cwd, 'vip.npy').write_text('vip')
                Path(settings['lbl_temp_dir'], 'debug_output.Kij.iter_0.cdf').write_text('matrix')
                Path(settings['output_dir'], 'history.pkl').write_text('history')
                Path(settings['output_dir'], 'retrieval.nc').write_text(str(len(counter)))

            def run():
                return run_debug('202211120529', datetime(2022, 11, 12, 5, 30),
                                 vip, 2, 25, '1', root/'debug', root/'prior.nc')

            with patch('retrieval_debug.subprocess.run', side_effect=solver):
                first, second = run(), run()
                self.assertNotEqual(first, second)
                self.assertEqual(vars(vip), original)
                self.assertEqual((root/'shared/retrieval.nc').read_text(), '1')
                self.assertEqual((second/'output/retrieval.nc').read_text(), '2')
                for attempt in (first, second):
                    self.assertTrue((attempt/'vip.npy').exists())
                    self.assertTrue((attempt/'work/debug_output.Kij.iter_0.cdf').exists())
                    self.assertTrue((attempt/'output/history.pkl').exists())
                    self.assertEqual(json.loads((attempt/'run.json').read_text())['status'], 'finished')
                vip.clobber = 1
                run()
                self.assertEqual((root/'shared/retrieval.nc').read_text(), '3')
                self.assertEqual((first/'output/retrieval.nc').read_text(), '1')

    def test_failure_retains_diagnostics_without_publishing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def solver(command, cwd, check):
                Path(cwd, 'vip.npy').write_text('partial')
                Path(cwd, 'output/retrieval.nc').write_text('incomplete')
                raise subprocess.CalledProcessError(1, command)

            with patch('retrieval_debug.subprocess.run', side_effect=solver):
                with self.assertRaises(subprocess.CalledProcessError):
                    run_debug('202211120529', datetime(2022, 11, 12, 5, 30),
                              FakeVIP(root), 1, None, '1', root/'debug', root/'prior.nc')
            metadata = next((root/'debug').rglob('run.json'))
            self.assertEqual(json.loads(metadata.read_text())['status'], 'failed')
            self.assertTrue((metadata.parent/'vip.npy').exists())
            self.assertFalse((root/'shared/retrieval.nc').exists())


if __name__ == '__main__':
    unittest.main()
