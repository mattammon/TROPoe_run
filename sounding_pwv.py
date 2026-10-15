"""Observed-sounding column water and a persistent, file-signature-based cache.

PWV = integral(q dp) / g, with specific humidity q in kg/kg and pressure in
Pa; kg/m2 equals mm liquid water. No retrieval data or extrapolation is used.
"""
import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from dashboard_data import _convert, read_manifest
from shared_outputs import atomic_text

LOG = logging.getLogger(__name__)
VERSION = 'specific_humidity_v1'
COLUMNS = ['pwv_mm', 'pwv_observed_mm', 'pwv_status', 'pwv_bottom_hpa',
           'pwv_top_hpa', 'pwv_max_gap_hpa', 'pwv_levels', 'pwv_error']


def integrate_pwv(pressure_hpa, mixing_ratio_gkg):
    """Trapezoidal pressure integral; accepts either pressure order."""
    p, r = np.asarray(pressure_hpa, float), np.asarray(mixing_ratio_gkg, float)/1000.
    if p.ndim != 1 or p.shape != r.shape or len(p) < 2:
        raise ValueError('Need aligned one-dimensional pressure and humidity profiles')
    if not (np.isfinite(p).all() and np.isfinite(r).all()) or (p <= 0).any() or (r < 0).any():
        raise ValueError('Invalid pressure or mixing ratio')
    order = np.argsort(p)
    p, r = p[order], r[order]
    if (np.diff(p) <= 0).any():
        raise ValueError('Pressure levels must be distinct')
    q = r/(1+r)
    return float(np.sum((q[1:]+q[:-1])*0.5*np.diff(p)*100.)/9.80665)


def sounding_pwv(path):
    """ARM sonde pres/tdry/rh/alt; retain ascent only, reject large gaps."""
    with xr.open_dataset(path) as ds:
        p, t = _convert(ds.pres, 'P'), _convert(ds.tdry, 'T')
        rh = np.asarray(ds.rh.values, float).reshape(-1)
        units = str(ds.rh.attrs.get('units', '%')).strip().lower()
        if units in ('1', 'fraction'):
            rh *= 100.
        elif units not in ('%', 'percent', 'percentage'):
            raise ValueError('Unsupported RH units: '+units)
        z = np.asarray(ds.alt.values, float).reshape(-1)
    if not len(p) == len(t) == len(rh) == len(z):
        raise ValueError('Sounding variables have different lengths')
    # Increasing height removes descent and repeated ground observations.
    keep, highest = [], -np.inf
    for i, height in enumerate(z):
        if np.isfinite(height) and height > highest:
            keep.append(i)
            highest = height
    p, t, rh = p[keep], t[keep], rh[keep]
    launch = p[np.isfinite(p) & (p > 0)]
    if not len(launch):
        raise ValueError('No valid ascent pressure')
    launch = launch[0]
    with np.errstate(over='ignore', invalid='ignore', divide='ignore'):
        e = rh/100.*6.112*np.exp(17.67*t/(t+243.5))
        r = 622.*e/(p-e)
    valid = (np.isfinite(p) & np.isfinite(t) & np.isfinite(r) & np.isfinite(rh)
             & (p > 0) & (p <= 1100) & (t > -150) & (t < 60)
             & (rh >= 0) & (rh <= 100) & (e < p) & (r >= 0))
    p, r = p[valid], r[valid]
    # Keep decreasing pressures in ascent order, avoiding inversions/duplicates.
    keep, lowest = [], np.inf
    for i, pressure in enumerate(p):
        if pressure < lowest:
            keep.append(i)
            lowest = pressure
    p, r = p[keep], r[keep]
    if len(p) < 2:
        raise ValueError('Fewer than two valid ascent humidity levels')
    observed = integrate_pwv(p, r)
    gap = float(np.max(-np.diff(p)))
    reasons = []
    if p[-1] > 100:
        reasons.append('Sounding does not reach 100 hPa')
    if launch-p[0] > 20:
        reasons.append('More than 20 hPa missing near launch')
    if gap > 100:
        reasons.append('Humidity gap exceeds 100 hPa')
    return dict(pwv_mm=np.nan if reasons else observed, pwv_observed_mm=observed,
                pwv_status='partial' if reasons else 'ok', pwv_bottom_hpa=float(p[0]),
                pwv_top_hpa=float(p[-1]), pwv_max_gap_hpa=gap, pwv_levels=len(p),
                pwv_error='; '.join(reasons))


