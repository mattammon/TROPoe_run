"""New spectral entries work without changes to downstream band lists."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import spectralBands
from case_collections import save_bands, read_bands
from catalog_retrievals import create_catalog
from dashboard_plots import colors
from retrieval_todo import expected_models, normalize_skip_bands, read_todo
import test_retrieval_todo


class DynamicBandTests(unittest.TestCase):
    def test_sparse_future_band_and_saved_selection(self):
        with patch.dict(spectralBands.ch2_bands, {'band42': '2200-2300'}):
            bands = spectralBands.available_ch2_bands()
            self.assertEqual(bands[-1], 42)
            self.assertNotIn(41, bands)
            self.assertIn('Ch2_B42', expected_models(bands))
            self.assertEqual(normalize_skip_bands(['42']), {'Ch2_B42'})
            with tempfile.TemporaryDirectory() as directory:
                manifest = Path(directory)/'collection.csv'
                save_bands(manifest, ['Ch2_B42', 'Ch1'])
                self.assertEqual(read_bands(manifest), ['Ch1', 'Ch2_B42'])
                _, summary, _ = create_catalog(directory)
                self.assertIn(42, summary['bands'])

    def test_colors_are_stable_for_new_bands(self):
        original = colors(['Ch1', 'Ch2_B1', 'Ch2_B18'])
        expanded = colors(['Ch1', 'Ch2_B1', 'Ch2_B18', 'Ch2_B19', 'Ch2_B42'])
        self.assertEqual(original, {m: expanded[m] for m in original})
        self.assertEqual(colors(['Ch2_B42'])['Ch2_B42'], expanded['Ch2_B42'])
        self.assertEqual(len(set(expanded.values())), len(expanded))

    def test_future_band_queue_is_accepted_and_completed(self):
        fixture = test_retrieval_todo.TodoTests()
        fixture.setUp()
        try:
            with patch.dict(spectralBands.ch2_bands, {'band42': '2200-2300'}):
                todo = fixture.plan([42])
                self.assertIn('Ch2_B42', read_todo(fixture.queue, fixture.outputs).model.tolist())
                fixture.output(model='Ch2_B42')
                self.assertNotIn('Ch2_B42', fixture.plan([42]).model.tolist())
        finally:
            fixture.tearDown()
