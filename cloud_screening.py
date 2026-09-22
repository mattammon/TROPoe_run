"""Auditable three-state SGP cloud screening; see CLOUD_SCREENING.md."""
from dataclasses import asdict, dataclass
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

CATEGORIES = ('clear_sky', 'not_clear_sky', 'uncertain')


@dataclass(frozen=True)
class ScreenPolicy:
    # Explicit policy thresholds, not a universally validated cloud classifier.
    context_minutes: float = 60.
    core_minutes: float = 10.
    retrieval_round_minutes: int = 15
    coverage_bin_seconds: int = 60
    min_coverage: float = 0.8
    max_gap_seconds: float = 180.
    min_samples: int = 3
    min_cloud_samples: int = 2
    asi_zenith_field: str = 'near_zenith_percent_cloud'
    asi_total_field: str = 'percent_cloud'
    asi_clear_zenith_max: float = 0.
    asi_clear_total_max: float = 10.
    asi_cloud_zenith_min: float = 5.
    asi_cloud_total_min: float = 20.
    asi_max_sza: float = 80.
    asi_require_qc: bool = True
    asi_max_uncertainty: float = 5.  # percentage points, when supplied
    asi_zenith_qc: str = 'qc_near_zenith_percent_cloud'
    asi_total_qc: str = 'qc_percent_cloud'
    asi_zenith_uncertainty: str = ''  # Optional explicit source field mappings
    asi_total_uncertainty: str = ''
    wavenumber: float = 985.
    wavenumber_tolerance: float = 0.5
    radiance_field: str = 'mean_rad'
    radiance_require_qc: bool = True
    radiance_clear_mean_max: float | None = None
    radiance_clear_std_max: float | None = None
    radiance_clear_p95_max: float | None = None
    # Crossing clear limits alone is ambiguous. These independently calibrated
    # higher limits are needed to assign radiance evidence as not_clear_sky.
    radiance_cloud_mean_min: float | None = None
    radiance_cloud_std_min: float | None = None
    clear_rule: str = 'asi'  # asi, radiance, both; contradictions always uncertain

    def __post_init__(self):
        if self.clear_rule not in ('asi', 'radiance', 'both'):
            raise ValueError('clear_rule must be asi, radiance, or both')
        for name in ('context_minutes', 'core_minutes', 'coverage_bin_seconds',
                     'max_gap_seconds', 'wavenumber', 'wavenumber_tolerance'):
            if not np.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if self.context_minutes < self.core_minutes + self.retrieval_round_minutes:
            raise ValueError('Context must cover the core window plus rounding offset')
        if self.retrieval_round_minutes < 0 or not 0 < self.min_coverage <= 1:
            raise ValueError('Invalid rounding or coverage policy')
        if self.min_samples < 2 or self.min_cloud_samples < 1:
            raise ValueError('Invalid minimum sample counts')
        if not 0 <= self.asi_clear_zenith_max < self.asi_cloud_zenith_min <= 100:
            raise ValueError('ASI zenith clear/cloud thresholds must be ordered within 0--100')
        if not 0 <= self.asi_clear_total_max < self.asi_cloud_total_min <= 100:
            raise ValueError('ASI total clear/cloud thresholds must be ordered within 0--100')
        if not 0 < self.asi_max_sza <= 90 or self.asi_max_uncertainty < 0:
            raise ValueError('Invalid ASI solar/uncertainty threshold')
        for name, value in asdict(self).items():
            if name.startswith('radiance_') and name.endswith(('_max', '_min')) and value is not None:
                if not np.isfinite(value) or value < 0:
                    raise ValueError(f'{name} must be nonnegative and finite')
        configured = (self.radiance_clear_mean_max is not None and self.radiance_clear_std_max is not None)
        if self.clear_rule in ('radiance', 'both') and not configured:
            raise ValueError('Radiance clear rule requires mean AND standard-deviation limits')
        for metric in ('mean', 'std'):
            low, high = getattr(self, f'radiance_clear_{metric}_max'), getattr(self, f'radiance_cloud_{metric}_min')
            if low is not None and high is not None and high <= low:
                raise ValueError(f'Radiance {metric} cloudy threshold must exceed clear threshold')

    @classmethod
    def from_json(cls, path):
        return cls(**json.loads(Path(path).read_text()))


def utc_naive(value):
    t = pd.Timestamp(value)
    return t.tz_convert('UTC').tz_localize(None) if t.tzinfo else t


def filename_time(path):
    found = re.search(r'\.(\d{8})\.(\d{6})\.', Path(path).name)
    if not found:
        raise ValueError(f'No ARM timestamp in {Path(path).name}')
    return pd.to_datetime(''.join(found.groups()), format='%Y%m%d%H%M%S')


