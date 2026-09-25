"""Auditable three-state SGP cloud screening; see CLOUD_SCREENING.md."""
from dataclasses import asdict, dataclass
import json
import logging
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr

logger = logging.getLogger(__name__)

CATEGORIES = ('clear_sky', 'not_clear_sky', 'uncertain')


@dataclass(frozen=True)
class ScreenPolicy:
    # Explicit policy thresholds, not a universally validated cloud classifier.
    context_minutes: float = 60.
    core_minutes: float = 10.
    retrieval_round_minutes: int = 15
    coverage_bin_seconds: int = 180
    min_coverage: float = 0.6
    max_gap_seconds: float = 600.
    min_samples: int = 3
    min_cloud_samples: int = 2
    asi_zenith_field: str = 'near_zenith_percent_cloud'
    asi_total_field: str = 'percent_cloud'
    asi_clear_zenith_max: float = 0.
    asi_clear_total_max: float = 20.
    asi_cloud_zenith_min: float = 10.
    asi_cloud_total_min: float = 50.
    asi_max_sza: float = 80.
    asi_first_pass: bool = True  # Any qualifying sample establishes clear sky
    asi_require_qc: bool = False  # ASISKYCOVER may supply uncertainty instead of QC flags
    asi_max_uncertainty: float = 10.  # percentage points, when supplied
    asi_zenith_qc: str = 'qc_near_zenith_percent_cloud'
    asi_total_qc: str = 'qc_percent_cloud'
    asi_zenith_uncertainty: str = ''  # Optional explicit source field mappings
    asi_total_uncertainty: str = ''
    wavenumber: float = 985.
    wavenumber_tolerance: float = 0.5
    radiance_field: str = 'mean_rad'
    radiance_require_qc: bool = True
    radiance_clear_mean_max: Optional[float] = None
    radiance_clear_std_max: Optional[float] = None
    radiance_clear_p95_max: Optional[float] = None
    # Crossing clear limits alone is ambiguous. These independently calibrated
    # higher limits are needed to assign radiance evidence as not_clear_sky.
    radiance_cloud_mean_min: Optional[float] = None
    radiance_cloud_std_min: Optional[float] = None
    clear_rule: str = 'asi'  # ASI with radiance fallback when ASI is uncertain; or radiance/both

    def __post_init__(self):
        for name in ('asi_zenith_qc', 'asi_total_qc'):
            if 'uncertainty' in getattr(self, name).lower():
                raise ValueError(name+' must name a QC flag, not an uncertainty percentage; use asi_zenith_uncertainty or asi_total_uncertainty')
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
    known = {'near_zenith_percent_cloud': 'near_zenith_uncertainty_total',
             'percent_cloud': 'uncertainty_total'}
    candidates = [explicit] if explicit else [known.get(field, ''), f'{field}_uncertainty',
                                               f'uncertainty_{field}', f'unc_{field}']
    for name in candidates:
        if name in ds:
            return _series(ds, name, size), name
    if explicit:
        raise ValueError(f'Missing configured uncertainty field {explicit}')
    return np.zeros(size), 'not_available'


def _check(valid, passed, label, path):
    """Log independent failure counts; a sample may fail multiple checks."""
    passed = np.broadcast_to(passed, valid.shape)
    rejected = int(np.count_nonzero(~passed))
    if rejected:
        logger.info('%s: %s rejects %d/%d samples (checks may overlap)',
                    Path(path).name, label, rejected, len(valid))
    valid &= passed


def _read_summary(path, times, valid):
    cadence = np.diff(times.asi8)/1e9
    cadence = cadence[cadence > 0]
    logger.info('%s: valid=%d/%d; UTC span=%s to %s; median positive cadence=%s s',
                Path(path).name, int(valid.sum()), len(valid),
                times[0] if len(times) else 'none', times[-1] if len(times) else 'none',
                float(np.median(cadence)) if len(cadence) else 'unknown')
    if not valid.any():
        logger.warning('%s: NO VALID OBSERVATIONS; inspect rejection messages above', path)


