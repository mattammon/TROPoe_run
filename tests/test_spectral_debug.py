import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import xarray as xr

import spectral_debug as debug


def fixture(gamma=3.):
    rng=np.random.default_rng(25)
    n,m=8,7
    t=rng.normal(size=(n,n));sa=t@t.T+np.eye(n)
    t=rng.normal(size=(m,m));se=t@t.T+np.eye(m)*.8
    p=np.linalg.inv(se);pa=np.linalg.inv(sa)
    k=rng.normal(size=(m,n))*.2
    xa=np.array([20.,15.,10.,8.,5.,2.,.1,.2])
    xn=xa+rng.normal(size=n)*.1
    y=rng.normal(size=m)+10
    fx=y-rng.normal(size=m)*.1
    b=gamma*pa+k.T@p@k
    g=np.linalg.solve(b,k.T@p)
    xnext=xa+g@(y-fx+k@(xn-xa))
    inv=np.linalg.inv(b)
    sop=inv@(gamma**2*pa+k.T@p@k)@inv
    raw=dict(Y=y,Xa=xa,Sa=sa,SaInv=pa,SmInv=p,Xn=xn,Xnp1=xnext,
             Kij=k,Gain=g,B=b,Sop=sop,Akern=(g@k).T,FXn=fx)
    meta=dict(z=np.array([0.,1.,2.]),Xa=xa.copy(),Sa=sa.copy(),Xop=xn.copy(),Akernal=raw['Akern'].copy(),
              obs_vector=y.copy(),obs_dimension=np.array([2000.,2001.,2010.,2011.,2020.,0.,0.]),
              obs_flag=np.array([1,1,1,1,1,5,6]),obs_vector_uncertainty=np.sqrt(np.diag(se)),
              version='test-09ab443',qc=dict(gamma=gamma,qc_flag=0.,rmsa=.8,converged_flag=1.))
    return raw,meta,se


def write_fixture(root):
    raw,meta,_=fixture()
    attempt=Path(root)/'202501011200'/'Ch2_B25'/'attempt'
    work=attempt/'work';work.mkdir(parents=True)
    out=attempt/'output';out.mkdir()
    for name,a in raw.items():
        # Upstream stores Xnp1 as a column, other vectors as 1-D.
        a=a[:,None] if name=='Xnp1' else a
        xr.Dataset({'var':(tuple('d'+str(i) for i in range(a.ndim)),a)}).to_netcdf(work/f'debug_output.{name}.iter_0.cdf')
    # A later proposal that is not the final state must not enter cohort results.
    for name,a in raw.items():
        if name in debug.CONSTANTS:continue
        if name in ('Xn','Xnp1'):a=a+.2
        xr.Dataset({'var':(tuple('d'+str(i) for i in range(a.ndim)),a)}).to_netcdf(work/f'debug_output.{name}.iter_1.cdf')
    ds=xr.Dataset(coords={'time':pd.to_datetime(['2025-01-01T12:00:05']),'height':[0.,1.,2.]})
    ds.height.attrs['units']='km'
    for key in ('Xa','Xop'):
        ds[key]=(('state',),meta[key]) if key=='Xa' else (('time','state'),meta[key][None,:])
    for key in ('Sa','Akernal'):
        ds[key]=(('state','state2'),meta[key]) if key=='Sa' else (('time','state','state2'),meta[key][None,:,:])
    for key in ('arb1','arb2'):ds[key]=( ('state' if key=='arb1' else 'state2',),[1,1,1,2,2,2,3,4])
    for key in ('obs_dimension','obs_flag'):ds[key]=('obs',meta[key])
    for key in ('obs_vector','obs_vector_uncertainty'):ds[key]=(('time','obs'),meta[key][None,:])
    ds['temperature']=(('time','height'),meta['Xop'][None,:3]);ds.temperature.attrs['units']='degC'
    ds['waterVapor']=(('time','height'),meta['Xop'][None,3:6]);ds.waterVapor.attrs['units']='g/kg'
    for key,value in meta['qc'].items():ds[key]=('time',[value])
    ds.attrs['algorithm_code_version']='test-09ab443'
    file=out/'tropoeOutput_Ch2_B25.20250101.120005.nc';ds.to_netcdf(file)
    (attempt/'run.json').write_text(json.dumps(dict(requested_case_time='202501011200',model='Ch2_B25',status='finished')))
    return attempt,work,file