def dataset_times(ds):
    """Decode CF time or ARM base_time + time_offset without guessing epochs."""
    if 'time' in ds and np.issubdtype(ds.time.dtype, np.datetime64):
        return pd.DatetimeIndex(ds.time.values)
    if 'time_offset' in ds and 'base_time' in ds:
        base = ds.base_time.values.item() if not np.issubdtype(ds.base_time.dtype, np.datetime64) else ds.base_time.values
        if np.issubdtype(ds.base_time.dtype, np.datetime64):
            origin = pd.Timestamp(np.asarray(base).reshape(-1)[0])
        else:
            units = str(ds.base_time.attrs.get('units', ''))
            if '1970-01-01' not in units:
                raise ValueError('base_time lacks recognized epoch units')
            origin = pd.Timestamp(base, unit='s')
        off = ds.time_offset.values
        if np.issubdtype(off.dtype, np.datetime64):
            return pd.DatetimeIndex(off)
        if np.issubdtype(off.dtype, np.timedelta64):
            return pd.DatetimeIndex(origin + pd.to_timedelta(off))
        units = str(ds.time_offset.attrs.get('units', 'seconds')).lower()
        if not units.startswith(('second', 's ')) and units != 's':
            raise ValueError('Unsupported time_offset units')
        return pd.DatetimeIndex(origin + pd.to_timedelta(off, unit='s'))
    raise ValueError('No decoded CF time or ARM base_time/time_offset')


def solar_zenith(times, latitude, longitude):
    """NOAA fractional-year approximation; UTC, east-positive longitude."""
    t = pd.DatetimeIndex(times)
    hour = t.hour + t.minute/60 + t.second/3600
    gamma = 2*np.pi / np.where(t.is_leap_year, 366, 365) * (t.dayofyear-1+(hour-12)/24)
    eq = 229.18*(.000075+.001868*np.cos(gamma)-.032077*np.sin(gamma)
                 -.014615*np.cos(2*gamma)-.040849*np.sin(2*gamma))
    dec = (.006918-.399912*np.cos(gamma)+.070257*np.sin(gamma)
           -.006758*np.cos(2*gamma)+.000907*np.sin(2*gamma)
           -.002697*np.cos(3*gamma)+.00148*np.sin(3*gamma))
    ha = np.deg2rad((hour*60+eq+4*longitude)/4-180)
    lat = np.deg2rad(latitude)
    return np.rad2deg(np.arccos(np.clip(np.sin(lat)*np.sin(dec)+np.cos(lat)*np.cos(dec)*np.cos(ha), -1, 1)))


def _series(ds, name, size):
    a = np.asarray(ds[name].values)
    if a.shape != (size,):
        raise ValueError(f'{name} must contain one value per time sample')
    return a.astype(float)


def _uncertainty(ds, field, explicit, size):
    candidates = [explicit] if explicit else [f'{field}_uncertainty', f'uncertainty_{field}', f'unc_{field}']
    for name in candidates:
        if name in ds:
            return _series(ds, name, size), name
    if explicit:
        raise ValueError(f'Missing configured uncertainty field {explicit}')
    return np.zeros(size), 'not_available'


def read_asi(path, policy, latitude, longitude):
    with xr.open_dataset(path) as ds:
        times = dataset_times(ds)
        n = len(times)
        zenith = _series(ds, policy.asi_zenith_field, n)
        total = _series(ds, policy.asi_total_field, n)
        valid = np.isfinite(zenith) & np.isfinite(total) & (zenith >= 0) & (zenith <= 100) & (total >= 0) & (total <= 100)
        qc_present = []
        for name in (policy.asi_zenith_qc, policy.asi_total_qc):
            if name in ds:
                valid &= _series(ds, name, n) == 0
                qc_present.append(name)
            elif policy.asi_require_qc:
                valid[:] = False
        # Global QC, if supplied, is an additional veto.
        for name in ('qc_time', 'qc_flag'):
            if name in ds:
                valid &= _series(ds, name, n) == 0
        uz, uz_name = _uncertainty(ds, policy.asi_zenith_field, policy.asi_zenith_uncertainty, n)
        ut, ut_name = _uncertainty(ds, policy.asi_total_field, policy.asi_total_uncertainty, n)
        valid &= np.isfinite(uz) & np.isfinite(ut) & (uz >= 0) & (ut >= 0)
        valid &= (uz <= policy.asi_max_uncertainty) & (ut <= policy.asi_max_uncertainty)
        sza = solar_zenith(times, latitude, longitude)
        valid &= sza <= policy.asi_max_sza
        return pd.DataFrame({'time': times, 'zenith': zenith, 'total': total, 'sza': sza,
                             'valid': valid, 'file': str(Path(path).resolve()),
                             'qc_fields': ','.join(qc_present), 'uncertainty_fields': f'{uz_name},{ut_name}'})


