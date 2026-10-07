"""Clear-sky retrieval plans and execution against live NetCDF completion evidence."""
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from catalog_retrievals import scan, NAME
from dashboard_classification import atomic_text, read_selection_manifest
from spectralBands import ch2_bands

LOG = logging.getLogger(__name__)
FIELDS = ['case_id', 'sounding_time', 'retrieval_time', 'sounding_file', 'category',
          'channel', 'band', 'model', 'reason', 'classification_manifest', 'retrieval_dir', 'tolerance_seconds']


def expected_models(bands):
    bands = sorted(set(int(b) for b in bands))
    if any('band'+str(b) not in ch2_bands for b in bands):
        raise ValueError('Unknown Ch2 band in RETRIEVAL_TODO_BANDS')
    return ['Ch1']+['Ch2_B'+str(b) for b in bands]


def profile_index(profiles):
    frame = pd.DataFrame(profiles)
    if frame.empty:
        return pd.DataFrame(columns=['file', 'time', 'status', 'model'])
    frame['time'] = pd.to_datetime(frame.time, utc=True, errors='coerce')
    frame['model'] = ['Ch1' if int(c) == 1 else 'Ch2_B'+str(int(b)) for c, b in zip(frame.channel, frame.band)]
    return frame.loc[frame.time.notna()].sort_values(['model', 'time'])


def pending_retrievals(cases, index, bands, classification_manifest, retrieval_dir, tolerance=60.):
    if not np.isfinite(tolerance) or not 0 <= tolerance < 450:
        raise ValueError('Completion tolerance must be finite and between 0 and 450 seconds (exclusive upper limit)')
    clear = cases.loc[cases.category == 'clear_sky'].copy()
    rows = []
    for model in expected_models(bands):
        subset = index.loc[index.model == model]
        usable = np.sort(pd.to_datetime(subset.loc[subset.status == 'usable', 'time'], utc=True).dt.as_unit('ns').astype('int64').to_numpy())
        all_times = np.sort(pd.to_datetime(subset.time, utc=True).dt.as_unit('ns').astype('int64').to_numpy())
        def found(times, target):
            pos = np.searchsorted(times, target-int(tolerance*1e9))
            return pos < len(times) and times[pos] <= target+int(tolerance*1e9)
        for case in clear.itertuples():
            target = pd.to_datetime(case.retrieval_time, utc=True, errors='raise')
            if pd.isna(target):
                raise ValueError('Invalid retrieval time for '+str(case.case_id))
            if found(usable, target.value):
                continue
            rows.append(dict(case_id=str(case.case_id), sounding_time=pd.to_datetime(case.sounding_time, utc=True).isoformat(),
                retrieval_time=target.isoformat(), sounding_file=str(case.sounding_file), category='clear_sky',
                channel=1 if model == 'Ch1' else 2, band='' if model == 'Ch1' else model.split('_B')[1], model=model,
                reason='incomplete_output' if found(all_times, target.value) else 'missing_or_unreadable_output',
                classification_manifest=str(Path(classification_manifest).resolve()),
                retrieval_dir=str(Path(retrieval_dir).resolve()), tolerance_seconds=tolerance))
    return pd.DataFrame(rows, columns=FIELDS).sort_values(['sounding_time', 'case_id', 'channel', 'band']).reset_index(drop=True)


def save_todo(path, frame):
    atomic_text(path, frame.to_csv(index=False), catalog=True)


class LiveInventory:
    """Read changed files only; recheck file presence before every queued job."""
    def __init__(self, root, targets, models, tolerance):
        self.root = Path(root).resolve()
        self.targets, self.models, self.tolerance = targets, set(models), tolerance
        self.signatures, self.profiles = {}, {}

    def refresh(self):
        current = {}
        for p in self.root.rglob('*'):
            match = NAME.match(p.name)
            if not match or p.suffix.lower() not in ('.nc', '.cdf') or not p.is_file():
                continue
            ident = match.groupdict()
            model = 'Ch1' if ident['channel'] == '1' else 'Ch2_B'+str(int(ident['band']))
            if model not in self.models:
                continue
            stat = p.stat()
            current[str(p.resolve())] = (stat.st_mtime_ns, stat.st_size)
        changed = [Path(p) for p, sig in current.items() if self.signatures.get(p) != sig]
        for p in set(self.profiles)-set(current):
            self.profiles.pop(p, None)
        if changed:
            _, profiles = scan(self.root, self.targets, self.tolerance, self.models, paths=changed)
            for p in changed:
                self.profiles[str(p)] = []
            for profile in profiles:
                self.profiles[profile['file']].append(profile)
        self.signatures = current
        return profile_index([p for rows in self.profiles.values() for p in rows])