class SpectralDebugTests(unittest.TestCase):
    def test_zero_gain_opaque_sentinel_is_safe_despite_positive_precision(self):
        raw,meta,_=fixture()
        raw['SmInv']=np.diag(np.diag(raw['SmInv']))
        raw['Kij'][0]=0.
        raw['FXn'][0]=-777.
        k,p=raw['Kij'],raw['SmInv']
        b=3*raw['SaInv']+k.T@p@k
        g=np.linalg.solve(b,k.T@p)
        raw.update(B=b,Gain=g,Akern=(g@k).T)
        raw['Xnp1']=raw['Xa']+g@(raw['Y']-raw['FXn']+k@(raw['Xn']-raw['Xa']))
        a=debug.analyze(raw,meta)
        self.assertEqual(a['sentinel_inactive'],1)
        self.assertEqual(a['diagnostic_residual'][0],0.)
        np.testing.assert_array_equal(a['contributions'][:,0],0.)
        np.testing.assert_allclose(debug.local_experiment(a)['state'],raw['Xnp1'])
        w=debug.feature_weights(meta['z'],8,'T',0.,2.)
        table=debug.observation_table(a,w)
        self.assertTrue(table.sentinel_excluded.iloc[0])
        self.assertEqual(table.likelihood_pull.iloc[0],0.)
        # Exercise the actual across-case entry point, including final matching,
        # NetCDF reload, both variables, grouping, and the accepted-row count.
        meta['Akernal']=raw['Akern'].copy()
        with tempfile.TemporaryDirectory() as root:
            with patch(__name__+'.fixture',return_value=(raw,meta,None)):
                attempt,work,file=write_fixture(root)
            jobs=[dict(case_id='opaque',model='Ch2_B25',attempt=str(attempt),
                       work=str(work),retrieval_time='2025-01-01T12:00Z')]
            metrics,spectra,issues=debug.summarize_cohort(jobs,0.,2.,10.)
            self.assertTrue(issues.empty,issues.to_string())
            self.assertEqual(set(metrics.variable),{'T','q'})
            self.assertTrue(metrics.zero_influence_sentinel_rows.eq(1).all())
            self.assertFalse(spectra.empty)

    def test_symmetry_uses_covariance_scale_not_near_zero_cross_terms(self):
        a=np.array([[4.,1e-10,0.],[2e-8,9.,0.],[0.,0.,40000.]])
        np.testing.assert_array_equal(debug.symmetric(a,'Sa'),(a+a.T)/2)
        # A large auxiliary-state variance must not hide a bad T/q cross term.
        a[0,1]=.01
        with self.assertRaisesRegex(ValueError,'substantial asymmetry'):
            debug.symmetric(a,'Sa')
        with self.assertRaisesRegex(ValueError,'nonfinite'):
            debug.symmetric(np.array([[np.nan]]),'Sa')
        with self.assertRaisesRegex(ValueError,'shape='):
            debug.symmetric(np.zeros((2,3)),'Sa')

    def test_exact_attribution_damping_modes_and_step(self):
        raw,meta,_=fixture()
        a=debug.analyze(raw,meta)
        self.assertAlmostEqual(a['gamma'],3.)  # Missing scalar gfac is reconstructed.
        np.testing.assert_allclose(a['contributions'].sum(axis=1),raw['Xnp1']-raw['Xa'])
        np.testing.assert_allclose(a['obs_step']+a['prior_step'],raw['Xnp1']-raw['Xn'],atol=1e-14)
        self.assertAlmostEqual(a['information_fraction'].sum(),np.trace(a['A']))
        self.assertTrue(debug.final_match(raw,meta))
        self.assertGreater(np.linalg.norm(raw['Xnp1']-meta['Xop']),0.)

    def test_correlated_withholding_is_marginal_not_conditional(self):
        raw,meta,se=fixture()
        a=debug.analyze(raw,meta)
        baseline=debug.local_experiment(a)
        np.testing.assert_allclose(baseline['state'],raw['Xnp1'],atol=1e-12)
        omit=np.array([True,False,False,False,False,False,False]);keep=np.flatnonzero(~omit)
        result=debug.local_experiment(a,prior_scale=4.,omit=omit)
        k=raw['Kij'][keep];p=np.linalg.inv(se[np.ix_(keep,keep)])
        g=np.linalg.solve(3./4*raw['SaInv']+k.T@p@k,k.T@p)
        np.testing.assert_allclose(result['state'],raw['Xa']+g@a['innovation'][keep],atol=1e-12)
        self.assertGreater(debug.local_experiment(a,4.)['dfs'],baseline['dfs'])

    def test_groups_preserve_auxiliary_rows_and_directional_cost(self):
        raw,meta,_=fixture();a=debug.analyze(raw,meta)
        w=debug.feature_weights(meta['z'],8,'q',1.,1.,True,1.)
        table=debug.observation_table(a,w,10.,-1.)
        self.assertEqual(table.group.iloc[-2:].tolist(),['Surface T','Surface q'])
        self.assertAlmostEqual(table.feature_contribution.sum(),w@(raw['Xnp1']-raw['Xa']))
        self.assertAlmostEqual(table.absolute_share.sum(),1.)
        direction=-w/np.max(np.abs(w));epsilon=1e-6
        r=a['residual'];v=raw['Kij']@direction;p=raw['SmInv']
        score=(.5*r@p@r-.5*(r-epsilon*v)@p@(r-epsilon*v))/epsilon
        self.assertAlmostEqual(table.likelihood_pull.sum(),score,places=6)
        labels,c,dfs=debug.grouped_contributions(a,table,np.arange(8))
        np.testing.assert_allclose(c.sum(axis=1),raw['Xnp1']-raw['Xa'])
        self.assertAlmostEqual(dfs.sum(),np.trace(a['A']))

    def test_mismatch_orientation_and_sentinels_rejected(self):
        raw,meta,_=fixture();meta['Y']=np.zeros(7)
        bad=dict(meta,obs_vector=meta['obs_vector']+1)
        with self.assertRaisesRegex(ValueError,'Companion metadata mismatch'):debug.analyze(raw,bad)
        wrong=dict(raw,Akern=raw['Akern'].T)
        with self.assertRaisesRegex(ValueError,'does not close'):debug.analyze(wrong,meta)
        sentinel=dict(raw,FXn=raw['FXn'].copy());sentinel['FXn'][0]=-777
        sentinel['Xnp1']=raw['Xa']+raw['Gain']@(raw['Y']-sentinel['FXn']+raw['Kij']@(raw['Xn']-raw['Xa']))
        with self.assertRaisesRegex(ValueError,'sentinel'):debug.analyze(sentinel,meta)

    def test_archive_final_iteration_and_cohort(self):
        with tempfile.TemporaryDirectory() as root:
            attempt,work,file=write_fixture(root)
            inventory,errors=debug.inventory(root)
            self.assertFalse(errors);self.assertEqual(len(inventory),1)
            file2,record=debug.companion_in_attempt(attempt,'2025-01-01T12:00Z')
            self.assertEqual(file2,str(file));self.assertEqual(record,0)
            meta=debug.read_companion(debug.signature(file),0)
            self.assertEqual(debug.matching_final_steps(work,meta),[0])
            raw=debug.read_iteration(debug.iteration_signature(work,1))
            self.assertIn('Sa',raw)  # Constants fall back to iteration 0 only.
            jobs=[dict(case_id='a',model='Ch2_B25',attempt=str(attempt),work=str(work),retrieval_time='2025-01-01T12:00Z')]
            metrics,spectra,issues=debug.summarize_cohort(jobs,0.,2.,10.)
            self.assertTrue(issues.empty,issues.to_string())
            self.assertEqual(set(metrics.variable),{'T','q'})
            self.assertTrue(metrics.iteration.eq(0).all())
            np.testing.assert_allclose(metrics.gamma,[3.,3.])
            for _,group in spectra.groupby('variable'):
                self.assertAlmostEqual(group.absolute_share.sum(),1.)
            before=debug.cohort_signatures([str(attempt)])
            p=work/'debug_output.Xn.iter_0.cdf';p.touch()
            self.assertNotEqual(before,debug.cohort_signatures([str(attempt)]))

    def test_missing_matrix_and_invalid_layer(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError,'Missing debug'):debug.iteration_signature(root,0)
        with self.assertRaisesRegex(ValueError,'flanking'):debug.feature_weights(np.array([0.,1.,2.]),8,'T',0.,1.,True)


