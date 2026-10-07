"""Inventory TROPoe files and compare usable T/q profiles with expected cases."""
import argparse
import csv
import json
import logging
from pathlib import Path
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import xarray as xr

from cloud_screening import dataset_times

LOG = logging.getLogger(__name__)
NAME = re.compile(r'^tropoeOutput_Ch(?P<channel>[12])(?:_B(?P<band>\d+))?\.')
FILE_FIELDS = ['file', 'channel', 'band', 'status', 'n_profiles', 'n_usable', 'size_bytes', 'modified_utc', 'error']
PROFILE_FIELDS = ['file', 'channel', 'band', 'profile_index', 'time', 'status', 'n_levels', 'n_finite_pairs', 'error']
CASE_FIELDS = ['case_id', 'sounding_time', 'retrieval_time', 'channel', 'band', 'status', 'n_matches', 'matched_file', 'profile_index', 'matched_time', 'offset_seconds', 'matching_files']


def scan(root, target_times=None, tolerance_seconds=60., models=None, paths=None):
    files, profiles = [], []
    paths = sorted(p for p in (root.rglob('*') if paths is None else paths)
                   if p.is_file() and p.suffix.lower() in ('.nc', '.cdf') and NAME.match(p.name))
    if models is not None:
        def model(path):
            ident = NAME.match(path.name).groupdict()
            return 'Ch1' if ident['channel'] == '1' else 'Ch2_B'+str(int(ident['band']))
        paths = [p for p in paths if model(p) in models]
    targets = None if target_times is None else np.sort(np.array([pd.Timestamp(t).value for t in pd.to_datetime(list(target_times), utc=True)], dtype=np.int64))
    if targets is not None and not len(targets):
        return files, profiles
    tolerance_ns = int(tolerance_seconds*1e9)
    LOG.info('Scanning %d retrieval files under %s', len(paths), root)
    for number, path in enumerate(paths, 1):
        ident = NAME.match(path.name).groupdict()
        row = dict(file=str(path.resolve()), channel=int(ident['channel']), band=ident['band'] or '',
                   status='unreadable', n_profiles=0, n_usable=0, size_bytes=0, modified_utc='', error='')
        LOG.info('[%d/%d] %s', number, len(paths), path)
        try:
            stat = path.stat()
            row.update(size_bytes=stat.st_size, modified_utc=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat())
            with xr.open_dataset(path) as ds:
                times = dataset_times(ds)
                row['n_profiles'] = len(times)
                selected_indices = list(range(len(times)))
                if targets is not None:
                    selected_indices = []
                    for i, timestamp in enumerate(times):
                        if pd.isna(timestamp):
                            continue
                        value = pd.Timestamp(timestamp).value
                        pos = np.searchsorted(targets, value-tolerance_ns)
                        if pos < len(targets) and targets[pos] <= value+tolerance_ns:
                            selected_indices.append(i)
                if not selected_indices:
                    row['status'] = 'outside_selection' if len(times) else 'empty'
                    files.append(row)
                    continue
                for name in ('temperature', 'waterVapor', 'height'):
                    if name not in ds:
                        raise ValueError('Missing required variable '+name)
                # Require an unambiguous time axis. Only read one profile at a time.
                time_dim = ds['time'].dims[0] if 'time' in ds and ds['time'].ndim == 1 else ds['time_offset'].dims[0]
                for i in selected_indices:
                    t = times[i]
                    pr = dict(file=row['file'], channel=row['channel'], band=row['band'], profile_index=i,
                              time='' if pd.isna(t) else pd.Timestamp(t).isoformat(), status='invalid',
                              n_levels=0, n_finite_pairs=0, error='')
                    try:
                        arrays = []
                        for name in ('temperature', 'waterVapor', 'height'):
                            da = ds[name]
                            if name != 'height' and time_dim not in da.dims:
                                raise ValueError(name+' lacks the time dimension')
                            if time_dim in da.dims:
                                da = da.isel({time_dim: i})
                            a = np.asarray(da.values, dtype=float)
                            if a.ndim != 1:
                                raise ValueError(name+' must be a vertical profile')
                            arrays.append(a)
                        temp, vapor, height = arrays
                        if not (temp.shape == vapor.shape == height.shape):
                            raise ValueError('T/q/height shapes differ')
                        pr['n_levels'] = len(height)
                        pr['n_finite_pairs'] = int((np.isfinite(temp) & np.isfinite(vapor) & np.isfinite(height)).sum())
                        if pd.isna(t) or len(height) < 2:
                            raise ValueError('Missing time or fewer than two levels')
                        if not np.all(np.isfinite(height)) or not np.all(np.diff(height) > 0):
                            raise ValueError('Invalid or non-increasing height grid')
                        if pr['n_finite_pairs'] == len(height):
                            pr['status'] = 'usable'
                            row['n_usable'] += 1
                        else:
                            pr['status'] = 'partial'
                            pr['error'] = 'Missing/nonfinite T or q values'
                    except Exception as exc:
                        pr['error'] = '%s: %s' % (type(exc).__name__, exc)
                    profiles.append(pr)
                row['status'] = ('empty' if not len(times) else 'usable' if row['n_usable'] == len(selected_indices)
                                 else 'partial' if row['n_usable'] else 'no_usable_profiles')
        except Exception as exc:
            row['error'] = '%s: %s' % (type(exc).__name__, exc)
            LOG.warning('%s: %s', path, row['error'])
        files.append(row)
    return files, profiles