def read_asi(path, policy, latitude, longitude):
    if not policy.asi_first_pass:
        return _read_asi_strict(path, policy, latitude, longitude)
    with xr.open_dataset(path) as ds:
        times = dataset_times(ds)
        n = len(times)
        zenith = _series(ds, policy.asi_zenith_field, n)
        total = _series(ds, policy.asi_total_field, n)
        # Missing/fill values cannot satisfy a physical cloud-percentage criterion.
        for values in (zenith, total):
            values[(values < 0) | (values > 100)] = np.nan
        sza = solar_zenith(times, latitude, longitude)
        valid = np.isfinite(sza) & (sza <= policy.asi_max_sza)
        qc = [name for name in (policy.asi_zenith_qc, policy.asi_total_qc, 'qc_time', 'qc_flag') if name in ds]
        uncertainty_names = []
        for field, explicit in ((policy.asi_zenith_field, policy.asi_zenith_uncertainty),
                                (policy.asi_total_field, policy.asi_total_uncertainty)):
            try:
                values, name = _uncertainty(ds, field, explicit, n)
                logger.info('%s: %s uncertainty=%s; %d samples exceed %g%% (diagnostic only)',
                            Path(path).name, field, name, int((values > policy.asi_max_uncertainty).sum()), policy.asi_max_uncertainty)
            except (ValueError, TypeError) as exc:
                name = 'unreadable'
                logger.warning('%s: optional uncertainty diagnostic unavailable: %s', path, exc)
            uncertainty_names.append(name)
        logger.info('%s: ASI FIRST PASS; QC flags %s ignored; only solar zenith <= %g degrees gates samples. Cloud fractions are checked during case selection.',
                    Path(path).name, qc, policy.asi_max_sza)
        _read_summary(path, times, valid)
        return pd.DataFrame({'time': times, 'zenith': zenith, 'total': total, 'sza': sza,
                             'valid': valid, 'file': str(Path(path).resolve()),
                             'qc_fields': ','.join(qc), 'uncertainty_fields': ','.join(uncertainty_names)})


