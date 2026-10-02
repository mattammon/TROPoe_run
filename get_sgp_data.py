"""Download and classify SGP sounding cases without deleting source data.

Run ``python get_sgp_data.py --help``; see CLOUD_SCREENING.md for policy details.
"""
import argparse
from collections import Counter, OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
import math
from numbers import Real
import time as clock
from pathlib import Path
import re
import subprocess
import uuid

import pandas as pd
import xarray as xr

import config
from arm_download import ARMClient, CatalogError
from cloud_screening import (CATEGORIES, ScreenPolicy, dataset_times, evaluate_case,
                             filename_time, read_asi, read_radiance)


logger = logging.getLogger(__name__)

def json_safe(value):
    """Represent unavailable/nonfinite diagnostics as standard JSON null."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, Real) and not math.isfinite(value):
        return None
    return value


def parse_date(value):
    value = str(value)
    if not re.fullmatch(r'\d{8}|\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Dates must be YYYYMMDD or YYYY-MM-DD')
    return pd.to_datetime(value, format='%Y%m%d' if '-' not in value else '%Y-%m-%d')


def index_files(directory, stream):
    """Include legacy group folders; prefer ALL for duplicate basenames."""
    candidates = sorted(Path(directory).glob(f'*/{stream}.*'))
    candidates.sort(key=lambda p: (p.parent.name != config.MASTER_DATA_FOLDER, str(p)))
    result = {}
    for p in candidates:
        if p.is_file() and p.suffix.lower() in ('.nc', '.cdf'):
            result.setdefault(p.name, p.resolve())
    return result


class ObservationCache:
    """Read only one spectral element; keep at most six daily frames in memory."""
    def __init__(self, paths, reader):
        self.by_day = {}
        self.reader = reader
        self.cache = OrderedDict()
        self.errors = {}
        for path in paths:
            try:
                day = filename_time(path).normalize()
            except ValueError:
                self.errors[str(path)] = 'filename_timestamp_unreadable'
                continue
            self.by_day.setdefault(day, []).append(path)

    def around(self, time, minutes):
        frames, files = [], []
        start = (time-pd.Timedelta(minutes=minutes/2)).normalize()
        end = (time+pd.Timedelta(minutes=minutes/2)).normalize()
        # Adjacent file days also cover files crossing UTC midnight.
        for day in pd.date_range(start-pd.Timedelta(days=1), end+pd.Timedelta(days=1)):
            for path in self.by_day.get(day, []):
                key = str(path)
                files.append(key)
                if key not in self.cache:
                    try:
                        logger.info('Reading observations: %s', path)
                        self.cache[key] = self.reader(path)
                    except Exception as exc:
                        logger.error('Observation read failed: %s: %s: %s', path, type(exc).__name__, exc)
                        logger.debug('Observation read traceback', exc_info=True)
                        self.errors[key] = f'{type(exc).__name__}: {exc}'
                        self.cache[key] = pd.DataFrame()
                    if len(self.cache) > 6:
                        self.cache.popitem(last=False)
                else:
                    logger.debug('Using cached observations: %s', path)
                    self.cache.move_to_end(key)
                frames.append(self.cache[key])
        return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
                {f: self.errors[f] for f in files if f in self.errors})


class SGP_DATA:
    streams = {'ch1': 'sgpaerich1nf1turnC1.c1', 'ch2': 'sgpaerich2nf1turnC1.c1',
               'eng': 'sgpaeriengineerC1.b1', 'sum': 'sgpaerisummaryC1.b1',
               'asi': 'sgpasiskycoverC1.b1', 'sonde': 'sgpsondewnpnC1.b1',
               'sfc': 'sgpmetE13.b1'}

    def __init__(self, sdate, edate, *, directories=None, client=None):
        self.start, self.end = parse_date(sdate), parse_date(edate)
        if self.end < self.start:
            raise ValueError('End date precedes start date')
        if config.SITE != 'sgp':
            raise ValueError('This downloader supports SGP only')
        self.start_date, self.end_date = self.start.strftime('%Y-%m-%d'), self.end.strftime('%Y-%m-%d')
        self.directories = directories or {
            'sonde': config.SONDE_DIR, 'asi': config.ASI_DIR, 'ch1': config.CH1_DIR,
            'ch2': config.CH2_DIR, 'eng': config.ENG_DIR, 'sum': config.SUM_DIR, 'sfc': config.SFC_DIR}
        self.client = client
        self.download_log = []

    def dataset_download(self, stream, stream_dir, sdate, edate):
        logger.info('Download stage: %s [%s, %s] -> %s', stream, sdate, edate, stream_dir)
        if self.client is None:
            self.client = ARMClient()
        try:
            records = self.client.download(self.streams[stream], sdate, edate,
                                           Path(stream_dir)/config.MASTER_DATA_FOLDER)
        except CatalogError as exc:
            logger.error('%s', exc)
            self.download_log.append({'stream': stream, 'start': sdate, 'end': edate,
                                      'status': 'catalog_failed', 'error': str(exc)})
            raise
        self.download_log.append({'stream': stream, 'start': sdate, 'end': edate,
                                  'status': 'catalog_complete', 'files': records})
        logger.info('Download stage complete: %s; %s', stream, dict(Counter(r['status'] for r in records)))
        return records

    def download_data_retrieval(self, sdate, edate):
        for key in ('ch1', 'ch2', 'sum', 'eng', 'sfc'):
            records = self.dataset_download(key, self.directories[key], sdate, edate)
            if any(r['status'] == 'unavailable' for r in records) or not records:
                raise RuntimeError(f'Retrieval input download incomplete for {key} on {sdate}')

    def single_data_download(self):
        self.download_data_retrieval(self.start_date, self.end_date)

    def group_data_download(self, cloud_cover_perc_range=None,
                            cloud_cover_variable='near_zenith_percent_cloud', **kwargs):
        if cloud_cover_perc_range not in (None, [0, 0], (0, 0)) or cloud_cover_variable != 'near_zenith_percent_cloud':
            raise ValueError('Legacy range filtering is replaced by ScreenPolicy; see CLOUD_SCREENING.md')
        return self.screen_cases(**kwargs)

    def screen_cases(self, *, policy=None, offline=False, output_dir=None, retrieval_data='clear_sky'):
        started = clock.monotonic()
        policy = policy or ScreenPolicy()
        logger.info('Screening UTC dates %s through %s; offline=%s; retrieval_data=%s', self.start_date, self.end_date, offline, retrieval_data)
        logger.info('Effective policy: %s', json.dumps(asdict(policy), sort_keys=True))
        if policy.radiance_clear_mean_max is None or policy.radiance_clear_std_max is None:
            logger.warning('Radiance clear thresholds are not configured; radiances cannot establish clear sky')
        if retrieval_data not in ('clear_sky', 'all', 'none'):
            raise ValueError('retrieval_data must be clear_sky, all, or none')
        catalog_sondes = []
        if not offline:
            # A failed sounding catalog must not masquerade as a complete inventory.
            catalog_sondes = self.dataset_download('sonde', self.directories['sonde'], self.start_date, self.end_date)
            first = (self.start-pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            last = (self.end+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
            for key in ('asi', 'ch1'):
                try:
                    self.dataset_download(key, self.directories[key], first, last)
                except CatalogError:
                    pass  # Persist failure; missing observations cannot establish clear sky.
        indices = {key: index_files(directory, self.streams[key]) for key, directory in self.directories.items()}
        logger.info('Local inventory (all dates): %s', {k: len(v) for k, v in indices.items()})
        sondes = dict(indices['sonde'])
        for record in catalog_sondes:
            sondes.setdefault(record['filename'], Path(record['path']))
        longitude, latitude = config.site_coordinates['sgp']
        asi = ObservationCache(indices['asi'].values(), lambda p: read_asi(p, policy, latitude, longitude))
        rad = ObservationCache(indices['ch1'].values(), lambda p: read_radiance(p, policy))
        cases, inventory_errors = [], []
        for name, path in sorted(sondes.items()):
            try:
                time = filename_time(name)
            except ValueError:
                inventory_errors.append({'file': str(path), 'reason': 'filename_timestamp_unreadable'})
                continue
            if not self.start <= time < self.end+pd.Timedelta(days=1):
                continue
            logger.info('Case %d: %s; sounding=%s', len(cases)+1, time, path)
            a, a_errors = asi.around(time, policy.context_minutes)
            r, r_errors = rad.around(time, policy.context_minutes)
            case = evaluate_case(time, a, r, policy)
            case.update(case_id=time.strftime('%Y%m%dT%H%M%S')+'_'+name,
                        sounding_file=str(path), sounding_filename=name, time_source='ARM_filename',
                        read_errors={**a_errors, **r_errors})
            try:
                with xr.open_dataset(path) as ds:
                    times = dataset_times(ds)
                    if len(times) == 0 or pd.isna(times[0]):
                        raise ValueError('Sounding has no valid launch time')
                    case['sounding_first_observation_time'] = times[0].isoformat()
                    if abs((times[0]-time).total_seconds()) > 300:
                        raise ValueError('Sounding observation and filename times differ by more than 5 minutes')
            except Exception as exc:
                logger.error('Sounding validation failed: %s: %s: %s', path, type(exc).__name__, exc)
                logger.debug('Sounding validation traceback', exc_info=True)
                case['category'], case['reason'] = 'uncertain', 'sounding_unavailable_or_time_invalid'
                case['read_errors'][str(path)] = f'{type(exc).__name__}: {exc}'
            case['radiance_wavenumbers'] = sorted(r.actual_wavenumber.dropna().unique().tolist()) if not r.empty else []
            case['qc_fields'] = {kind: sorted(frame.qc_fields.unique().tolist()) if not frame.empty else []
                                 for kind, frame in [('asi', a), ('radiance', r)]}
            case['asi_uncertainty_fields'] = sorted(a.uncertainty_fields.unique().tolist()) if not a.empty else []
            logger.info('Case result: %s — %s; ASI=%s (%s); radiance=%s (%s)', case['category'], case['reason'], case['evidence']['asi']['state'], case['evidence']['asi']['reason'], case['evidence']['radiance']['state'], case['evidence']['radiance']['reason'])
            cases.append(case)

        # Download other raw streams once per selected day; never use retrieval success as a cloud label.
        wanted_days = sorted({c['sounding_time'][:10] for c in cases
                              if retrieval_data == 'all' or (retrieval_data == 'clear_sky' and c['category'] == 'clear_sky')})
        logger.info('Screened %d cases; ancillary retrieval downloads selected for %d days (offline=%s)', len(cases), len(wanted_days), offline)
        if not cases:
            logger.warning('No soundings found within requested dates')
        if not offline:
            for day in wanted_days:
                for key in ('ch2', 'sum', 'eng', 'sfc'):
                    try:
                        self.dataset_download(key, self.directories[key], day, day)
                    except CatalogError:
                        pass
            indices = {key: index_files(directory, self.streams[key]) for key, directory in self.directories.items()}
        datasets_by_day = {}
        for key, entries in indices.items():
            datasets_by_day[key] = {}
            for name, path in entries.items():
                try:
                    file_day = filename_time(name).normalize()
                except ValueError:
                    continue
                datasets_by_day[key].setdefault(file_day, []).append(str(path))
        for case in cases:
            day = pd.Timestamp(case['sounding_time']).normalize()
            case['datasets'] = {'sonde': [case['sounding_file']]}
            for key in self.streams:
                if key != 'sonde':
                    offsets = (-1, 0, 1) if key in ('asi', 'ch1') else (0,)
                    case['datasets'][key] = sorted({p for offset in offsets
                        for p in datasets_by_day[key].get(day+pd.Timedelta(days=offset), [])})
        policy_json = json.dumps(asdict(policy), sort_keys=True)
        policy_hash = hashlib.sha256(policy_json.encode()).hexdigest()[:12]
        root = Path(output_dir) if output_dir else Path(config.DATA_DIR)/'cloud_screening'/config.SITE
        run_name = f'{self.start:%Y%m%d}_{self.end:%Y%m%d}_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_{policy_hash}_{uuid.uuid4().hex[:8]}'
        run_dir = root/run_name
        logger.info('Writing manifests and category links: %s', run_dir)
        run_dir.mkdir(parents=True, exist_ok=False)
        for category in CATEGORIES:
            (run_dir/category).mkdir()
        for case in cases:
            source = Path(case['sounding_file'])
            if source.is_file():
                try:
                    (run_dir/case['category']/source.name).symlink_to(source)
                except OSError as exc:
                    logger.warning('Could not link sounding %s: %s', source, exc)
                    case['organization_error'] = str(exc)
        rows = []
        for case in cases:
            row = {key: case[key] for key in ('case_id', 'sounding_time', 'retrieval_time', 'sounding_file', 'category', 'reason')}
            row['policy_hash'] = policy_hash
            row['read_errors'] = json.dumps(case['read_errors'], sort_keys=True)
            for kind, evidence in case['evidence'].items():
                row[kind+'_state'], row[kind+'_reason'] = evidence['state'], evidence['reason']
                for window in ('core', 'context'):
                    for key, value in evidence[window].items():
                        if key != 'files':
                            row[f'{kind}_{window}_{key}'] = value
            row['datasets'] = json.dumps(case['datasets'], sort_keys=True)
            rows.append(row)
        # Write the completion marker last. Interrupted runs have no metadata.json.
        pd.DataFrame(rows, columns=None if rows else ['case_id', 'sounding_time', 'retrieval_time', 'sounding_file', 'category', 'reason']).to_csv(run_dir/'manifest.csv', index=False)
        (run_dir/'cases.json').write_text(json.dumps(json_safe(cases), indent=2, allow_nan=False)+'\n')
        (run_dir/'policy.json').write_text(json.dumps(asdict(policy), indent=2)+'\n')
        (run_dir/'downloads.json').write_text(json.dumps(self.download_log, indent=2)+'\n')
        try:
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent, stderr=subprocess.DEVNULL, text=True).strip()
        except (OSError, subprocess.CalledProcessError):
            revision = 'unavailable'
        metadata = {'schema_version': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
                    'start_date_inclusive': self.start_date, 'end_date_inclusive': self.end_date,
                    'scope': 'locally_available_soundings' if offline else 'ARM_live_catalog_and_local_soundings',
                    'catalog_scope_note': 'ARM Live Data covers online files; not an assertion of historical archive completeness.',
                    'git_revision': revision, 'policy_hash': policy_hash, 'radiance_units': 'mW/(m2 sr cm-1)',
                    'counts': {k: Counter(c['category'] for c in cases)[k] for k in CATEGORIES},
                    'inventory_errors': inventory_errors, 'retrieval_data_requested': retrieval_data,
                    'offline': offline, 'manifest': str((run_dir/'manifest.csv').resolve())}
        (run_dir/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
        logger.info('Completed in %.1fs: %s', clock.monotonic()-started, metadata['counts'])
        for kind in ('asi', 'radiance'):
            logger.info('%s reason totals: %s', kind, dict(Counter(c['evidence'][kind]['reason'] for c in cases)))
        print(json.dumps(metadata['counts']))
        print(f"Manifest: {(run_dir/'manifest.csv').resolve()}")
        return run_dir/'manifest.csv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('start', nargs='?', help='First UTC date, inclusive (YYYY-MM-DD or YYYYMMDD)')
    parser.add_argument('end', nargs='?', help='Last UTC date, inclusive')
    parser.add_argument('--offline', action='store_true', help='Classify local files without credentials or network calls')
    parser.add_argument('--policy', type=Path, help='JSON policy overrides (unlisted fields retain defaults)')
    parser.add_argument('--output-dir', type=Path, help='Parent directory for a new immutable screening run')
    parser.add_argument('--retrieval-data', choices=('clear_sky', 'all', 'none'), default='clear_sky')
    parser.add_argument('--write-default-policy', type=Path, help='Write a policy template and exit')
    parser.add_argument('--log-level', choices=('DEBUG', 'INFO', 'WARNING', 'ERROR'), default='INFO', help='Console verbosity (default: INFO)')
    parser.add_argument('--log-file', type=Path, help='Append timestamped output to this file as well as the console')
    args = parser.parse_args()
    handlers = [logging.StreamHandler()]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding='utf-8'))
    logging.basicConfig(level=getattr(logging, args.log_level),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
                        handlers=handlers, force=True)
    if args.write_default_policy:
        with args.write_default_policy.open('x') as out:
            out.write(json.dumps(asdict(ScreenPolicy()), indent=2)+'\n')
        return
    if not args.start or not args.end:
        parser.error('start and end dates are required')
    policy = ScreenPolicy.from_json(args.policy) if args.policy else ScreenPolicy()
    SGP_DATA(args.start, args.end).screen_cases(policy=policy, offline=args.offline,
        output_dir=args.output_dir, retrieval_data=args.retrieval_data)


if __name__ == '__main__':
    main()
