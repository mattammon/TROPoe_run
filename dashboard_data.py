"""Read-only data preparation for TROPoe_APP; no Streamlit dependency."""
from pathlib import Path
import logging

import numpy as np
import pandas as pd
import xarray as xr

from cloud_screening import dataset_times
from information_content import height_km, read_information, remap_dfs

LOG = logging.getLogger(__name__)
VARIABLES = {'T': ('Temperature', '°C', 'temperature'),
             'q': ('Water vapor mixing ratio', 'g/kg', 'waterVapor'),
             'Td': ('Dew point', '°C', 'dewpt')}


GROUP_ORDERS = {
    'Season': ['Winter (DJF)', 'Spring (MAM)', 'Summer (JJA)', 'Autumn (SON)'],
    'Month': ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    'Time of day (UTC)': ['00–06 UTC', '06–12 UTC', '12–18 UTC', '18–24 UTC'],
}
CLASS_LABELS = {'clear_sky': 'Clear sky', 'not_clear_sky': 'Not clear sky',
                'uncertain': 'Uncertain', 'unknown': 'Unknown'}


def case_label(timestamp):
    """Display UTC date/time while keeping original case IDs as join keys."""
    t = pd.to_datetime(timestamp, utc=True)
    return t.strftime('%d %b %Y · %H:%M' + (':%S' if t.second else '') + ' UTC')