class SpectralLabUITests(unittest.TestCase):
    def test_views_and_cohort(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as root:
            write_fixture(root)
            script='''
import pandas as pd
import streamlit as st
from types import SimpleNamespace
from dashboard_spectral_lab import render_spectral_lab
cases=pd.DataFrame([dict(case_id='case',sounding_time=pd.Timestamp('2025-01-01T12:00Z'),retrieval_time=pd.Timestamp('2025-01-01T12:00Z'),sounding_file='missing.nc',category='clear_sky',asi_state='clear_sky',radiance_state='clear_sky')])
config=SimpleNamespace(RETRIEVAL_DEBUG_DIR=ROOT,SITE='sgp',site_coordinates={'sgp':[-97.5,36.6]})
source=dict(master=ROOT+'/master.csv',output=ROOT,master_hash='test')
def chart(fig,key):st.plotly_chart(fig,key=key)
render_spectral_lab(cases,pd.DataFrame(),['Ch2_B25'],source,config,60.,chart)
'''.replace('ROOT',repr(root))
            app=AppTest.from_string(script).run(timeout=30)
            self.assertFalse(app.exception)
            for view in ('Observations vs prior','Band / prior experiments','Matrices and provenance'):
                app.radio(key='spectral_diagnostic').set_value(view).run(timeout=30)
                self.assertFalse(app.exception,view)
                if view=='Band / prior experiments':
                    app.checkbox(key='spectral_withhold').check().run(timeout=30)
                    self.assertFalse(app.exception)
                    app.select_slider(key='spectral_prior_scale').set_value(4.).run(timeout=30)
                    self.assertFalse(app.exception)
            app.radio(key='spectral_diagnostic').set_value('Iteration history').run(timeout=30)
            app.button(key='spectral_history').click().run(timeout=30)
            self.assertFalse(app.exception)
            app.radio(key='spectral_lab_view').set_value('Across cases').run(timeout=30)
            self.assertFalse(app.exception)
            app.button(key='spectral_build_cohort').click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertGreater(len(app.dataframe),0)
            app.selectbox(key='spectral_cohort_group').set_value('PWV bin').run(timeout=30)
            self.assertFalse(app.exception)
            app.radio(key='spectral_cohort_spec_variable').set_value('q').run(timeout=30)
            self.assertFalse(app.exception)


if __name__=='__main__':unittest.main()