def catalog_pwv(cases, manifest, sounding_root, output, progress=None):
    """Compute every case; reuse unchanged soundings and checkpoint every 25 cases."""
    output = Path(output)
    try:
        saved = pd.read_csv(output, keep_default_na=False, dtype=str)
        cache = {row['cache_key']: row for row in saved.to_dict('records')}
    except (OSError, ValueError, KeyError):
        cache = {}
    basename_index = None
    def resolve(value):
        nonlocal basename_index
        original = Path(str(value)).expanduser()
        for candidate in (original, Path(manifest).resolve().parent/original):
            if candidate.is_file():
                return candidate.resolve()
        if sounding_root:
            if basename_index is None:
                basename_index = {}
                for candidate in Path(sounding_root).expanduser().rglob('*'):
                    if candidate.suffix.lower() in ('.nc', '.cdf') and candidate.is_file():
                        basename_index.setdefault(candidate.name, set()).add(candidate.resolve())
            matches = basename_index.get(original.name, set())
            if len(matches) == 1:
                return next(iter(matches))
            if matches:
                raise ValueError('Ambiguous sounding basename: '+original.name)
        raise FileNotFoundError('Sounding not found: '+str(value))
    rows, reused = [], 0
    for number, case in enumerate(cases.itertuples(), 1):
        row = dict(case_id=case.case_id, sounding_file=case.sounding_file, cache_key='',
                   pwv_status='error', pwv_error='', **{c: np.nan for c in COLUMNS if c not in ('pwv_status', 'pwv_error')})
        try:
            path = resolve(case.sounding_file)
            stat = path.stat()
            key = hashlib.sha256(f'{VERSION}|{path}|{stat.st_size}|{stat.st_mtime_ns}'.encode()).hexdigest()
            row.update(cache_key=key, sounding_file=str(path))
            if key in cache and cache[key].get('pwv_status') in ('ok', 'partial'):
                row.update({c: cache[key][c] for c in COLUMNS})
                reused += 1
            else:
                row.update(sounding_pwv(path))
                cache[key] = row.copy()
        except Exception as exc:
            row['pwv_error'] = str(exc)
            LOG.warning('PWV %s: %s', case.case_id, exc)
        rows.append(row)
        if number % 25 == 0 or number == len(cases):
            atomic_text(output, pd.DataFrame(rows).to_csv(index=False), catalog=True)
            if progress:
                progress(number, len(cases), reused)
            LOG.info('PWV %d/%d cases (%d cached)', number, len(cases), reused)
    result = pd.DataFrame(rows, columns=['case_id', 'sounding_file', 'cache_key']+COLUMNS)
    for column in COLUMNS:
        if column not in ('pwv_status', 'pwv_error'):
            result[column] = pd.to_numeric(result[column], errors='coerce')
    if cases.empty:
        atomic_text(output, result.to_csv(index=False), catalog=True)
    return result


def pwv_cache_path(manifest, output):
    identity = hashlib.sha256(str(Path(manifest).expanduser().resolve()).encode()).hexdigest()[:12]
    return Path(output)/('sounding_pwv_'+identity+'.csv')


def main():
    import config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default=config.CLOUD_MASTER_MANIFEST or config.CLOUD_SCREEN_MANIFEST)
    parser.add_argument('--sounding-root', default=config.SONDE_DIR)
    parser.add_argument('--output', help='Defaults to the same per-master cache used by the app')
    args = parser.parse_args()
    args.output = args.output or str(pwv_cache_path(args.manifest, config.CLOUD_CLASSIFICATION_DIR))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    results = catalog_pwv(read_manifest(args.manifest), args.manifest, args.sounding_root, args.output)
    print(results.pwv_status.value_counts().to_string())
    print('Saved '+args.output)


if __name__ == '__main__':
    main()
