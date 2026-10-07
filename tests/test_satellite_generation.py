import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dashboard_satellite import generate_satellite_image

class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_single_sounding_utc_command_and_reuse(self):
        image=self.root/'202503051913_GOES-16_VIS.png'
        def run(command, **kwargs):
            self.assertEqual(command[3:6],['20250305','19','13'])
            self.assertEqual(command[-2:],['--output-dir',str(self.root)])
            self.assertEqual(kwargs['env']['MPLBACKEND'],'Agg')
            image.write_bytes(b'fixture')
            return subprocess.CompletedProcess(command,0,'finished')
        with patch('dashboard_satellite.subprocess.run',side_effect=run) as mocked:
            generate_satellite_image('2025-03-05T13:13:45-06:00',self.root)
            generate_satellite_image('2025-03-05T19:13Z',self.root)
            self.assertEqual(mocked.call_count,1)
    def test_failure_timeout_and_missing_output(self):
        with patch('dashboard_satellite.subprocess.run',return_value=subprocess.CompletedProcess([],1,'missing cartopy')):
            with self.assertRaisesRegex(RuntimeError,'missing cartopy'): generate_satellite_image('2025-03-05',self.root)
        with patch('dashboard_satellite.subprocess.run',side_effect=subprocess.TimeoutExpired([],180,output=b'waiting')):
            with self.assertRaisesRegex(RuntimeError,'timed out'): generate_satellite_image('2025-03-05',self.root)
        with patch('dashboard_satellite.subprocess.run',return_value=subprocess.CompletedProcess([],0,'')):
            with self.assertRaisesRegex(RuntimeError,'without creating'): generate_satellite_image('2025-03-05',self.root)
    def app(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_string('''
import pandas as pd
import streamlit as st
from dashboard_setup import inspect_case
from dashboard_classification import ReviewStore
frame=pd.DataFrame([dict(case_id='case',sounding_time=pd.Timestamp('2025-03-05T19:13Z'),retrieval_time=pd.Timestamp('2025-03-05T19:15Z'),category='clear_sky',automatic_category='clear_sky',classification_source='thresholds')])
inspect_case(frame,st.session_state['root'],ReviewStore(st.session_state['reviews']),'test')
''')
        app.session_state['root']=str(self.root/'images')
        app.session_state['reviews']=str(self.root/'reviews')
        return app
    def test_click_generates_once_and_displays(self):
        from PIL import Image
        app=self.app()
        def generate(time,root):
            self.assertEqual(time.minute,13) # sounding, never rounded retrieval time
            Path(root).mkdir()
            Image.new('RGB',(4,4)).save(Path(root)/'202503051913_GOES-16_VIS.png')
            return 'generated'
        with patch('dashboard_setup.generate_satellite_image',side_effect=generate) as mocked:
            app.run(); self.assertEqual(mocked.call_count,0) # no automatic initial case download
            app.session_state['test_image_request']='case'; app.run()
            self.assertFalse(app.exception)
            self.assertEqual(mocked.call_count,1)
            self.assertTrue(any(s.label=='Satellite image' for s in app.selectbox))
            app.run(); self.assertEqual(mocked.call_count,1)
    def test_failed_click_does_not_loop_and_retry_is_explicit(self):
        app=self.app()
        with patch('dashboard_setup.generate_satellite_image',side_effect=RuntimeError('network unavailable')) as mocked:
            app.session_state['test_image_request']='case'; app.run()
            self.assertFalse(app.exception)
            self.assertEqual(mocked.call_count,1)
            app.run(); self.assertEqual(mocked.call_count,1)
            next(b for b in app.button if b.label=='Retry satellite generation').click().run()
            self.assertEqual(mocked.call_count,2)
            self.assertFalse(app.exception)

if __name__=='__main__': unittest.main()
