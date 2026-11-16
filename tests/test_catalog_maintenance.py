import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
import config

from catalog_maintenance import (delete_saved_catalog, plan_arm_cleanup,
                                 refresh_arm_catalog, retained_input_days)
from get_sgp_data import RetrievalInputPreparer, SGP_DATA


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_catalog_deletion_only_removes_selected_catalog(self):
        first = self.root/'runs/first'
        second = self.root/'collections/second'
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first/'classification.csv').write_text('case_id,category\n')
        (first/'settings.json').write_text('{}')
        (second/'collection.csv').write_text('case_id\n')
        (second/'settings.json').write_text('{}')
        (self.root/'manual_reviews.sqlite').write_text('history')
        todo = self.root/'active.csv'
        todo.write_text('classification_manifest\n'+str(first/'classification.csv')+'\n')
        with patch.object(config, 'RETRIEVAL_TODO_MANIFEST', str(todo)):
            delete_saved_catalog(self.root, first/'classification.csv')
        self.assertFalse(first.exists())
        self.assertFalse(todo.exists())
        self.assertTrue(second.exists())
        self.assertTrue((self.root/'manual_reviews.sqlite').exists())
        with self.assertRaises(ValueError):
            delete_saved_catalog(self.root, self.root/'manual_reviews.sqlite')

    def test_cleanup_keeps_union_and_padded_midnight_days(self):
        collections = [dict(path='a'), dict(path='b')]
        def frame(path):
            time = '2025-01-02T00:00:00Z' if path == 'a' else '2025-02-14T12:00:00Z'
            return pd.DataFrame({'retrieval_time': [time]})
        directories = {key: self.root/key for key in ('ch1', 'ch2', 'sum', 'eng', 'sfc')}
        with patch('case_collections.saved_collections', return_value=(collections, [])), \
                patch('case_collections.read_collection', side_effect=frame):
            days, count = retained_input_days(self.root)
            self.assertEqual((count, days), (2, {'20250101', '20250102', '20250214'}))
            for stream, directory in directories.items():
                directory.joinpath('ALL').mkdir(parents=True)
                for day in ('20250101', '20250102', '20250214', '20250301'):
                    (directory/'ALL'/f'{SGP_DATA.streams[stream]}.{day}.000000.cdf').write_text('raw')
            (directories['ch1']/'ALL'/'keep_notes.txt').write_text('other')
            stray = directories['ch1']/'ALL'/f'{SGP_DATA.streams["ch1"]}.20250301.000000.cdf'
            link = directories['ch1']/'old'
            link.mkdir()
            (link/stray.name).symlink_to(stray)
            candidates, _, _ = plan_arm_cleanup(self.root, directories)
            self.assertEqual(len(candidates), 6)
            totals, _, _ = refresh_arm_catalog(self.root, directories)
            self.assertEqual(totals['files'], 6)
            self.assertTrue((directories['ch1']/'ALL'/'keep_notes.txt').exists())
            self.assertFalse(stray.exists())
            self.assertFalse((link/stray.name).is_symlink())
            self.assertTrue((directories['ch1']/'ALL'/f'{SGP_DATA.streams["ch1"]}.20250101.000000.cdf').exists())

    def test_corrupt_collection_aborts_cleanup(self):
        with patch('case_collections.saved_collections', return_value=([], [{'path': 'broken'}])):
            with self.assertRaisesRegex(ValueError, 'unreadable'):
                plan_arm_cleanup(self.root)

    def test_prepare_required_and_optional_inputs(self):
        directories = {key: str(self.root/key) for key in ('ch1', 'ch2', 'sum', 'eng', 'sfc', 'aod')}
        preparer = RetrievalInputPreparer(directories=directories, client=object())
        calls = []
        def download(stream, directory, start, end):
            calls.append((stream, start))
            return [] if stream == 'aod' else [{'status': 'existing'}]
        with patch.object(preparer.downloader, 'dataset_download', side_effect=download):
            preparer.ensure('202501020000', 2)
            preparer.ensure('202501020000', 2)
        self.assertEqual(len(calls), 10)
        self.assertEqual(set(stream for stream, _ in calls), {'ch2', 'sum', 'eng', 'sfc', 'aod'})
        self.assertEqual(set(day for _, day in calls), {'2025-01-01', '2025-01-02'})
        preparer = RetrievalInputPreparer(directories=directories, client=object())
        with patch.object(preparer.downloader, 'dataset_download', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'Cannot prepare retrieval inputs'):
                preparer.ensure('202501021200', 1)


if __name__ == '__main__':
    unittest.main()
