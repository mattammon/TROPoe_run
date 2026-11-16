"""Conservative maintenance of saved selections and ARM retrieval inputs."""
from collections import Counter
from pathlib import Path
import shutil

import pandas as pd

import config
from cloud_screening import filename_time
from get_sgp_data import SGP_DATA


def delete_saved_catalog(root, manifest):
    """Remove exactly one published run or manual collection, never the review DB."""
    root = Path(root).expanduser().resolve(strict=True)
    manifest = Path(manifest).expanduser().absolute()
    if manifest.is_symlink():
        raise ValueError('Catalog symlinks cannot be deleted here')
    directory = manifest.parent.resolve(strict=True)
    allowed = {'classification.csv': 'runs', 'collection.csv': 'collections'}
    if directory.parent != root/allowed.get(manifest.name, '') or not manifest.is_file():
        raise ValueError('Selection is not a published catalog in this directory')
    if not (directory/'settings.json').is_file():
        raise ValueError('Catalog settings are missing')
    todo_path = getattr(config, 'RETRIEVAL_TODO_MANIFEST', None)
    todo = Path(todo_path) if todo_path else None
    clear_todo = False
    if todo and todo.is_file():
        queue = pd.read_csv(todo, usecols=['classification_manifest'])
        clear_todo = str(manifest.resolve()) in set(queue.classification_manifest.dropna().astype(str))
    shutil.rmtree(directory)
    if clear_todo:
        todo.unlink(missing_ok=True)


def retained_input_days(root, padding_minutes=None):
    """Union of padded retrieval days for every saved manual collection."""
    from case_collections import saved_collections, read_collection
    padding = float(config.RETRIEVAL_INPUT_PADDING_MINUTES if padding_minutes is None else padding_minutes)
    if not 0 <= padding < 1440:
        raise ValueError('Invalid retrieval input padding')
    collections, errors = saved_collections(root)
    if errors:
        raise ValueError('Cannot safely clean inputs: unreadable collections: '+str(errors))
    days = set()
    for item in collections:
        # read_collection verifies membership and the master fingerprint.
        frame = read_collection(item['path'])
        times = pd.to_datetime(frame.retrieval_time, utc=True, errors='raise')
        if times.isna().any():
            raise ValueError('Collection contains an invalid retrieval time')
        for time in times:
            days.update(day.strftime('%Y%m%d') for day in pd.date_range(
                (time-pd.Timedelta(minutes=padding)).normalize(),
                (time+pd.Timedelta(minutes=padding)).normalize()))
    return days, len(collections)


def plan_arm_cleanup(root, directories=None):
    """Preview recognized raw files outside retained days; unknown files are untouched."""
    days, count = retained_input_days(root)
    streams = dict(SGP_DATA.streams)
    streams.pop('asi')
    streams.pop('sonde')
    streams.pop('aod', None)  # AOD is diagnostic, not an input to the VIP.
    defaults = {'ch1': config.CH1_DIR, 'ch2': config.CH2_DIR, 'sum': config.SUM_DIR,
                'eng': config.ENG_DIR, 'sfc': config.SFC_DIR}
    directories = defaults if directories is None else directories
    candidates = []
    for stream, directory in directories.items():
        if stream not in streams:
            continue
        base = Path(directory).expanduser().absolute()
        if not base.is_dir() or base.is_symlink():
            continue
        for path in sorted(base.glob('*/*')) + sorted(base.glob('*')):
            # Only direct files in known stream roots or one level below.
            if path.parent != base and (path.parent.is_symlink() or path.parent.parent != base):
                continue
            if not (path.is_file() or path.is_symlink()) or path.is_dir():
                continue
            if not path.name.startswith(streams[stream]+'.') or path.suffix.lower() not in ('.nc', '.cdf'):
                continue
            try:
                day = filename_time(path).strftime('%Y%m%d')
            except ValueError:
                continue
            if day not in days:
                candidates.append(path)
    return candidates, count, days


def refresh_arm_catalog(root, directories=None):
    """Recompute the plan immediately before removing unreferenced raw files."""
    paths, count, days = plan_arm_cleanup(root, directories)
    totals = Counter()
    for path in paths:
        # A symlink is unlinked, not followed. Never recursively remove raw roots.
        size = 0 if path.is_symlink() else path.stat().st_size
        path.unlink()
        totals['files'] += 1
        totals['bytes'] += size
    return dict(totals), count, len(days)