def read_radiance(path, policy):
    with xr.open_dataset(path) as ds:
        times = dataset_times(ds)
        coord = next((name for name in ('wnum', 'wnum1', 'wavenumber') if name in ds), None)
        if coord is None or ds[coord].ndim != 1:
            raise ValueError('Missing one-dimensional wnum/wnum1/wavenumber')
        wave = np.asarray(ds[coord].values, dtype=float)
        wave_units = str(ds[coord].attrs.get('units', 'cm-1')).lower().replace(' ', '').replace('^', '')
        if wave_units not in ('cm-1', '1/cm', 'cm**-1'):
            raise ValueError(f'Unsupported wavenumber units: {wave_units}')
        k = int(np.nanargmin(abs(wave-policy.wavenumber)))
        if abs(wave[k]-policy.wavenumber) > policy.wavenumber_tolerance:
            raise ValueError('No spectral element within requested wavenumber tolerance')
        spectral_dim = ds[coord].dims[0]
        da = ds[policy.radiance_field].isel({spectral_dim: k})
        values = np.asarray(da.values, dtype=float)
        if values.shape != (len(times),):
            raise ValueError('Selected radiance must have one value per time')
        units = str(da.attrs.get('units', '')).replace(' ', '')
        if units.upper() == 'RU' or ('mW' in units and 'sr' in units and 'cm' in units):
            factor = 1.
        elif ('W' in units and 'mW' not in units and 'sr' in units and 'cm' in units):
            factor = 1000.
        else:
            raise ValueError(f'Unrecognized radiance units: {units!r}; expected spectral RU')
        values = values*factor
        valid = np.isfinite(values)
        found = []
        for name in (f'qc_{policy.radiance_field}', 'missingDataFlag', 'qc_flag', 'qc_time'):
            if name not in ds:
                continue
            da = ds[name]
            if spectral_dim in da.dims:
                da = da.isel({spectral_dim: k})
            flags = np.asarray(da.values, dtype=float)
            if flags.shape != values.shape:
                raise ValueError(f'Unsupported QC dimensions for {name}')
            valid &= flags == 0
            found.append(name)
        if policy.radiance_require_qc and not found:
            valid[:] = False
        for name in ('hatchOpen', 'hatch_open'):
            if name in ds:
                valid &= _series(ds, name, len(times)) == 1
        return pd.DataFrame({'time': times, 'radiance': values, 'valid': valid,
                             'actual_wavenumber': wave[k], 'file': str(Path(path).resolve()),
                             'qc_fields': ','.join(found)})


def window_stats(frame, start, end, fields, policy):
    """Time-bin occupancy and edge-aware gaps prevent dense bursts hiding gaps."""
    selected = frame[(frame.time >= start) & (frame.time <= end)] if not frame.empty else frame
    conflicting = 0
    if not selected.empty:
        # Overlapping files must not turn conflicting measurements into clear sky.
        grouped = selected.groupby('time')
        conflicts = grouped[list(fields)+['valid']].nunique(dropna=False).max(axis=1) > 1
        conflicting = int(conflicts.sum())
        selected_valid = selected.valid & ~selected.time.isin(conflicts[conflicts].index)
        valid = selected[selected_valid].copy()
    else:
        valid = selected
    valid = valid.drop_duplicates('time').sort_values('time') if not valid.empty else valid
    seconds = (end-start).total_seconds()
    bins = int(np.ceil(seconds/policy.coverage_bin_seconds))
    offsets = (valid.time-start).dt.total_seconds().to_numpy() if not valid.empty else np.array([])
    used = np.unique(np.minimum((offsets/policy.coverage_bin_seconds).astype(int), bins-1))
    gaps = np.diff(np.r_[0., offsets, seconds])
    stats = {'conflicting_timestamps': conflicting, 'n_total': len(selected), 'n_valid': len(valid), 'coverage': len(used)/bins,
             'max_gap_seconds': float(gaps.max()), 'files': sorted(set(selected.file)) if not selected.empty else []}
    stats['adequate'] = (not conflicting and len(valid) >= policy.min_samples and stats['coverage'] >= policy.min_coverage
                         and stats['max_gap_seconds'] <= policy.max_gap_seconds)
    for field in fields:
        a = valid[field].to_numpy() if not valid.empty else np.array([])
        for suffix, func in [('mean', np.mean), ('std', lambda x: np.std(x, ddof=1)),
                             ('p95', lambda x: np.percentile(x, 95)), ('max', np.max)]:
            stats[f'{field}_{suffix}'] = float(func(a)) if len(a) >= (2 if suffix == 'std' else 1) else None
    return stats, valid


