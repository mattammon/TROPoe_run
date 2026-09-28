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


def scan(root):
    files, profiles = [], []
    paths = sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in ('.nc', '.cdf') and NAME.match(p.name))
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
                for name in ('temperature', 'waterVapor', 'height'):
                    if name not in ds:
                        raise ValueError('Missing required variable '+name)
                # Require an unambiguous time axis. Only read one profile at a time.
                time_dim = ds['time'].dims[0] if 'time' in ds and ds['time'].ndim == 1 else ds['time_offset'].dims[0]
                for i, t in enumerate(times):
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
                row['status'] = ('empty' if not len(times) else 'usable' if row['n_usable'] == len(times)
                                 else 'partial' if row['n_usable'] else 'no_usable_profiles')
        except Exception as exc:
            row['error'] = '%s: %s' % (type(exc).__name__, exc)
            LOG.warning('%s: %s', path, row['error'])
        files.append(row)
    return files, profiles


def expected_cases(manifest, profiles, bands, include_ch1, category, tolerance):
    with manifest.open(newline='') as f:
        reader = csv.DictReader(f)
        needed = {'case_id', 'sounding_time', 'retrieval_time', 'category'}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError('Manifest requires '+', '.join(sorted(needed)))
        cases = [r for r in reader if r['category'] == category]
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


def write_csv(path, fields, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    import config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retrieval-dir', type=Path, default=Path(config.RETRIEVAL_DIR)/config.GROUP_NAME)
    parser.add_argument('--manifest', type=Path, default=config.CLOUD_SCREEN_MANIFEST)
    parser.add_argument('--inventory-only', action='store_true', help='Do not compare against a manifest')
    parser.add_argument('--bands', nargs='+', type=int, default=[17], help='Expected Ch2 bands; default: 17')
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
                   completion_definition='Readable time-matched profiles with finite T/q and increasing heights; not scientific QC or convergence certification.')
    (out/'summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    LOG.info('Catalog saved: %s', out.resolve())
    LOG.info('Expected retrievals: %s', summary['cases'])


if __name__ == '__main__':
    main()