def execute_todo(path, retrieval_dir, run_one):
    """Run only pending pairs. Keep the input plan and write a separate execution report."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError('Retrieval to-do manifest is missing. Apply a classification in TROPoe_APP.py first: '+str(path))
    jobs = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not set(FIELDS).issubset(jobs):
        raise ValueError('Retrieval to-do manifest lacks required columns')
    if jobs.empty:
        LOG.info('Retrieval to-do manifest is empty; nothing to run.')
        return []
    root = Path(retrieval_dir).resolve()
    if any(Path(value).resolve() != root for value in jobs.retrieval_dir):
        raise ValueError('To-do retrieval directory differs from config.RETRIEVAL_DIR/GROUP_NAME')
    if not jobs.category.eq('clear_sky').all():
        raise ValueError('To-do manifest must contain only clear-sky cases')
    # Validate every row before starting any expensive retrieval.
    classifications = {}
    for row in jobs.itertuples():
        if row.classification_manifest not in classifications:
            classified = read_selection_manifest(row.classification_manifest)
            classifications[row.classification_manifest] = classified.set_index('case_id')
        classified = classifications[row.classification_manifest]
        if row.case_id not in classified.index or classified.loc[row.case_id, 'category'] != 'clear_sky':
            raise ValueError('Queued case is absent or not clear in its saved classification: '+row.case_id)
        case = classified.loc[row.case_id]
        for field in ('sounding_time', 'retrieval_time'):
            if pd.to_datetime(getattr(row, field), utc=True) != pd.to_datetime(case[field], utc=True):
                raise ValueError('Queued case time differs from its classification master: '+row.case_id)
        model = 'Ch1' if row.channel == '1' and row.band == '' else 'Ch2_B'+row.band if row.channel == '2' else ''
        if model != row.model or model not in expected_models(range(1, 19)):
            raise ValueError('Invalid queued channel/band: '+row.model)
        sounding = pd.to_datetime(row.sounding_time, utc=True).floor('min')
        rounded = (sounding+pd.Timedelta(minutes=7, seconds=30)).floor('15min')
        if rounded != pd.to_datetime(row.retrieval_time, utc=True):
            raise ValueError('Queued target does not match SINGLE_TROPoe quarter-hour rounding: '+row.case_id)
    tolerances = pd.to_numeric(jobs.tolerance_seconds)
    if not np.isfinite(tolerances).all() or (tolerances < 0).any() or (tolerances >= 450).any():
        raise ValueError('Invalid queued completion tolerance')
    live = LiveInventory(root, jobs.retrieval_time.unique(), jobs.model.unique(), float(tolerances.max()))
    results = []
    for number, row in enumerate(jobs.itertuples(), 1):
        LOG.info('To-do %d/%d: %s %s', number, len(jobs), row.case_id, row.model)
        def complete():
            index = live.refresh()
            target = pd.to_datetime(row.retrieval_time, utc=True)
            return bool(((index.model == row.model) & (index.status == 'usable') &
                         ((index.time-target).dt.total_seconds().abs() <= float(row.tolerance_seconds))).any()) if len(index) else False
        result = dict(case_id=row.case_id, model=row.model, status='', error='')
        try:
            if complete():
                result['status'] = 'already_complete'
            else:
                date = pd.to_datetime(row.sounding_time, utc=True).strftime('%Y%m%d%H%M')
                run_one(date, int(row.channel), None if row.channel == '1' else int(row.band))
                result['status'] = 'completed' if complete() else 'still_missing_or_incomplete'
        except Exception as exc:
            result.update(status='failed', error=str(exc))
            LOG.exception('Retrieval failed: %s %s', row.case_id, row.model)
        results.append(result)
        atomic_text(path.with_name(path.stem+'_last_run.csv'), pd.DataFrame(results).to_csv(index=False), catalog=True)
        LOG.info('%s: %s', row.model, result['status'])
    return results

