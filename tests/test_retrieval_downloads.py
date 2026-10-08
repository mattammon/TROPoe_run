import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import xarray as xr
import config
from arm_download import ARMClient
from get_sgp_data import SGP_DATA, download_todo_inputs


class RetrievalDownloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.dirs = {key: str(self.root/key) for key in ('ch1', 'ch2', 'sum', 'eng', 'sfc', 'aod')}
        self.queue = self.root/'todo.csv'

    def test_deduplicated_channels_midnight_aod_and_skips(self):
        jobs = pd.DataFrame({'case_id': ['case', 'case'], 'channel': ['2', '2'],
                             'retrieval_time': ['2025-01-02T00:00:00Z']*2})
        client = Mock()
        client.download.return_value = [{'status': 'existing'}]
        with patch('retrieval_todo.pending_todo', return_value=jobs) as pending, patch.object(config, 'AOD_DATASTREAM', 'sgptestAODC1.c1'):
            report = download_todo_inputs(self.queue, skip_bands=['Ch1'], directories=self.dirs, client=client)
        self.assertEqual(pending.call_args.args[2], ['Ch1'])
        self.assertEqual(len(report), 10)  # Five streams, two days; no duplicate Ch2-band requests.
        self.assertEqual(set(report.stream), {'ch2', 'sum', 'eng', 'sfc', 'aod'})
        self.assertEqual(set(report.day), {'2025-01-01', '2025-01-02'})
        self.assertTrue(report.status.eq('complete').all())
        self.assertTrue(any(c.args[0] == 'sgptestAODC1.c1' for c in client.download.call_args_list))
        self.assertTrue((self.root/'todo_downloads.csv').exists())

    def test_empty_queue_needs_no_client_and_failures_are_reported(self):
        with patch('retrieval_todo.pending_todo', return_value=pd.DataFrame()), patch('get_sgp_data.ARMClient') as arm:
            self.assertTrue(download_todo_inputs(self.queue).empty)
            arm.assert_not_called()
        jobs = pd.DataFrame({'case_id': ['case'], 'channel': ['1'], 'retrieval_time': ['2025-01-01T12:00:00Z']})
        client = Mock()
        client.download.return_value = []
        with patch('retrieval_todo.pending_todo', return_value=jobs):
            report = download_todo_inputs(self.queue, directories=self.dirs, client=client)
        self.assertTrue(report.status.eq('incomplete').all())
        self.assertEqual(len(report), 4)

    def test_legacy_file_is_linked_into_vip_input_directory(self):
        old = self.root/'ch2'/'old_group'
        old.mkdir(parents=True)
        name = SGP_DATA.streams['ch2']+'.20250101.000000.nc'
        source = old/name
        xr.Dataset({'x': ('time', [1.])}).to_netcdf(source)
        client = Mock()
        client.download.return_value = [{'status': 'existing'}]
        downloader = SGP_DATA('20250101', '20250101', directories=self.dirs, client=client)
        downloader.dataset_download('ch2', self.dirs['ch2'], '2025-01-01', '2025-01-01')
        target = Path(self.dirs['ch2'])/config.MASTER_DATA_FOLDER/name
        self.assertTrue(target.is_symlink())
        self.assertEqual(target.resolve(), source)

    def test_valid_files_are_reused_and_corrupt_files_replaced(self):
        name = 'sgptestC1.b1.20250101.000000.nc'
        path = self.root/name
        xr.Dataset({'x': ('time', [1.])}).to_netcdf(path)
        good = path.read_bytes()
        payload = json.dumps({'status': 'success', 'files': [name]}).encode()
        client = ARMClient.__new__(ARMClient)
        client._credentials = 'test:test'
        with patch('arm_download.urlopen', return_value=io.BytesIO(payload)) as request:
            records = client.download('sgptestC1.b1', '2025-01-01', '2025-01-01', self.root)
        self.assertEqual(records[0]['status'], 'existing')
        self.assertEqual(request.call_count, 1)
        path.write_text('interrupted download')
        with patch('arm_download.urlopen', side_effect=[io.BytesIO(payload), io.BytesIO(good)]) as request:
            records = client.download('sgptestC1.b1', '2025-01-01', '2025-01-01', self.root)
        self.assertEqual(records[0]['status'], 'downloaded')
        self.assertEqual(path.read_bytes(), good)
        self.assertEqual(request.call_count, 2)


if __name__ == '__main__':
    unittest.main()
