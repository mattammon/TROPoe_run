"""Read-only, unit-aware analysis of TROPoe iteration NetCDF debug matrices.

Conventions verified against upstream 09ab443: K is obs x state, G is
state x obs, saved Akern is (G K).T. No pickle or object-NPY deserialization.
"""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy.linalg import eigh, pinvh

CONSTANTS = ('Y', 'Xa', 'Sa', 'SaInv', 'SmInv')
# Include in dashboard cache keys whenever diagnostic interpretation changes.
ANALYSIS_VERSION = 'final-state-height-correlation-v4'
REQUIRED = CONSTANTS + ('Xn', 'Xnp1', 'Kij', 'Gain', 'B', 'Sop', 'Akern')
FLAGS = {1: 'Infrared', 2: 'Microwave', 3: 'External T profile',
         4: 'External q profile', 5: 'Surface T', 6: 'Surface q',
         7: 'Model T', 8: 'Model q', 9: 'Surface CO2', 10: 'Scanning microwave',
         11: 'Previous retrieval T', 12: 'Previous retrieval q', 13: 'Cloud RH'}


def signature(path):
    p = Path(path).expanduser().resolve()
    s = p.stat()
    return str(p), s.st_mtime_ns, s.st_size


def inventory(root):
    """Discover isolated attempts from run.json; do not scan the retrieval tree."""
    root = Path(root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError('Debug archive not found: '+str(root))
    rows, issues = [], []
    # Known archive depth; do not descend into thousands of LBL working files.
    paths = {root/'run.json'} if (root/'run.json').is_file() else set()
    for pattern in ('*/run.json','*/*/run.json','*/*/*/run.json'):
        paths.update(root.glob(pattern))
    for path in sorted(paths):
        try:
            meta = json.loads(path.read_text())
            stamp = pd.to_datetime(str(meta['requested_case_time']), format='%Y%m%d%H%M', utc=True)
            work = path.parent/'work'
            steps = iterations(work)
            rows.append(dict(attempt=str(path.parent.resolve()), work=str(work.resolve()),
                case_minute=stamp.strftime('%Y%m%d%H%M'), model=meta['model'],
                status=meta.get('status', 'unknown'), iterations=len(steps),
                updated_ns=path.stat().st_mtime_ns))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            issues.append(dict(path=str(path), error=str(exc)))
    return pd.DataFrame(rows, columns=['attempt','work','case_minute','model','status','iterations','updated_ns']), issues


def iterations(work):
    return sorted({int(re.search(r'\.iter_(\d+)\.cdf$', p.name).group(1))
                   for p in Path(work).glob('debug_output.Kij.iter_*.cdf')
                   if re.search(r'\.iter_(\d+)\.cdf$', p.name)})


def iteration_signature(work, step):
    files = {}
    for name in REQUIRED + ('FXn', 'gfac'):
        p = Path(work)/f'debug_output.{name}.iter_{int(step)}.cdf'
        if not p.is_file() and name in CONSTANTS:
            p = Path(work)/f'debug_output.{name}.iter_0.cdf'
        if p.is_file():
            files[name] = signature(p)
        elif name != 'gfac':
            raise ValueError('Missing debug matrix: '+str(p))
    return tuple(sorted(files.items()))


def read_iteration(files):
    result = {}
    for name, sig in files:
        with xr.open_dataset(sig[0], decode_cf=False) as ds:
            if 'var' not in ds:
                raise ValueError('Expected debug variable "var": '+sig[0])
            a = np.asarray(ds['var'], dtype=float)
        result[name] = a.reshape(-1) if name in ('Xa','Xn','Xnp1','Y','FXn','gfac') else a
    return result


def read_companion(file_signature, record):
    with xr.open_dataset(file_signature[0]) as ds:
        if record < 0 or record >= ds.sizes.get('time', 0):
            raise ValueError('Invalid companion retrieval record')
        sample = ds.isel(time=int(record))
        z = np.asarray(ds.height, float)
        if str(ds.height.attrs.get('units','')).lower() != 'km' or z.ndim != 1 or not np.isfinite(z).all() or np.any(np.diff(z) <= 0):
            raise ValueError('Expected increasing native height in km AGL')
        n = len(z)
        for key in ('arb1','arb2'):
            if not np.array_equal(np.asarray(sample[key])[:2*n], np.r_[np.ones(n), np.full(n, 2)]):
                raise ValueError('Unsupported T/q state ordering in '+key)
        for key, valid in [('temperature', ('degc','c','celsius')), ('waterVapor', ('g/kg','gkg-1'))]:
            if str(sample[key].attrs.get('units','')).lower().replace(' ','') not in valid:
                raise ValueError('Unsupported state units in '+key)
        values = {key: np.asarray(sample[key], float) for key in
                  ('Xa','Xop','Sa','Akernal','obs_vector','obs_dimension','obs_flag','obs_vector_uncertainty')}
        values.update(z=z, time=str(sample.time.values),
                      version=str(ds.attrs.get('algorithm_code_version', 'unknown')),
                      qc={key: float(sample[key]) for key in ('gamma','qc_flag','converged_flag','rmsa','rmsr') if key in sample})
        flags, coordinates=values['obs_flag'],values['obs_dimension']
        if not np.isfinite(flags).all() or not np.equal(flags,np.floor(flags)).all():
            raise ValueError('Invalid observation flags')
        ir=flags==1
        if not np.isfinite(coordinates[ir]).all() or np.any(coordinates[ir]<=0):
            raise ValueError('Invalid infrared wavenumber metadata')
    return values


def companion_in_attempt(attempt, target, tolerance=60.):
    """Only the archived output from this attempt can supply automatic metadata."""
    found = []
    for path in sorted((Path(attempt)/'output').glob('*.nc')):
        with xr.open_dataset(path) as ds:
            times = pd.to_datetime(ds.time.values, utc=True)
            delta = np.abs((times-pd.to_datetime(target, utc=True)).total_seconds())
            found.extend((str(path), int(i)) for i in np.flatnonzero(delta <= tolerance))
    if len(found) != 1:
        raise ValueError(f'Expected exactly one archived output record near the case time; found {len(found)}. Use explicit companion selection for a failed/legacy attempt.')
    return found[0]


def relative_error(actual, expected):
    return float(np.linalg.norm(actual-expected)/max(np.linalg.norm(expected), 1e-14))


def symmetric(a, name):
    a = np.asarray(a, dtype=float)
    if a.ndim != 2 or a.shape[0] != a.shape[1]:
        raise ValueError(f'{name} must be square; shape={a.shape}')
    if not np.isfinite(a).all():
        raise ValueError(f'{name} contains {np.sum(~np.isfinite(a))} nonfinite entries')
    # Covariances mix units and have cross terms near zero. Elementwise relative
    # tolerance wrongly rejects roundoff in those terms; a global matrix norm
    # would instead hide errors in small-unit blocks (e.g. beside cloud states).
    # Normalize by sqrt(|diagonal_i diagonal_j|), i.e. correlation scale.
    diagonal = np.abs(np.diag(a))
    floor = max(float(diagonal.max())*np.finfo(float).eps, np.finfo(float).tiny)
    scale = np.sqrt(np.outer(np.maximum(diagonal, floor), np.maximum(diagonal, floor)))
    discrepancy = np.abs(a-a.T)/scale
    maximum = float(discrepancy.max())
    if maximum > 1e-5:
        i,j = np.unravel_index(np.argmax(discrepancy), a.shape)
        raise ValueError(f'{name} has substantial asymmetry: max diagonal-scaled difference '
                         f'{maximum:.3g} exceeds 1e-5 at [{i},{j}] '
                         f'({a[i,j]:.8g} versus {a[j,i]:.8g})')
    return (a+a.T)/2


def psd_root(a, name):
    a = symmetric(a, name)
    e, v = eigh(a)
    scale = max(np.max(np.abs(e)), 1e-30)
    if e.min() < -scale*1e-7:
        raise ValueError(name+' is not positive semidefinite')
    return (v*np.sqrt(np.maximum(e, 0)))@v.T, int(np.sum(e > scale*np.finfo(float).eps*len(e)))


def analyze(raw, meta):
    """Validate algebra/metadata before attaching physical labels or attributing spectra."""
    r = {k: np.asarray(v, float) for k,v in raw.items()}
    m, n = len(r['Y']), len(r['Xa'])
    shapes = {'Kij': (m,n), 'Gain': (n,m), 'Sa': (n,n), 'SaInv': (n,n),
              'SmInv': (m,m), 'B': (n,n), 'Sop': (n,n), 'Akern': (n,n),
              'Xn': (n,), 'Xnp1': (n,), 'FXn': (m,)}
    for key, shape in shapes.items():
        if r[key].shape != shape or not np.isfinite(r[key]).all():
            raise ValueError('Invalid shape or nonfinite values in '+key)
    if not np.isfinite(r['Y']).all() or not np.isfinite(r['Xa']).all():
        raise ValueError('Nonfinite observation or prior vector')
    for key, other in [('Y','obs_vector'), ('Xa','Xa'), ('Sa','Sa')]:
        if r[key].shape != meta[other].shape or not np.allclose(r[key], meta[other], rtol=2e-5, atol=2e-6):
            raise ValueError('Companion metadata mismatch: '+key+' differs. Do not combine attempts or observation records.')
    if meta['obs_flag'].shape != (m,) or meta['obs_dimension'].shape != (m,) or meta['Xop'].shape != (n,):
        raise ValueError('Companion observation/state dimensions disagree')
    sa, p, precision = symmetric(r['Sa'],'Sa'), symmetric(r['SaInv'],'SaInv'), symmetric(r['SmInv'],'SmInv')
    sroot, rank = psd_root(sa, 'Sa')
    k, g = r['Kij'], r['Gain']
    h = k.T@precision@k
    a = g@k
    gamma = float(np.sum((r['B']-h)*p)/max(np.sum(p*p), 1e-30))
    gamma_source = 'Inferred from B − Kᵀ SmInv K = γ SaInv'
    if 'gfac' in r:
        gamma = float(r['gfac'].item())
        gamma_source = 'Saved gfac'
    if not np.isfinite(gamma) or gamma <= 0:
        raise ValueError('Cannot determine a positive damping/prior weight gamma')
    residual = r['Y']-r['FXn']
    d = residual+k@(r['Xn']-r['Xa'])
    proposed = r['Xa']+g@d
    checks = dict(update=relative_error(proposed-r['Xa'], r['Xnp1']-r['Xa']),
                  saved_kernel=relative_error(a, r['Akern'].T),
                  hessian=relative_error(r['B'], gamma*p+h),
                  gain_equation=relative_error(r['B']@g, k.T@precision))
    if max(checks.values()) > 1e-4:
        raise ValueError('Debug algebra does not close (wrong orientation, mixed samples, or unsupported solver): '+str(checks))
    suspicious = np.isin(r['Y'], [-777.,-999.,-9999.]) | np.isin(r['FXn'], [-777.,-999.,-9999.])
    active = np.any(g != 0, axis=0) | np.any(k != 0, axis=1)
    off_diagonal = precision.copy()
    np.fill_diagonal(off_diagonal, 0.)
    # TROPoe can retain positive diagonal precision for an opaque element while
    # explicitly zeroing its K row and G column. Such a row has no state effect.
    # Require exact zeros and no precision coupling: never silently mask a row
    # whose sentinel could propagate to other observations or local experiments.
    unsafe = suspicious & (active | np.any(off_diagonal != 0, axis=0))
    if np.any(unsafe):
        raise ValueError(f'{np.sum(unsafe)} active observations contain sentinel candidates (-777/-999/-9999). Nonzero Gain, Jacobian, or cross-observation precision prevents safe attribution; inspect these raw rows first.')
    diagnostic_residual = residual.copy()
    diagnostic_residual[suspicious] = 0.
    eig, modes = eigh(symmetric(sroot@h@sroot, 'Whitened information'))
    if eig.min() < -max(np.max(np.abs(eig)),1)*1e-7:
        raise ValueError('Negative observation information: check SmInv')
    order = np.argsort(eig)[::-1]
    eig, modes = np.maximum(eig[order],0), modes[:,order]
    fractions = eig/(eig+gamma)
    sigma = np.sqrt(np.maximum(np.diag(sa),0))
    prior_response = np.eye(n)-a
    prior_variance = np.diag(prior_response@sa@prior_response.T)
    prior_sensitivity = np.sqrt(np.maximum(prior_variance,0))/np.where(sigma>0,sigma,np.nan)
    return dict(raw=r, meta=meta, K=k, G=g, A=a, prior_response=prior_response,
                gamma=gamma, gamma_source=gamma_source, checks=checks,
                residual=residual, diagnostic_residual=diagnostic_residual,
                sentinel=suspicious, innovation=d, proposed=proposed,
                contributions=g*d[None,:], obs_step=g@residual,
                prior_step=-prior_response@(r['Xn']-r['Xa']),
                dfs_by_obs=np.sum(g*k.T,axis=0), sigma=sigma,
                prior_sensitivity=prior_sensitivity, sa_root=sroot, prior_rank=rank,
                eigenvalues=eig, modes=modes, information_fraction=fractions,
                inactive=int((~active).sum()), sentinel_inactive=int(suspicious.sum()),
                prior_id=hashlib.sha256(sa.tobytes()+r['Xa'].tobytes()).hexdigest()[:12])


def final_match(raw, meta):
    """Debug calculations are at Xn, not at the proposed Xnp1."""
    return (raw['Xn'].shape == meta['Xop'].shape
            and np.allclose(raw['Xn'], meta['Xop'], rtol=2e-5, atol=2e-4)
            and np.allclose(raw['Akern'], meta['Akernal'], rtol=3e-4, atol=3e-6))


def matching_final_steps(work, meta):
    matches = []
    for step in iterations(work):
        try:
            files = tuple((key, signature(Path(work)/f'debug_output.{key}.iter_{step}.cdf'))
                          for key in ('Xn','Akern'))
            if final_match(read_iteration(files), meta):
                matches.append(step)
        except (OSError, ValueError, KeyError):
            continue
    return matches


def cohort_signatures(attempts):
    """Cache key follows every matrix/output/metadata file, not just directory names."""
    result = []
    for attempt in sorted(set(attempts)):
        root = Path(attempt)
        for path in [root/'run.json', *sorted((root/'work').glob('debug_output.*.cdf')),
                     *sorted((root/'output').glob('*.nc'))]:
            result.append(signature(path))
    return tuple(result)


def summarize_cohort(jobs, bottom, top, bin_width, progress=None, sounding_loader=None, profile_rows=None, height_grid=None):
    """One final-matched iteration per case/band; invalid attempts are exclusions."""
    metrics, spectra, issues = [], [], []
    for number, row in enumerate(jobs, 1):
        if progress:
            progress(number, len(jobs))
        try:
            path, record = companion_in_attempt(row['attempt'], row['retrieval_time'])
            meta = read_companion(signature(path), record)
            step, match_info = select_final_step(row['work'],meta)
            a = analyze(read_iteration(iteration_signature(row['work'], step)), meta)
            common = {key: row[key] for key in ('case_id','model','attempt')}
            common['iteration'] = step
            common.update(match_info)
            common['zero_influence_sentinel_rows'] = a['sentinel_inactive']
            case_rows = case_metrics(a,bottom,top)
            sounding, accuracy_error = None, 'Sounding comparison not requested'
            if sounding_loader is not None:
                try:
                    sounding = sounding_loader(row)
                    accuracy_error = ''
                except Exception as exc:
                    accuracy_error = str(exc)
            for variable in ('T','q'):
                w = feature_weights(meta['z'], len(a['proposed']),variable,bottom,top)
                table = observation_table(a,w,bin_width)
                ids = np.flatnonzero(w)
                labels, _, dfs = grouped_contributions(a,table,ids)
                grouped = table.groupby('group', sort=False).agg(
                    contribution=('feature_contribution','sum'), absolute_share=('absolute_share','sum'),
                    absolute_contribution=('absolute_contribution','sum'), channels=('obs_index','size'),
                    bin_start=('bin_start','first'))
                grouped['layer_dfs'] = pd.Series(dict(zip(labels,dfs)))
                metric_row = next(m for m in case_rows if m['variable']==variable)
                metric_row['accuracy_error'] = accuracy_error
                if sounding is not None:
                    try:
                        accuracy = accuracy_attribution(a,table,sounding,variable,bottom,top)
                        metric_row.update(accuracy['stats'])
                        grouped['mse_improvement'] = accuracy['groups'].set_index('group').mse_improvement
                        if profile_rows is not None and height_grid is not None:
                            profile_rows.extend(dict(common,variable=variable,**p) for p in
                                profile_accuracy_pairs(a,table,sounding,variable,height_grid))
                    except Exception as exc:
                        metric_row['accuracy_error'] = str(exc)
                metrics.append(dict(common, **metric_row))
                for group, values in grouped.iterrows():
                    spectra.append(dict(common, variable=variable, spectral_group=group, **values.to_dict()))
        except Exception as exc:
            issues.append(dict(case_id=row['case_id'],model=row['model'],attempt=row['attempt'],error=str(exc)))
    return pd.DataFrame(metrics), pd.DataFrame(spectra), pd.DataFrame(issues)


def feature_weights(z, size, variable, bottom, top, contrast=False, flank=.5):
    selected = (z >= bottom) & (z <= top)
    if not selected.any():
        raise ValueError('No native levels in the selected layer')
    weights = selected.astype(float)/selected.sum()
    if contrast:
        lower = (z >= bottom-flank) & (z < bottom)
        upper = (z > top) & (z <= top+flank)
        if not lower.any() or not upper.any():
            raise ValueError('Contrast requires native levels in both flanking layers')
        weights -= .5*lower/lower.sum()+.5*upper/upper.sum()
    result = np.zeros(size)
    offset = 0 if variable == 'T' else len(z)
    result[offset:offset+len(z)] = weights
    return result


def observation_table(a, weights, width=10., amplitude=1.):
    """Signed feature attribution and likelihood pull; keep auxiliary observations separate."""
    if width <= 0:
        raise ValueError('Spectral bin width must be positive')
    meta, raw = a['meta'], a['raw']
    flags, wn = meta['obs_flag'].astype(int), meta['obs_dimension']
    feature_gain = weights@a['G']
    signed = feature_gain*a['innovation']
    abs_total = np.abs(signed).sum()
    perturbation = amplitude*weights/max(np.max(np.abs(weights)),1e-30)
    spectral_change = a['K']@perturbation
    # Full precision multiplication retains cross-observation covariance.
    score = spectral_change*(raw['SmInv']@a['diagnostic_residual'])
    group = [f'{np.floor(w/width)*width:g}–{(np.floor(w/width)+1)*width:g} cm⁻¹'
             if f == 1 and np.isfinite(w) else FLAGS.get(f, 'Observation flag '+str(f)) for f,w in zip(flags,wn)]
    return pd.DataFrame(dict(obs_index=np.arange(len(wn)), flag=flags, coordinate=wn,
        group=group, observed=raw['Y'], calculated=raw['FXn'], uncertainty=meta['obs_vector_uncertainty'],
        residual=a['residual'], sentinel_excluded=a['sentinel'], innovation=a['innovation'], feature_contribution=signed,
        absolute_contribution=np.abs(signed), absolute_share=np.abs(signed)/abs_total if abs_total else np.nan,
        feature_step=feature_gain*a['residual'], likelihood_pull=score, dfs=a['dfs_by_obs'],
        bin_start=np.where(flags==1,np.floor(wn/width)*width,np.nan)))


def grouped_contributions(a, table, state_indices):
    labels = list(dict.fromkeys(table.group))
    c, dfs = [], []
    for label in labels:
        obs = np.flatnonzero(table.group.eq(label))
        c.append(a['contributions'][np.ix_(state_indices,obs)].sum(axis=1))
        dfs.append((a['G'][np.ix_(state_indices,obs)]*a['K'][np.ix_(obs,state_indices)].T).sum())
    return labels, np.array(c).T, np.asarray(dfs)


def local_experiment(a, prior_scale=1., omit=None):
    """One frozen linear solve. Withholding marginalizes full observation covariance."""
    if prior_scale <= 0:
        raise ValueError('Prior covariance multiplier must be positive')
    raw = a['raw']
    k, precision = a['K'], raw['SmInv']
    keep = np.arange(k.shape[0])
    if omit is not None and np.any(omit):
        # Inactive zero-precision rows are excluded, not assigned zero variance.
        active = np.flatnonzero(np.any(np.abs(precision)>0,axis=1))
        block = precision[np.ix_(active,active)]
        e = np.linalg.eigvalsh(block)
        if not len(e) or e.min() <= e.max()*1e-12:
            raise ValueError('Withholding requires nonsingular active observation precision; cannot infer a marginal covariance safely')
        covariance = np.linalg.inv(block)
        positions = np.flatnonzero(~np.asarray(omit, bool)[active])
        keep = active[positions]
        if not len(keep):
            raise ValueError('The experiment removes every active observation')
        precision = np.linalg.inv(covariance[np.ix_(positions,positions)])
        k = k[keep]
    b = a['gamma']/prior_scale*raw['SaInv'] + k.T@precision@k
    gain = pinvh((b+b.T)/2)@k.T@precision
    kernel = gain@k
    x = raw['Xa']+gain@a['innovation'][keep]
    return dict(state=x, A=kernel, dfs=float(np.trace(kernel)), keep=keep)


def case_metrics(a, bottom, top):
    rows = []
    z, raw = a['meta']['z'], a['raw']
    n = len(z)
    for variable, offset in [('T',0),('q',n)]:
        ids = np.flatnonzero((z>=bottom)&(z<=top))+offset
        if not len(ids):
            raise ValueError('No native levels in cohort analysis layer')
        sigma = a['sigma'][ids]
        normalized = (a['proposed'][ids]-raw['Xa'][ids])/np.where(sigma>0,sigma,np.nan)
        rows.append(dict(variable=variable, layer_dfs=float(np.diag(a['A'])[ids].sum()),
            prior_sensitivity=float(np.nanmean(a['prior_sensitivity'][ids])),
            sigma_ratio=float(np.nanmean(np.sqrt(np.maximum(np.diag(raw['Sop'])[ids],0))/np.where(sigma>0,sigma,np.nan))),
            departure_prior_sigma=float(np.sqrt(np.nanmean(normalized**2))), native_levels=len(ids),
            gamma=a['gamma'], total_dfs=float(np.trace(a['A'])), prior_id=a['prior_id'],
            **{('final_gamma' if key=='gamma' else key):value for key,value in a['meta']['qc'].items()}))
    return rows


def accuracy_attribution(a, table, sounding, variable, bottom, top):
    """Exact additive allocation of prior-to-proposal squared-error reduction.

    This symmetric allocation shares cross terms among spectral contributions;
    it is not a channel-removal experiment or attribution of the saved final Xn.
    """
    z = np.asarray(a['meta']['z'])
    sz = np.asarray(sounding['z'], float)
    if len(sz) < 2 or not np.all(np.isfinite(sz)) or np.any(np.diff(sz) <= 0):
        raise ValueError('Sounding heights must be finite and strictly increasing')
    truth = np.interp(z, sz, sounding[variable], left=np.nan, right=np.nan)
    offset = 0 if variable == 'T' else len(z)
    levels = np.flatnonzero((z >= bottom) & (z <= top))
    ids = levels + offset
    prior, proposed, final = a['raw']['Xa'][ids], a['proposed'][ids], a['meta']['Xop'][ids]
    valid = np.isfinite(truth[levels]) & np.isfinite(prior) & np.isfinite(proposed) & np.isfinite(final)
    if not valid.any():
        raise ValueError('No finite radiosonde/retrieval pairs in this layer')
    labels, contributions, _ = grouped_contributions(a, table, ids)
    target = truth[levels]
    improvement = contributions * (2*target-prior-proposed)[:,None]
    improvement[~valid] = np.nan
    def rmse(x):
        return float(np.sqrt(np.mean((x[valid]-target[valid])**2)))
    stats = dict(prior_rmse=rmse(prior), proposed_rmse=rmse(proposed), saved_rmse=rmse(final),
                 accuracy_levels=int(valid.sum()), accuracy_total_levels=len(ids))
    stats['saved_rmse_improvement'] = stats['prior_rmse']-stats['saved_rmse']
    stats['proposed_mse_improvement'] = stats['prior_rmse']**2-stats['proposed_rmse']**2
    group_scores = pd.DataFrame({'group':labels, 'mse_improvement':np.nanmean(improvement,axis=0)})
    element_scores = a['contributions'][ids[valid]] * (2*target[valid]-prior[valid]-proposed[valid])[:,None]
    elements = table[['obs_index','flag','coordinate','group','absolute_share','feature_contribution']].copy()
    elements['mse_improvement'] = element_scores.mean(axis=0)
    return dict(stats=stats, groups=group_scores, improvement=improvement,
                labels=labels, z=z[levels], truth=target, valid=valid, elements=elements)


def channel_grid(values, labels, bin_starts, model, width):
    """Reindex binned IR values onto a numeric full-channel axis; gaps stay NaN."""
    low, high = (500.,1800.) if model == 'Ch1' else (1800.,3000.)
    starts = np.arange(np.floor(low/width)*width,high,width)
    output = np.full((len(values),len(starts)),np.nan)
    for i,label in enumerate(labels):
        start = bin_starts.get(label,np.nan)
        if np.isfinite(start):
            j = int(round((start-starts[0])/width))
            if 0 <= j < len(starts): output[:,j] = np.asarray(values)[:,i]
    return starts+width/2,output,(low,high)


def select_final_step(work, meta):
    """Closest verified saved-state/kernel match; iteration recency is irrelevant."""
    candidates = []
    for step in matching_final_steps(work, meta):
        raw = read_iteration(tuple((key, signature(Path(work)/f'debug_output.{key}.iter_{step}.cdf'))
                                   for key in ('Xn','Akern')))
        state_error = relative_error(raw['Xn'],meta['Xop'])
        kernel_error = relative_error(raw['Akern'],meta['Akernal'])
        candidates.append((state_error+kernel_error,step,state_error,kernel_error))
    if not candidates:
        raise ValueError('No debug Xn and Akern match the final saved solution; latest iteration is not a fallback')
    _,step,state_error,kernel_error = min(candidates)
    return step,dict(final_state_relative_error=state_error,final_kernel_relative_error=kernel_error,
                     matching_iterations=len(candidates),latest_available_iteration=max(iterations(work)))


def profile_accuracy_pairs(a, table, sounding, variable, grid):
    """One signed spectral-bin contribution/error-improvement pair per case/height.

    Interpolate states and contributions vertically, then compute absolute errors.
    No extrapolation, no filling NaNs, and no spectral interpolation. Contributions
    describe the proposal evaluated at final-matched Xn; error uses saved Xop.
    """
    z = np.asarray(a['meta']['z'])
    sz = np.asarray(sounding['z'],float)
    if len(sz)<2 or not np.all(np.isfinite(sz)) or np.any(np.diff(sz)<=0):
        raise ValueError('Sounding heights must be finite and strictly increasing')
    grid = np.asarray(grid,float)
    n = len(z); offset = 0 if variable=='T' else n
    ids = np.arange(n)+offset
    labels,c,_ = grouped_contributions(a,table,ids)
    def interp(values):return np.interp(grid,z,values,left=np.nan,right=np.nan)
    prior = interp(a['raw']['Xa'][ids]); final = interp(a['meta']['Xop'][ids])
    observed = np.interp(grid,sz,sounding[variable],left=np.nan,right=np.nan)
    improvement = np.abs(prior-observed)-np.abs(final-observed)
    starts = table.groupby('group').bin_start.first().to_dict()
    rows=[]
    for j,label in enumerate(labels):
        if not np.isfinite(starts.get(label,np.nan)):continue
        contribution = interp(c[:,j])
        for h,value,delta in zip(grid,contribution,improvement):
            if np.isfinite(value) and np.isfinite(delta):
                rows.append(dict(height_km=float(h),spectral_group=label,bin_start=starts[label],
                                 contribution=float(value),absolute_error_improvement=float(delta)))
    return rows


def profile_correlations(pairs, minimum_cases=3, magnitude=False):
    """Pairwise Pearson r, preserving support counts even for undefined r."""
    rows=[]
    keys=['model','variable','height_km','spectral_group','bin_start']
    for key,g in pairs.groupby(keys,dropna=False,sort=True):
        if g.case_id.duplicated().any():
            raise ValueError('Duplicate case in a spectral-height correlation cell')
        x=g.contribution.to_numpy(float); y=g.absolute_error_improvement.to_numpy(float)
        if magnitude:x=np.abs(x)
        valid=np.isfinite(x)&np.isfinite(y); x,y=x[valid],y[valid]
        r=np.nan
        if len(x)>=minimum_cases and np.ptp(x)>0 and np.ptp(y)>0:
            r=float(np.clip(np.corrcoef(x,y)[0,1],-1.,1.))
        rows.append(dict(zip(keys,key),pearson_r=r,cases=len(x)))
    return pd.DataFrame(rows)