def _read_asi_strict(path, policy, latitude, longitude):
    with xr.open_dataset(path) as ds:
        times = dataset_times(ds)
        n = len(times)
        zenith = _series(ds, policy.asi_zenith_field, n)
        total = _series(ds, policy.asi_total_field, n)
        valid = np.isfinite(zenith) & np.isfinite(total) & (zenith >= 0) & (zenith <= 100) & (total >= 0) & (total <= 100)
        logger.info('%s: invalid/nonfinite cloud fractions=%d/%d', Path(path).name, int((~valid).sum()), n)
        qc_present = []
        for name in (policy.asi_zenith_qc, policy.asi_total_qc):
            if name in ds:
                _check(valid, _series(ds, name, n) == 0, 'QC '+name+' != 0', path)
                qc_present.append(name)
            elif policy.asi_require_qc:
                logger.warning('%s: required QC field %s MISSING; all samples rejected', path, name)
                valid[:] = False
        # Global QC, if supplied, is an additional veto.
        for name in ('qc_time', 'qc_flag'):
            if name in ds:
                _check(valid, _series(ds, name, n) == 0, 'QC '+name+' != 0', path)
        uz, uz_name = _uncertainty(ds, policy.asi_zenith_field, policy.asi_zenith_uncertainty, n)
        ut, ut_name = _uncertainty(ds, policy.asi_total_field, policy.asi_total_uncertainty, n)
        logger.info('%s: uncertainty fields: zenith=%s, total=%s', Path(path).name, uz_name, ut_name)
        for label, uncertainty_name, qc_name in (
                ('zenith', uz_name, policy.asi_zenith_qc),
                ('total', ut_name, policy.asi_total_qc)):
            if uncertainty_name == 'not_available':
                if qc_name not in qc_present:
                    logger.warning('%s: no recognized %s QC or uncertainty; all samples rejected', path, label)
                    valid[:] = False
                else:
                    logger.info('%s: %s uncertainty unavailable; using QC flags only', path, label)
            elif qc_name not in qc_present and not policy.asi_require_qc:
                logger.info('%s: %s QC flag absent; using %s <= %g percent',
                            path, label, uncertainty_name, policy.asi_max_uncertainty)
        _check(valid, np.isfinite(uz) & np.isfinite(ut) & (uz >= 0) & (ut >= 0), 'invalid uncertainty', path)
        _check(valid, (uz <= policy.asi_max_uncertainty) & (ut <= policy.asi_max_uncertainty), 'uncertainty > %g percent' % policy.asi_max_uncertainty, path)
        sza = solar_zenith(times, latitude, longitude)
        _check(valid, sza <= policy.asi_max_sza, 'solar zenith > %g degrees' % policy.asi_max_sza, path)
        _read_summary(path, times, valid)
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
        logger.info('%s: selected wavenumber=%.4f cm-1; nonfinite radiances=%d', Path(path).name, wave[k], int((~valid).sum()))
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
            _check(valid, flags == 0, 'QC '+name+' != 0', path)
            found.append(name)
        if policy.radiance_require_qc and not found:
            logger.warning('%s: no recognized radiance QC field; all samples rejected', path)
            valid[:] = False
        for name in ('hatchOpen', 'hatch_open'):
            if name in ds:
                _check(valid, _series(ds, name, len(times)) == 1, 'hatch not open', path)
        _read_summary(path, times, valid)
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
    failures = []
    if conflicting:
        failures.append('conflicting_timestamps=%d' % conflicting)
    if len(valid) < policy.min_samples:
        failures.append('valid_samples=%d < %d' % (len(valid), policy.min_samples))
    if stats['coverage'] < policy.min_coverage:
        failures.append('coverage=%.3f < %.3f' % (stats['coverage'], policy.min_coverage))
    if stats['max_gap_seconds'] > policy.max_gap_seconds:
        failures.append('max_gap=%.1fs > %.1fs' % (stats['max_gap_seconds'], policy.max_gap_seconds))
    stats['adequacy_failures'] = '; '.join(failures)
    for field in fields:
        a = valid[field].to_numpy() if not valid.empty else np.array([])
        a = a[np.isfinite(a)]
        stats[f'{field}_n_finite'] = len(a)
        for suffix, func in [('mean', np.mean), ('std', lambda x: np.std(x, ddof=1)),
                             ('p95', lambda x: np.percentile(x, 95)), ('max', np.max)]:
            value = float(func(a)) if len(a) >= (2 if suffix == 'std' else 1) else None
            stats[f'{field}_{suffix}'] = value if value is not None and np.isfinite(value) else None
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
            w = windows[name]
            logger.info('%s %s UTC [%s, %s]: total=%d valid=%d coverage=%.1f%% max_gap=%.1fs; %s',
                        kind, name, start, end, w['n_total'], w['n_valid'],
                        100*w['coverage'], w['max_gap_seconds'],
                        'PASS' if w['adequate'] else 'FAIL: '+w['adequacy_failures'])
            if kind == 'asi' and policy.asi_first_pass:
                logger.info('ASI %s coverage check is diagnostic only in first-pass mode', name)
        state, reason = 'uncertain', 'insufficient_valid_coverage'
        enough = all(w['adequate'] for w in windows.values())
        core, context = samples['core'], samples['context']
        if kind == 'asi' and policy.asi_first_pass:
            # Use raw window samples so duplicate conflicts and bin adequacy
            # remain diagnostic only, never vetoing a qualifying observation.
            start, end = ranges['context']
            eligible = frame[(frame.time >= start) & (frame.time <= end) & frame.valid] if not frame.empty else frame
            clear = ((eligible.zenith.between(0, policy.asi_clear_zenith_max)) &
                     (eligible.total.between(0, policy.asi_clear_total_max))) if not eligible.empty else pd.Series(dtype=bool)
            clear_count = int(clear.sum())
            cloudy = ((eligible.zenith.between(policy.asi_cloud_zenith_min, 100)) |
                      (eligible.total.between(policy.asi_cloud_total_min, 100))) if not eligible.empty else pd.Series(dtype=bool)
            if clear_count:
                state, reason = 'clear_sky', 'asi_first_pass_clear_sample'
            elif cloudy.any():
                state, reason = 'not_clear_sky', 'asi_first_pass_cloud_evidence_without_clear_sample'
            else:
                state, reason = 'uncertain', 'asi_first_pass_no_qualifying_sample'
            logger.info('ASI first pass: %d solar-angle-eligible samples, %d meet BOTH cloud limits; coverage/QC/uncertainty do not veto', len(eligible), clear_count)
        elif kind == 'asi':
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
    if (policy.clear_rule == 'asi' and evidence['asi']['state'] == 'uncertain'
            and evidence['radiance']['state'] == 'clear_sky'):
        category, reason = 'clear_sky', 'asi_uncertain_radiance_clear_fallback'
        logger.info('ASI uncertain; classifying clear sky because the configured radiance clear limits and coverage checks passed')
    elif policy.asi_first_pass and policy.clear_rule == 'asi':
        category, reason = evidence['asi']['state'], evidence['asi']['reason']
    elif any(e[w]['conflicting_timestamps'] for e in evidence.values() for w in ('core', 'context')):
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