def evaluate_case(time, asi, radiance, policy):
    time = utc_naive(time)
    # Match the minute-resolution input and quarter-hour rounding in SINGLE_TROPoe.
    minute = time.floor('min')
    if policy.retrieval_round_minutes:
        step = policy.retrieval_round_minutes*60
        secs = (minute-minute.normalize()).total_seconds()
        target = minute.normalize()+pd.Timedelta(seconds=int(secs/step+.5)*step)
    else:
        target = time
    ranges = {'context': (time-pd.Timedelta(minutes=policy.context_minutes/2), time+pd.Timedelta(minutes=policy.context_minutes/2)),
              'core': (target-pd.Timedelta(minutes=policy.core_minutes/2), target+pd.Timedelta(minutes=policy.core_minutes/2))}
    evidence = {}
    for kind, frame, fields in [('asi', asi, ['zenith', 'total']), ('radiance', radiance, ['radiance'])]:
        windows, samples = {}, {}
        for name, (start, end) in ranges.items():
            windows[name], samples[name] = window_stats(frame, start, end, fields, policy)
        state, reason = 'uncertain', 'insufficient_valid_coverage'
        enough = all(w['adequate'] for w in windows.values())
        core, context = samples['core'], samples['context']
        if kind == 'asi':
            cloudy = ((core.zenith >= policy.asi_cloud_zenith_min) | (core.total >= policy.asi_cloud_total_min)).sum() if not core.empty else 0
            if cloudy >= policy.min_cloud_samples:
                state, reason = 'not_clear_sky', 'repeated_cloud_detection_in_core'
            elif enough:
                clear = ((context.zenith <= policy.asi_clear_zenith_max) & (context.total <= policy.asi_clear_total_max)).all()
                state, reason = ('clear_sky', 'clear_through_context_and_core') if clear else ('uncertain', 'borderline_or_clouds_outside_core')
        else:
            thresholds_set = policy.radiance_clear_mean_max is not None and policy.radiance_clear_std_max is not None
            if enough:
                cloud = any(limit is not None and windows['core'][f'radiance_{metric}'] >= limit
                            for metric, limit in [('mean', policy.radiance_cloud_mean_min), ('std', policy.radiance_cloud_std_min)])
                clear = thresholds_set and all(w['radiance_mean'] <= policy.radiance_clear_mean_max
                                               and w['radiance_std'] <= policy.radiance_clear_std_max
                                               and (policy.radiance_clear_p95_max is None or w['radiance_p95'] <= policy.radiance_clear_p95_max)
                                               for w in windows.values())
                if cloud:
                    state, reason = 'not_clear_sky', 'calibrated_radiance_cloud_limit_exceeded'
                elif clear:
                    state, reason = 'clear_sky', 'calibrated_radiance_clear_limits_met'
                else:
                    reason = 'radiance_thresholds_not_configured' if not thresholds_set else 'radiance_ambiguous'
        evidence[kind] = {'state': state, 'reason': reason, **windows}
    states = {e['state'] for e in evidence.values()}
    if any(e[w]['conflicting_timestamps'] for e in evidence.values() for w in ('core', 'context')):
        category, reason = 'uncertain', 'conflicting_duplicate_observations'
    elif 'clear_sky' in states and 'not_clear_sky' in states:
        category, reason = 'uncertain', 'conflicting_instrument_evidence'
    elif 'not_clear_sky' in states:
        category, reason = 'not_clear_sky', 'cloud_evidence'
    else:
        required = ('asi', 'radiance') if policy.clear_rule == 'both' else (policy.clear_rule,)
        clear = all(evidence[k]['state'] == 'clear_sky' for k in required)
        category, reason = ('clear_sky', f'{policy.clear_rule}_clear_rule_met') if clear else ('uncertain', 'clear_rule_not_met')
    return {'category': category, 'reason': reason, 'sounding_time': time.isoformat(),
            'retrieval_time': target.isoformat(), 'windows': {k: [s.isoformat(), e.isoformat()] for k, (s, e) in ranges.items()},
            'evidence': evidence}


def selected_sounding_files(sonde_dir, group, manifest=None, category='clear_sky'):
    """Use an explicit manifest when configured; never fall back on a bad one."""
    if not manifest:
        return sorted(str(p) for p in (Path(sonde_dir)/group).glob('*sonde*'))
    if category not in CATEGORIES:
        raise ValueError(f'Invalid cloud-screen category: {category}')
    df = pd.read_csv(manifest, dtype=str)
    if not {'category', 'sounding_file'} <= set(df.columns):
        raise ValueError('Cloud manifest requires category and sounding_file columns')
    files = df.loc[df.category == category, 'sounding_file'].tolist()
    missing = [p for p in files if not Path(p).is_file()]
    if missing:
        raise FileNotFoundError(f'{len(missing)} selected sounding files are unavailable; first: {missing[0]}')
    return sorted(set(files))
