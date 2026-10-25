import unittest
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import xarray as xr
from dashboard_noise import read_retrieval, nearest_noise, filter_metadata, spectrum_table, separated, noise_figure
from dashboard_data import signature

class NoiseTests(unittest.TestCase):
    def test_output_record_floor_and_flag(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'out.nc'
            ds=xr.Dataset({
                'obs_flag': ('obs_dim',[1,1,3]),
                'obs_dimension': ('obs_dim',[2350.,2380.,0.]),
                'obs_vector_uncertainty': (('time','obs_dim'),[[.05,.08,.5],[.1,.2,.5]]),
                'forward_calc': (('time','obs_dim'),[[-777.,2.,10.],[-777.,2.,10.]])
            },attrs={'VIP_irs_min_noise_wnum':'2300,2400','VIP_irs_min_noise_spec':'0.02,0.04','VIP_irs_min_noise_flag':0})
            ds.to_netcdf(p)
            wn,n,f,src,enabled=read_retrieval(signature(p),1)
            np.testing.assert_allclose(n,[.1,.2])
            np.testing.assert_allclose(f,[.03,.036])
            self.assertEqual(src,'Recorded VIP')
            self.assertEqual(enabled,'0')

    def test_filters_intersect_and_missing_only_when_enabled(self):
        f=pd.DataFrame({'Season':['JJA','JJA','DJF'],'Classification':['clear','cloudy','clear'],
            'Day/night':['Day','Night','Day'],'pwv_mm':[30.,np.nan,5.],'aod':[.1,.2,np.nan]})
        self.assertEqual(len(filter_metadata(f,{},{})),3)
        out=filter_metadata(f,{'Season':['JJA'],'Day/night':['Day']},{'pwv_mm':(20,40),'aod':(0,.15)})
        self.assertEqual(out.index.tolist(),[0])
        self.assertTrue(filter_metadata(f,{'Season':[]},{}).empty)

    def test_nearest_noise_time_and_no_extrapolation(self):
        t=pd.Timestamp('2025-01-02T00:00Z')
        summaries=[('a',(pd.DatetimeIndex([t-pd.Timedelta(seconds=20)]),np.array([2000.,2100.]),np.array([[.1,.2]]))),
                   ('b',(pd.DatetimeIndex([t+pd.Timedelta(seconds=5)]),np.array([2000.,2100.]),np.array([[.3,.5]])))]
        n,path,offset=nearest_noise(summaries,t,np.array([1900.,2050.]),30)
        self.assertEqual(path,'b')
        self.assertEqual(offset,5)
        self.assertTrue(np.isnan(n[0]))
        self.assertAlmostEqual(n[1],.4)
        with self.assertRaises(ValueError): nearest_noise(summaries,t,np.array([2050.]),1)

    def test_case_mean_counts_and_gaps(self):
        rows=[('a','A',np.array([2000.,2001.,2300.]),np.array([1.,2.,3.]),np.array([.1,.1,.1])),
              ('b','B',np.array([2000.,2001.]),np.array([3.,np.nan]),np.array([.1,.1]))]
        table=spectrum_table(rows)
        fig,mean=noise_figure(table,'Ch2_B19','Instrument')
        self.assertEqual(mean['count'].tolist(),[2,1,1])
        self.assertEqual(mean.noise.tolist(),[2.,2.,3.])
        x,y=separated(np.array([2000.,2001.,2002.,2300.]),np.ones(4))
        self.assertTrue(np.isnan(x).any())
        self.assertEqual(fig.data[0].line.width,1)

    def test_summary_reader_and_page(self):
        from dashboard_noise import read_summary
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'aerisum.20250101.nc'
            xr.Dataset({'SkyNENCh2':(('time','wnum2'),[[.1,.2,.3]])},
                coords={'time':pd.to_datetime(['2025-01-01T12:00']), 'wnum2':[2300.,2350.,2400.]}).to_netcdf(p)
            times,wn,n=read_summary(signature(p),2)
            self.assertEqual(n.shape,(1,3))
            r=Path(root)/'retrieval.nc'
            xr.Dataset({'obs_flag':('obs_dim',[1,1]),'obs_dimension':('obs_dim',[2350.,2400.]),
                'obs_vector_uncertainty':(('time','obs_dim'),[[.1,.2]])}).to_netcdf(r)
            script = """
import streamlit as st
import pandas as pd
from types import SimpleNamespace
from dashboard_noise import render_noise
t=pd.Timestamp('2025-01-01T12:00Z')
cases=pd.DataFrame(dict(case_id=['a'], sounding_time=[t],retrieval_time=[t],
category=['clear_sky'],asi_state=['clear_sky'],radiance_state=['clear_sky']))
index=pd.DataFrame(dict(model=['Ch2_B19'],time=[t],status=['usable'],file=[RETRIEVAL],profile_index=[0]))
config=SimpleNamespace(SITE='sgp',site_coordinates={'sgp':[-97.,36.]},SUM_DIR=ROOT,MASTER_DATA_FOLDER='')
render_noise(cases,index,['Ch2_B19'],{},config,60.,
lambda fig,name: st.plotly_chart(fig,key=name),lambda *args: None)
""".replace('RETRIEVAL',repr(str(r))).replace('ROOT',repr(root))
            app=AppTest.from_string(script).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')),1, str([(x.type, getattr(x,'value','')) for x in app if x.type in ('caption','dataframe','warning','info')]))
            app.radio(key='noise_source').set_value('Effective retrieval uncertainty').run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')),1, str([(x.type, getattr(x,'value','')) for x in app if x.type in ('caption','dataframe','warning','info')]))
