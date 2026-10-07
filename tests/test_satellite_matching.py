"""Satellite filename matching and the image-review panel (no GOES/network access)."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from dashboard_classification import satellite_inventory, match_satellite_images, satellite_images

class SatelliteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.group = self.root/'clear_sky_days'
        self.group.mkdir()
        self.image = self.group/'202503051920_GOES-16_VIS.png'
        self.image.touch()
    def tearDown(self): self.tmp.cleanup()
    def test_nested_exact_and_retrieval_time(self):
        self.assertEqual(satellite_images(self.root,'2025-03-05T19:20:49Z'),[self.image])
        self.assertEqual(satellite_images(self.group,'2025-03-05T13:20:00-06:00'),[self.image])
        result=match_satellite_images(satellite_inventory(self.root),'2025-03-05T19:13Z','2025-03-05T19:20Z')
        self.assertEqual(result['basis'],'exact retrieval minute')
        self.assertEqual(result['matches'][0]['path'],self.image)
    def test_nearby_is_bounded_and_reports_offset(self):
        inventory=satellite_inventory(self.root)
        for tolerance, expected in [(0,0),(4,0),(5,1),(15,1)]:
            result=match_satellite_images(inventory,'2025-03-05T19:13Z','2025-03-05T19:15Z',tolerance)
            self.assertEqual(len(result['matches']),expected)
        self.assertEqual(result['matches'][0]['offset_minutes'],5)
        self.assertEqual(result['basis'],'nearest to retrieval minute')
        self.assertFalse(match_satellite_images(inventory,'2025-03-06T19:15Z',tolerance_minutes=15)['matches'])
    def test_exact_priority_ties_missing_and_midnight(self):
        exact=self.group/'202503051913_GOES-16_VIS.png'; exact.touch()
        inv=satellite_inventory(self.root)
        self.assertEqual(match_satellite_images(inv,'2025-03-05T19:13Z','2025-03-05T19:20Z',15)['matches'][0]['path'],exact)
        earlier=self.group/'202503051910_GOES-16_IR.PNG'; earlier.touch()
        exact.unlink()
        self.assertEqual(len(match_satellite_images(satellite_inventory(self.root),'2025-03-05T19:14Z','2025-03-05T19:15Z',5)['matches']),2)
        midnight=self.group/'202503060000_GOES-16_IR.png'; midnight.touch()
        (self.group/'202513060000_invalid.png').touch()
        self.assertEqual(satellite_images(self.root,'2025-03-05T23:57Z',tolerance_minutes=3),[midnight])
        self.assertFalse(match_satellite_images([],None,None,15)['matches'])
        with self.assertRaises(FileNotFoundError): satellite_inventory(self.root/'absent')
    def test_image_panel_uses_example_and_audits_selected_path(self):
        from PIL import Image
        from streamlit.testing.v1 import AppTest
        Image.new('RGB',(10,10),'white').save(self.image)
        script='''
import pandas as pd
import streamlit as st
from dashboard_setup import inspect_case
from dashboard_classification import ReviewStore
frame=pd.DataFrame([dict(case_id='test-case',sounding_time=pd.Timestamp('2025-03-05T19:13Z'),retrieval_time=pd.Timestamp('2025-03-05T19:15Z'),category='clear_sky',automatic_category='clear_sky',classification_source='thresholds')])
inspect_case(frame, st.session_state['image_root'], ReviewStore(st.session_state['reviews']), 'test')
'''
        app=AppTest.from_string(script)
        app.session_state['image_root']=str(self.root)
        app.session_state['reviews']=str(self.root/'reviews')
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(next(s for s in app.selectbox if s.label=='Satellite image').options,[self.image.name])
        self.assertTrue(any('offset +5 min' in c.value for c in app.caption))
        self.assertTrue(any('Nearby-time match' in w.value for w in app.warning))
        next(n for n in app.number_input if n.label.startswith('Satellite filename')).set_value(0.).run()
        self.assertFalse(any(s.label=='Satellite image' for s in app.selectbox))
        next(n for n in app.number_input if n.label.startswith('Satellite filename')).set_value(15.).run()
        next(b for b in app.button if b.label=='Save persistent manual override').click().run()
        self.assertFalse(app.exception)
        from dashboard_classification import ReviewStore
        reviews,_=ReviewStore(self.root/'reviews').snapshot()
        self.assertEqual(reviews['test-case']['image_path'],str(self.image))

if __name__=='__main__': unittest.main()