def case_metadata(cases):
    result = cases.copy()
    times = pd.to_datetime(result.sounding_time, utc=True)
    result['Case'] = times.map(case_label)
    result['Season'] = times.dt.month.map(lambda m: GROUP_ORDERS['Season'][(m % 12)//3])
    result['Month'] = times.dt.month.map(lambda m: GROUP_ORDERS['Month'][m-1])
    result['Time of day (UTC)'] = times.dt.hour.map(lambda h: GROUP_ORDERS['Time of day (UTC)'][h//6])
    result['Year'] = times.dt.year.astype(str)
    for column, label in [('category', 'Classification'), ('asi_state', 'ASI classification'),
                          ('radiance_state', 'Radiance classification')]:
        result[label] = result[column].map(lambda v: CLASS_LABELS.get(v, str(v)))
    return result


def display_cases(frame, labels, keep_id=False):
    result = frame.copy()
    if 'case_id' in result:
        result['Case'] = result.case_id.map(labels).fillna('Unknown date')
        if not keep_id:
            result = result.drop(columns='case_id')
        result = result[['Case']+[c for c in result if c != 'Case']]
    return result


def signature(path):
    p = Path(path).expanduser().resolve()
    s = p.stat()
    return str(p), s.st_mtime_ns, s.st_size


def read_manifest(path):
    df = pd.read_csv(path)
    required = {'case_id', 'retrieval_time', 'sounding_file'}
    if not required.issubset(df):
        raise ValueError('Manifest requires: ' + ', '.join(sorted(required)))
    if df.empty or df.case_id.isna().any() or df.case_id.duplicated().any():
        raise ValueError('Manifest must contain unique, nonempty case IDs')
    df['case_id'] = df.case_id.astype(str)
    for key in ('retrieval_time', 'sounding_time'):
        df[key] = pd.to_datetime(df.get(key, df.retrieval_time), utc=True, errors='coerce')
    if df.retrieval_time.isna().any() or df.sounding_time.isna().any():
        raise ValueError('Manifest contains invalid case times')
    for key in ('category', 'asi_state', 'radiance_state'):
        df[key] = df[key].fillna('unknown') if key in df else 'unknown'
    return df.sort_values(['sounding_time', 'case_id']).reset_index(drop=True)


def filter_cases(df, dates, selections, bounds=None, include_missing=True):
    """Inclusive UTC dates; missing cloud metrics are retained by default."""
    keep = df.sounding_time.dt.date.between(*dates)
    for key, values in selections.items():
        keep &= df[key].isin(values)
    for key, (low, high) in (bounds or {}).items():
        a = pd.to_numeric(df[key], errors='coerce')
        keep &= a.between(low, high) | (a.isna() & include_missing)
    return df.loc[keep].copy()


def model_name(channel, band):
    return 'Ch1' if int(channel) == 1 else 'Ch2_B' + str(int(band))


def model_sort(name):
    return (0, 0) if name == 'Ch1' else (1, int(name.split('_B')[1]))


def read_index(root, catalog='', target_times=None, tolerance_seconds=60.):
    """Use a catalog or scan actual NetCDF times; never infer time from names."""
    if not Path(root).is_dir():
        raise ValueError('Retrieval directory does not exist: ' + str(root))
    if catalog and target_times is None:
        df = pd.read_csv(catalog)
        needed = {'file', 'channel', 'band', 'profile_index', 'time', 'status'}
        if not needed.issubset(df):
            raise ValueError('Select the catalog profiles.csv, not cases.csv or files.csv')
        # Catalog paths are absolute, as written by catalog_retrievals.py.
        root_path = Path(root).resolve()
        within = df.file.map(lambda p: root_path in Path(p).resolve().parents)
        df = df.loc[within].copy()
        errors = df.loc[df.status != 'usable'].copy()
    else:
        from catalog_retrievals import scan
        files, profiles = scan(Path(root), target_times=target_times, tolerance_seconds=tolerance_seconds)
        errors = pd.DataFrame([f for f in files if f.get('error')])
        df = pd.DataFrame(profiles)
        if len(df):
            errors = pd.concat([errors, df.loc[df.status != 'usable']], ignore_index=True)
    if df.empty:
        return pd.DataFrame(columns=['file', 'model', 'profile_index', 'time', 'status']), errors
    df['time'] = pd.to_datetime(df.time, utc=True, errors='coerce')
    df['model'] = [model_name(c, b) for c, b in zip(df.channel, df.band)]
    df = df.loc[df.status.isin(['usable', 'partial']) & df.time.notna()].copy()
    return df.sort_values(['model', 'time', 'file', 'profile_index']), errors


def match_cases(cases, index, models, tolerance):
    rows = []
    for model in models:
        subset = index.loc[index.model == model].reset_index(drop=True)
        # pandas 3 may preserve microsecond resolution; Timestamp.value is ns.
        times = subset.time.dt.as_unit('ns').astype('int64').to_numpy() if len(subset) else np.array([], dtype=np.int64)
        for case in cases.itertuples():
            lo = np.searchsorted(times, case.retrieval_time.value-int(tolerance*1e9), side='left')
            hi = np.searchsorted(times, case.retrieval_time.value+int(tolerance*1e9), side='right')
            candidates = subset.iloc[lo:hi].copy()
            row = dict(case_id=case.case_id, model=model, n_matches=len(candidates),
                       file='', profile_index=-1, offset_seconds=np.nan, matched_time='', status='missing')
            if len(candidates):
                candidates['offset_seconds'] = (candidates.time-case.retrieval_time).dt.total_seconds()
                candidates['distance'] = candidates.offset_seconds.abs()
                best = candidates.sort_values(['distance', 'file', 'profile_index']).iloc[0]
                row.update(file=best.file, profile_index=int(best.profile_index),
                           offset_seconds=best.offset_seconds, matched_time=best.time.isoformat(),
                           status='duplicate' if len(candidates) > 1 else 'matched')
            rows.append(row)
    return pd.DataFrame(rows)


def _convert(da, kind):
    a = np.asarray(da.values, float).reshape(-1)
    unit = str(da.attrs.get('units', '')).lower().replace(' ', '').replace('**', '^')
    if kind in ('T', 'Td'):
        if unit in ('k', 'kelvin'):
            a = a-273.15
        elif unit not in ('', 'c', 'degc', 'degree_c', 'degrees_c', 'celsius', 'degree_celsius', 'degrees_celsius'):
            raise ValueError('Unsupported temperature units: ' + unit)
    elif kind == 'q':
        if unit in ('kg/kg', 'kgkg-1', 'kgkg^-1'):
            a = a*1000
        elif unit not in ('', 'g/kg', 'gkg-1', 'gkg^-1'):
            raise ValueError('Unsupported water vapor units: ' + unit)
    elif kind == 'P':
        if unit == 'pa':
            a = a/100
        elif unit not in ('', 'hpa', 'mb', 'mbar', 'millibar', 'millibars'):
            raise ValueError('Unsupported pressure units: ' + unit)
    return a


def load_retrieval(file_signature, record, expected_time, source='auto', no_model=False):
    path = file_signature[0]
    with xr.open_dataset(path) as ds:
        times = pd.to_datetime(dataset_times(ds), utc=True)
        if record >= len(times) or times[record] != pd.Timestamp(expected_time):
            raise ValueError('Catalog time changed; rebuild the catalog and reload')
        dim = ds.time.dims[0] if 'time' in ds and ds.time.ndim == 1 else ds.time_offset.dims[0]
        sample = ds.isel({dim: record}, drop=True)
        z = height_km(sample)
        result = {'z': z, 'errors': {}, 'file': path, 'record': record}
        for key, (_, _, field) in VARIABLES.items():
            try:
                da = sample[field]
                if da.ndim != 1 or da.size != len(z):
                    raise ValueError('Expected one value per height')
                result[key] = _convert(da, key)
            except (KeyError, ValueError) as exc:
                result['errors'][key] = str(exc)
        result['information'] = read_information(sample, source=source, no_model=no_model)
        for key in ('qc_flag', 'lwp', 'rmsa'):
            if key in sample and sample[key].size == 1:
                result[key] = float(sample[key].values.item())
        return result


def sounding_path(path, manifest_dir, sounding_root=''):
    original = Path(str(path))
    if original.is_file():
        return original
    relative = Path(manifest_dir)/original
    if relative.is_file():
        return relative
    if sounding_root:
        matches = sorted(Path(sounding_root).rglob(original.name))
        matches = list({p.resolve() for p in matches if p.is_file()})
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError('Ambiguous sounding basename in sounding root: '+original.name)
    raise FileNotFoundError('Sounding not found: '+str(path))


def load_sounding(file_signature):
    with xr.open_dataset(file_signature[0]) as ds:
        alt = np.asarray(ds.alt.values, float).reshape(-1)
        units = str(ds.alt.attrs.get('units', 'm')).lower()
        if units in ('m', 'meter', 'meters'):
            alt = alt/1000
        elif units not in ('km', 'kilometer', 'kilometers'):
            raise ValueError('Unsupported sounding altitude units: '+units)
        if not np.isfinite(alt[0]):
            raise ValueError('Missing launch altitude')
        z = alt-alt[0]
        t = _convert(ds.tdry, 'T')
        p = _convert(ds.pres, 'P')
        rh = np.asarray(ds.rh.values, float).reshape(-1)
        rh_unit = str(ds.rh.attrs.get('units', '%')).lower()
        if rh_unit in ('1', 'fraction'):
            rh *= 100
        if not len(z) == len(t) == len(p) == len(rh):
            raise ValueError('Sounding variables have different lengths')
        # Keep ascending observations only, including the first occurrence of a height.
        keep, top = [], -np.inf
        for i, h in enumerate(z):
            if np.isfinite(h) and h > top:
                keep.append(i)
                top = h
        if len(keep) < 2:
            raise ValueError('Fewer than two ascending sounding levels')
        with np.errstate(invalid='ignore', divide='ignore', over='ignore'):
            vapor = (rh/100)*6.112*np.exp(17.67*t/(t+243.5))
            q = 622*vapor/(p-vapor)
            e = (rh/100)*6.1365*np.exp(17.502*t/(240.97+t))
            td = 240.97*np.log(e/6.1365)/(17.502-np.log(e/6.1365))
        invalid = (rh <= 0) | (rh > 100) | ~np.isfinite(rh) | (p <= vapor)
        q[invalid] = np.nan
        td[invalid] = np.nan
        return {'z': z[keep], 'T': t[keep], 'Td': td[keep], 'q': q[keep]}


def interpolate(profile, variable, grid):
    values = np.asarray(profile[variable], float).copy()
    values[~np.isfinite(values)] = np.nan
    return np.interp(grid, profile['z'], values, left=np.nan, right=np.nan)


def build_analysis(cases, models, profiles, observations, variable, edges, paired=True):
    """Complete common-grid RMSE; information is independent of sounding availability."""
    centers = (edges[:-1]+edges[1:])/2
    rows, curves, infos, problems = [], {}, {}, []
    meta = cases.set_index('case_id')
    for case in cases.case_id:
        for model in models:
            key = (case, model)
            profile = profiles.get(key)
            if profile is None:
                problems.append(dict(case_id=case, model=model, stage='profile', reason='No loaded profile'))
                continue
            if variable in ('T', 'q'):
                info = profile.get('information', {})
                data = info.get('variables', {}).get(variable)
                if data:
                    mapped = remap_dfs(profile['z'], data['dfs_level'], edges)
                    if np.isfinite(mapped['dfs_bin']).all():
                        infos[key] = dict(**mapped, source=data['source'], dfs=float(mapped['dfs_bin'].sum()))
                    else:
                        problems.append(dict(case_id=case, model=model, stage='DFS', reason='Incomplete layer coverage'))
                else:
                    problems.append(dict(case_id=case, model=model, stage='DFS', reason=info.get('errors', {}).get(variable, 'Missing information diagnostics')))
            try:
                if variable not in profile:
                    raise ValueError(profile.get('errors', {}).get(variable, 'Missing retrieval variable: '+variable))
                if case not in observations:
                    raise ValueError('No loaded radiosonde; see sounding load errors')
                ret = interpolate(profile, variable, centers)
                obs = interpolate(observations[case], variable, centers)
                if not np.isfinite(ret).all() or not np.isfinite(obs).all():
                    raise ValueError('Missing/nonfinite values inside the selected layer (no extrapolation)')
                error = ret-obs
                # Centers are uniformly spaced, so all vertical samples have equal weight.
                obs_std, ret_std = np.std(obs), np.std(ret)
                corr = float(np.corrcoef(obs, ret)[0, 1]) if obs_std > 0 and ret_std > 0 else np.nan
                curves[key] = dict(retrieved=ret, observed=obs, error=error)
                rows.append(dict(case_id=case, model=model, time=meta.loc[case, 'sounding_time'],
                                 category=meta.loc[case, 'category'], rmse=float(np.sqrt(np.mean(error**2))),
                                 bias=float(error.mean()), correlation=corr, observed_std=obs_std,
                                 retrieved_std=ret_std))
            except (KeyError, ValueError) as exc:
                problems.append(dict(case_id=case, model=model, stage='RMSE', reason=str(exc)))
    metrics = pd.DataFrame(rows)
    if paired and len(metrics):
        counts = metrics.groupby('case_id').model.nunique()
        common = set(counts[counts == len(models)].index)
        for row in metrics.loc[~metrics.case_id.isin(common)].itertuples():
            problems.append(dict(case_id=row.case_id, model=row.model, stage='RMSE cohort', reason='Another selected band lacks a valid comparison'))
        metrics = metrics.loc[metrics.case_id.isin(common)].copy()
        curves = {k: v for k, v in curves.items() if k[0] in common}
    if paired and infos:
        common_info = {c for c in cases.case_id if all((c, m) in infos for m in models)}
        for case, model in infos:
            if case not in common_info:
                problems.append(dict(case_id=case, model=model, stage='DFS cohort', reason='Another selected band lacks valid DFS in this layer'))
        infos = {k: v for k, v in infos.items() if k[0] in common_info}
    if len(metrics):
        metrics['dfs'] = [infos.get((r.case_id, r.model), {}).get('dfs', np.nan) for r in metrics.itertuples()]
        metrics['dfs_source'] = [infos.get((r.case_id, r.model), {}).get('source', '') for r in metrics.itertuples()]
    return dict(metrics=metrics, curves=curves, information=infos, problems=pd.DataFrame(problems),
                centers=centers, edges=edges, variable=variable,
                case_labels=dict(zip(cases.case_id, cases.sounding_time.map(case_label))))


def demo_data():
    """Deterministic synthetic demonstration, never presented as observations."""
    rng = np.random.default_rng(42)
    models = ['Ch1', 'Ch2_B1', 'Ch2_B6', 'Ch2_B18']
    z = np.linspace(0, 6, 121)
    rows, profiles, observations = [], {}, {}
    for i, time in enumerate(pd.date_range('2025-01-01T00:00Z', periods=48, freq='12h')):
        case = 'DEMO_'+time.strftime('%Y%m%dT%H%M')
        cloud = float(rng.uniform(0, 100))
        category = ['clear_sky', 'uncertain', 'not_clear_sky'][i % 3]
        row = dict(case_id=case, sounding_time=time, retrieval_time=time, sounding_file='SYNTHETIC',
                   category=category, asi_state=category, radiance_state=['clear_sky', 'uncertain'][i % 2],
                   asi_core_total_mean=cloud, asi_core_zenith_mean=max(0, cloud-20),
                   radiance_core_radiance_mean=3+cloud/8, radiance_core_radiance_std=0.08+cloud/120)
        if i % 7 == 0:
            row['asi_core_total_mean'] = np.nan
        rows.append(row)
        t = 16-6*z+3*np.sin(z*2+i/7)+i/12
        q = 8*np.exp(-z/1.7)*(1+0.2*np.sin(i))
        observations[case] = dict(z=z, T=t, q=q, Td=t-5)
        for b, model in enumerate(models):
            if b == 3 and i % 9 == 0:
                continue
            bias = (b-1)*0.15
            perturbation = (0.5+b*0.12)*np.sin(3*z+i)+rng.normal(0, 0.1, len(z))
            info = {'variables': {}, 'errors': {}}
            for key in ('T', 'q'):
                dfs = (0.13+b*0.02)*np.exp(-z/(2 if key == 'T' else 1.3))
                info['variables'][key] = dict(dfs_level=dfs, source='Akernal')
            profiles[(case, model)] = dict(z=z, T=t+bias+perturbation, q=q+0.2*perturbation,
                                           Td=t-5+perturbation, information=info)
    return pd.DataFrame(rows), models, profiles, observations

