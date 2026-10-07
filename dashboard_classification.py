"""Unclassified master data, reproducible classifications, and durable review decisions."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import errno
from shared_outputs import atomic_text, shared_csv, shared_directory

import numpy as np
import pandas as pd

CATEGORIES = ('clear_sky', 'not_clear_sky', 'uncertain')
CLASS_COLUMNS = {'category', 'classification', 'reason', 'asi_state', 'asi_reason',
                 'radiance_state', 'radiance_reason', 'automatic_category', 'manual_category',
                 'classification_source', 'Case', 'Classification', 'ASI classification', 'Radiance classification'}


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strip_classifications(frame):
    return frame.drop(columns=[c for c in frame if c in CLASS_COLUMNS]).copy()


def prepare_master(source):
    """Reuse clean input, or create one stable, unclassified sibling of a legacy CSV."""
    source = Path(source).expanduser().resolve()
    frame = pd.read_csv(source, dtype={'case_id': str})
    required = {'case_id', 'sounding_file', 'retrieval_time'}
    if not required.issubset(frame) or frame.case_id.isna().any() or frame.case_id.duplicated().any() or frame.empty:
        raise ValueError('Master requires unique case_id, sounding_file, retrieval_time, and at least one case')
    clean = strip_classifications(frame)
    if list(clean.columns) == list(frame.columns):
        return source
    content = clean.to_csv(index=False)
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    target = source.parent/('master_manifest_'+digest+'.csv')
    if not target.exists():
        atomic_text(target, content)
    elif target.read_text() != content:
        raise ValueError('Master destination has unexpected contents: '+str(target))
    return target


@dataclass(frozen=True)
class ClassificationRules:
    window: str = 'core'
    use_asi: bool = True
    use_radiance: bool = True
    combine: str = 'either'
    asi_zenith_max: float = 0.
    asi_total_max: float = 10.
    radiance_mean_max: float = 7.
    radiance_std_max: float = .3

    def __post_init__(self):
        if self.window not in ('core', 'context') or self.combine not in ('either', 'both'):
            raise ValueError('Invalid classification window or combination rule')
        if not self.use_asi and not self.use_radiance:
            raise ValueError('Enable ASI, radiance, or both')
        for name in ('asi_zenith_max', 'asi_total_max', 'radiance_mean_max', 'radiance_std_max'):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0:
                raise ValueError('Thresholds must be finite and nonnegative')
        if self.asi_total_max > 100 or self.asi_zenith_max > 100:
            raise ValueError('Cloud percentages cannot exceed 100')


def instrument_state(frame, limits):
    values = pd.DataFrame({key: pd.to_numeric(frame[key], errors='coerce') if key in frame else np.nan for key in limits}, index=frame.index)
    finite = np.isfinite(values)
    passed = finite.all(axis=1) & values.le(pd.Series(limits)).all(axis=1)
    failed = (finite & values.gt(pd.Series(limits))).any(axis=1)
    return pd.Series(np.select([passed, failed], ['clear_sky', 'not_clear_sky'], default='uncertain'), index=frame.index)


def classify(frame, rules, overrides=None):
    """Apply three-valued rules to all master cases; overrides have final precedence."""
    result = strip_classifications(frame)
    w = rules.window
    result['asi_state'] = instrument_state(result, {f'asi_{w}_zenith_mean': rules.asi_zenith_max, f'asi_{w}_total_mean': rules.asi_total_max}) if rules.use_asi else 'disabled'
    result['radiance_state'] = instrument_state(result, {f'radiance_{w}_radiance_mean': rules.radiance_mean_max, f'radiance_{w}_radiance_std': rules.radiance_std_max}) if rules.use_radiance else 'disabled'
    columns = (['asi_state'] if rules.use_asi else [])+(['radiance_state'] if rules.use_radiance else [])
    states = result[columns]
    clear = states.eq('clear_sky').any(axis=1) if rules.combine == 'either' else states.eq('clear_sky').all(axis=1)
    cloudy = states.eq('not_clear_sky').all(axis=1) if rules.combine == 'either' else states.eq('not_clear_sky').any(axis=1)
    result['automatic_category'] = np.select([clear, cloudy], ['clear_sky', 'not_clear_sky'], default='uncertain')
    result['category'] = result.automatic_category
    result['classification_source'] = 'thresholds'
    for case, decision in (overrides or {}).items():
        category = decision['category'] if isinstance(decision, dict) else decision
        if category not in CATEGORIES:
            raise ValueError('Invalid stored manual category: '+str(category))
        hit = result.case_id == case
        result.loc[hit, 'category'] = category
        result.loc[hit, 'classification_source'] = 'manual'
    return result


class ReviewStore:
    """SQLite transactions preserve concurrent reviews and their complete audit history."""
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        shared_directory(self.root)
        self.db = self.root/'manual_reviews.sqlite3'
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS reviews (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, category TEXT, note TEXT NOT NULL, image_path TEXT NOT NULL, reviewer TEXT NOT NULL, created_utc TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(str(self.db), timeout=30)

    def snapshot(self):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT * FROM reviews ORDER BY id').fetchall()
        current = {}
        for row in rows:
            if row['category'] is None:
                current.pop(row['case_id'], None)
            else:
                current[row['case_id']] = dict(row)
        return current, (rows[-1]['id'] if rows else 0)

    def save(self, case_id, category, note='', image_path='', reviewer=''):
        if not case_id or (category is not None and category not in CATEGORIES):
            raise ValueError('Invalid review decision')
        with self.connect() as conn:
            conn.execute('INSERT INTO reviews(case_id, category, note, image_path, reviewer, created_utc) VALUES (?, ?, ?, ?, ?, ?)',
                         (str(case_id), category, note, str(image_path), reviewer, now()))

    def history(self):
        with self.connect() as conn:
            return pd.read_sql_query('SELECT * FROM reviews ORDER BY id', conn)


def classification_directory_name(rules):
    """Readable criteria; exact values are also retained in settings.json."""
    number = lambda value: str(float(value)).removesuffix('.0')
    asi = ('ASI-z'+number(rules.asi_zenith_max)+'-t'+number(rules.asi_total_max)) if rules.use_asi else 'ASI-off'
    rad = ('RAD-m'+number(rules.radiance_mean_max)+'-s'+number(rules.radiance_std_max)) if rules.use_radiance else 'RAD-off'
    return '_'.join([rules.window, asi, rad, rules.combine])


def save_run(master_path, frame, rules, store):
    """Snapshot decisions and rules; final directory appears only after all files exist."""
    overrides, revision = store.snapshot()
    result = classify(frame, rules, overrides)
    run_id = classification_directory_name(rules)
    root = store.root/'runs'
    shared_directory(root)
    temporary = Path(tempfile.mkdtemp(prefix='.pending_', dir=root))
    settings = dict(schema_version=1, created_utc=now(), rules=asdict(rules),
                    master_manifest=str(Path(master_path).resolve()), master_sha256=fingerprint(master_path),
                    manual_revision=revision, counts=result.category.value_counts().to_dict(),
                    rule_definition='window mean ASI cloud percentages and radiance mean/std; inclusive maxima; missing evidence uncertain; manual override wins')
    try:
        shared_csv(result[['case_id', 'category']], temporary/'classification.csv', index=False)
        atomic_text(temporary/'settings.json', json.dumps(settings, indent=2, allow_nan=False)+'\n')
        case_ids = set(frame.case_id)
        relevant = {k: v for k, v in overrides.items() if k in case_ids}
        atomic_text(temporary/'manual_overrides.json', json.dumps(relevant, indent=2)+'\n')
        shared_directory(temporary)
        sequence = 1
        while True:
            destination = root/(run_id if sequence == 1 else run_id+'__'+str(sequence))
            if destination.exists():
                sequence += 1
                continue
            try:
                # Published runs always contain files: a concurrent writer's run
                # cannot be replaced by rename. Retry with the next sequence.
                os.rename(temporary, destination)
                break
            except OSError as exc:
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                sequence += 1
    except Exception:
        import shutil
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return result, destination/'classification.csv'


def read_selection_manifest(manifest, classification=None):
    """Read legacy combined manifests or join a saved compact snapshot to its master."""
    manifest = Path(manifest).expanduser().resolve()
    frame = pd.read_csv(manifest, dtype={'case_id': str})
    if classification:
        selection_path = Path(classification).expanduser().resolve()
        master_path = manifest
    elif 'category' in frame and 'sounding_file' not in frame:
        selection_path = manifest
        settings = json.loads((selection_path.parent/'settings.json').read_text())
        master_path = Path(settings['master_manifest'])
    elif 'category' in frame:
        return frame
    else:
        raise ValueError('Master is unclassified. Apply rules in TROPoe_APP.py, then set CLOUD_CLASSIFICATION_MANIFEST to the saved classification.csv path.')
    settings = json.loads((selection_path.parent/'settings.json').read_text())
    if fingerprint(master_path) != settings['master_sha256']:
        raise ValueError('Master has changed since this classification was saved; apply a new classification')
    master = strip_classifications(pd.read_csv(master_path, dtype={'case_id': str}))
    labels = pd.read_csv(selection_path, dtype={'case_id': str})
    if set(labels.columns) != {'case_id', 'category'} or labels.case_id.duplicated().any() or master.case_id.duplicated().any() or set(labels.case_id) != set(master.case_id):
        raise ValueError('Classification must have exactly one row for every master case')
    if not labels.category.isin(CATEGORIES).all():
        raise ValueError('Invalid classification category')
    joined = master.merge(labels, on='case_id', validate='one_to_one')
    joined['sounding_file'] = joined.sounding_file.map(lambda value: str((master_path.parent/str(value)).resolve()) if not Path(str(value)).is_absolute() else str(value))
    return joined


def satellite_inventory(root):
    """Read timestamped PNG names recursively, including GROUP_NAME subdirectories.

    The prefix is the requested image time, not necessarily the actual GOES scan
    time. satellite.py's group_plot obtains it from the Ch1 output filename.
    """
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError('Satellite directory is not available: '+str(root))
    inventory = []
    # os.walk exposes permission errors that Path.rglob can silently suppress.
    def failed(exc):
        raise exc
    for directory, _, files in os.walk(root, onerror=failed):
        for name in files:
            if Path(name).suffix.lower() != '.png' or not name[:12].isdigit():
                continue
            stamp = pd.to_datetime(name[:12], format='%Y%m%d%H%M', utc=True, errors='coerce')
            if not pd.isna(stamp):
                inventory.append((stamp, Path(directory)/name))
    return sorted(inventory, key=lambda item: (item[0], str(item[1])))


def match_satellite_images(inventory, sounding_time, retrieval_time=None, tolerance_minutes=0):
    """Prefer exact launch/retrieval minutes, then nearest to retrieval (or launch).

    Tied nearest timestamps are all returned for explicit image selection. Never
    pick an unbounded nearest image; zero tolerance disables the nearby fallback.
    """
    if not np.isfinite(tolerance_minutes) or tolerance_minutes < 0:
        raise ValueError('Satellite time tolerance must be finite and nonnegative')
    targets = []
    for label, value in [('sounding', sounding_time), ('retrieval', retrieval_time)]:
        stamp = pd.to_datetime(value, utc=True, errors='coerce')
        if stamp is not None and not pd.isna(stamp):
            targets.append((label, stamp.floor('min')))
    for label, stamp in targets:
        matches = [dict(path=p, time=t, offset_minutes=0.) for t, p in inventory if t == stamp]
        if matches:
            return dict(matches=matches, basis='exact '+label+' minute', reference_time=stamp)
    if not targets:
        return dict(matches=[], basis='invalid case times', reference_time=None)
    label, target = targets[-1]  # Retrieval when available, otherwise sounding.
    candidates = [(abs((stamp-target).total_seconds())/60., stamp, path) for stamp, path in inventory]
    best = min((distance for distance, _, _ in candidates), default=float('inf'))
    matches = [dict(path=path, time=stamp, offset_minutes=(stamp-target).total_seconds()/60.)
               for distance, stamp, path in candidates
               if distance == best and distance <= tolerance_minutes]
    return dict(matches=matches, basis='nearest to '+label+' minute', reference_time=target)


def satellite_images(root, sounding_time, retrieval_time=None, tolerance_minutes=0):
    """Compatibility helper returning paths; nearby matching is explicit opt-in."""
    if not Path(root).expanduser().is_dir():
        return []
    result = match_satellite_images(satellite_inventory(root), sounding_time, retrieval_time, tolerance_minutes)
    return [item['path'] for item in result['matches']]