def expected_cases(manifest, profiles, bands, include_ch1, category, tolerance):
    from dashboard_classification import read_selection_manifest
    frame = read_selection_manifest(manifest)
    needed = {'case_id', 'sounding_time', 'retrieval_time', 'category'}
    if not needed.issubset(frame):
        raise ValueError('Manifest requires '+', '.join(sorted(needed)))
    cases = frame.loc[frame.category == category].to_dict('records')
    configurations = ([(1, '')] if include_ch1 else []) + [(2, str(b)) for b in sorted(set(bands))]
    index = {}
    for p in profiles:
        if p['time']:
            index.setdefault((p['channel'], str(p['band'])), []).append(p)
    rows = []
    for case in cases:
        target = pd.to_datetime(case['retrieval_time'], utc=True, errors='coerce')
        for channel, band in configurations:
            row = dict(case_id=case['case_id'], sounding_time=case['sounding_time'], retrieval_time=case['retrieval_time'],
                       channel=channel, band=band, status='missing', n_matches=0, matched_file='', profile_index='',
                       matched_time='', offset_seconds='', matching_files='[]')
            if pd.isna(target):
                row['status'] = 'invalid_target_time'
            else:
                matches = []
                for p in index.get((channel, band), []):
                    delta = (pd.to_datetime(p['time'], utc=True)-target).total_seconds()
                    if abs(delta) <= tolerance:
                        matches.append((p, delta))
                good = [(p, d) for p, d in matches if p['status'] == 'usable']
                row['n_matches'] = len(good)
                row['matching_files'] = json.dumps(sorted({p['file'] for p, _ in matches}))
                if good:
                    p, delta = min(good, key=lambda x: (abs(x[1]), x[0]['file'], x[0]['profile_index']))
                    row.update(status='complete' if len(good) == 1 else 'duplicate', matched_file=p['file'],
                               profile_index=p['profile_index'], matched_time=p['time'], offset_seconds=delta)
                elif matches:
                    row['status'] = 'invalid_output'
            rows.append(row)
    return rows


def completed_by_band(cases, profiles, bands, include_ch1, has_manifest):
    """Count matched cases, or distinct usable profile times without a manifest."""
    counts = {('Ch1' if channel == 1 else 'Ch2_B'+str(band)): set()
              for channel, band in (([(1, '')] if include_ch1 else []) +
                                    [(2, b) for b in sorted(set(bands))])}
    for row in (cases if has_manifest else profiles):
        key = 'Ch1' if int(row['channel']) == 1 else 'Ch2_B'+str(row['band'])
        counts.setdefault(key, set())
        if has_manifest and row['status'] in ('complete', 'duplicate'):
            counts[key].add(row['case_id'])
        elif not has_manifest and row['status'] == 'usable':
            counts[key].add(row['time'])
    return {key: len(values) for key, values in counts.items()}


def write_csv(path, fields, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    import config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retrieval-dir', type=Path, default=Path(config.RETRIEVAL_DIR)/config.GROUP_NAME)
    parser.add_argument('--manifest', type=Path, default=getattr(config, 'CLOUD_CLASSIFICATION_MANIFEST', None) or config.CLOUD_SCREEN_MANIFEST)
    parser.add_argument('--inventory-only', action='store_true', help='Do not compare against a manifest')
    parser.add_argument('--bands', nargs='+', type=int, default=[1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18],
                        help='Expected Ch2 bands; default: all')
    parser.add_argument('--no-ch1', action='store_true', help='Exclude Ch1 from expected retrievals')
    parser.add_argument('--category', default=config.CLOUD_SCREEN_CATEGORY)
    parser.add_argument('--tolerance-seconds', type=float, default=60., help='Maximum absolute profile-time offset; default: 60')
    parser.add_argument('--output-dir', type=Path, help='Output folder; default: retrieval-dir/catalog')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not args.retrieval_dir.is_dir():
        parser.error('Retrieval directory does not exist: '+str(args.retrieval_dir))
    if not np.isfinite(args.tolerance_seconds) or args.tolerance_seconds < 0 or any(b < 1 for b in args.bands):
        parser.error('Tolerance must be finite and nonnegative; bands must be positive')
    manifest = Path(args.manifest) if args.manifest and not args.inventory_only else None
    if manifest is not None and not manifest.is_file():
        parser.error('Manifest does not exist: '+str(manifest))
    files, profiles = scan(args.retrieval_dir)
    cases = expected_cases(manifest, profiles, args.bands, not args.no_ch1, args.category, args.tolerance_seconds) if manifest else []
    out = args.output_dir or args.retrieval_dir/'catalog'
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out/'files.csv', FILE_FIELDS, files)
    write_csv(out/'profiles.csv', PROFILE_FIELDS, profiles)
    write_csv(out/'cases.csv', CASE_FIELDS, cases)
    write_csv(out/'pending.csv', CASE_FIELDS, [r for r in cases if r['status'] not in ('complete', 'duplicate')])
    from collections import Counter
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(), retrieval_dir=str(args.retrieval_dir.resolve()),
                   manifest=str(manifest.resolve()) if manifest else None, bands=args.bands, include_ch1=not args.no_ch1,
                   tolerance_seconds=args.tolerance_seconds, files=dict(Counter(r['status'] for r in files)),
                   profiles=dict(Counter(r['status'] for r in profiles)), cases=dict(Counter(r['status'] for r in cases)),
                   completed_by_band=completed_by_band(cases, profiles, args.bands, not args.no_ch1, manifest is not None),
                   completed_by_band_basis=('unique matched case IDs; duplicate outputs count once per case' if manifest else
                                            'distinct usable profile times across scanned files'),
                   completion_definition='Readable time-matched profiles with finite T/q and increasing heights; not scientific QC or convergence certification.')
    (out/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    LOG.info('Catalog saved: %s', out.resolve())
    LOG.info('Expected retrievals: %s', summary['cases'])


if __name__ == '__main__':
    main()

