"""Saved case membership and band choices; retrieval outputs are shared."""
from spectralBands import available_ch2_bands
import json
import errno
import os
import re
import tempfile
from pathlib import Path
import pandas as pd
from shared_outputs import atomic_text, shared_csv, shared_directory


def selected_cases(frame):
    if 'collection_selected' in frame:
        return frame.loc[frame.collection_selected.eq(True)].copy()
    return frame.loc[frame.category.eq('clear_sky')].copy()


def validate_models(models):
    from retrieval_todo import normalize_skip_bands, expected_models
    parsed = normalize_skip_bands(models)
    if not parsed:
        raise ValueError('Select at least one retrieval band')
    return [m for m in expected_models(available_ch2_bands()) if m in parsed]


def save_bands(manifest, models):
    models = validate_models(models)
    atomic_text(Path(manifest).parent/'group_bands.json', json.dumps({'models': models}, indent=2)+'\n', catalog=True)
    return models


def read_bands(manifest, default=None):
    path = Path(manifest).parent/'group_bands.json'
    if path.is_file():
        return validate_models(json.loads(path.read_text())['models'])
    return validate_models(default) if default is not None else None


def save_collection(master, frame, ids, name, rules, output, models):
    from dataclasses import asdict
    from dashboard_classification import fingerprint, now
    ids = set(map(str, ids))
    if not ids or not ids.issubset(set(frame.case_id.astype(str))):
        raise ValueError('Choose at least one valid master case')
    name = name.strip()
    slug = re.sub(r'[^A-Za-z0-9_-]+', '-', name).strip('-_')[:100]
    if not slug:
        raise ValueError('Enter a collection name containing letters or numbers')
    models = validate_models(models)
    root = Path(output)/'collections'
    shared_directory(root, writable=True)
    pending = Path(tempfile.mkdtemp(prefix='.pending_', dir=root))
    try:
        membership = frame.loc[frame.case_id.astype(str).isin(ids), ['case_id']]
        shared_csv(membership, pending/'collection.csv', index=False, catalog=True)
        settings = dict(kind='manual_collection', name=name, schema_version=1,
            master_manifest=str(Path(master).resolve()), master_sha256=fingerprint(master),
            created_utc=now(), rules=asdict(rules), case_count=len(membership))
        atomic_text(pending/'settings.json', json.dumps(settings, indent=2)+'\n', catalog=True)
        save_bands(pending/'collection.csv', models)
        shared_directory(pending, writable=True)
        seq = 1
        while True:
            destination = root/(slug if seq == 1 else slug+'__'+str(seq))
            try:
                if destination.exists():
                    seq += 1
                    continue
                os.rename(pending, destination)
                return destination/'collection.csv'
            except OSError as exc:
                if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
                seq += 1
    except Exception:
        import shutil
        shutil.rmtree(pending, ignore_errors=True)
        raise


def read_collection(path):
    from dashboard_classification import fingerprint, strip_classifications
    path = Path(path).resolve()
    settings = json.loads((path.parent/'settings.json').read_text())
    master = Path(settings['master_manifest'])
    if settings.get('kind') != 'manual_collection' or fingerprint(master) != settings['master_sha256']:
        raise ValueError('Collection master changed or collection settings are invalid')
    frame = strip_classifications(pd.read_csv(master, dtype={'case_id':str}))
    ids = pd.read_csv(path, dtype={'case_id':str})
    if list(ids.columns) != ['case_id'] or ids.empty or ids.case_id.isna().any() or ids.case_id.duplicated().any() or frame.case_id.duplicated().any() or not set(ids.case_id).issubset(set(frame.case_id)):
        raise ValueError('Invalid collection case membership')
    frame = frame.loc[frame.case_id.isin(ids.case_id)].copy()
    frame['category'] = 'unknown'
    frame['collection_selected'] = True
    frame['sounding_file'] = frame.sounding_file.map(lambda v: str((master.parent/str(v)).resolve()) if not Path(str(v)).is_absolute() else str(v))
    return frame


def saved_collections(root):
    result, errors = [], []
    for path in Path(root).rglob('collection.csv'):
        if any(p.startswith('.pending_') for p in path.parts):
            continue
        try:
            settings = json.loads((path.parent/'settings.json').read_text())
            result.append(dict(path=str(path.resolve()), name=settings['name'], rules=settings['rules'],
                master=settings['master_manifest'], created=settings['created_utc'],
                label=f"Collection: {settings['name']} · {settings['case_count']} selected cases"))
        except (OSError, ValueError, KeyError) as exc:
            errors.append(dict(path=str(path), error=str(exc)))
    return result, errors


def restore_collection(path):
    from dashboard_classification import ClassificationRules, classify, ReviewStore
    from dashboard_data import read_manifest
    path = Path(path).resolve()
    settings = json.loads((path.parent/'settings.json').read_text())
    chosen = read_collection(path)
    source_cases = read_manifest(settings['master_manifest'])
    for field in ('retrieval_time', 'sounding_time'):
        chosen[field] = pd.to_datetime(chosen[field], utc=True, errors='raise')
    root = path.parent.parent.parent
    store = ReviewStore(root)
    overrides, _ = store.snapshot()
    classified = classify(chosen, ClassificationRules(**settings['rules']), overrides)
    classified['collection_selected'] = True
    return dict(master=settings['master_manifest'], master_hash=settings['master_sha256'],
                cases=source_cases, output=str(root)), dict(cases=classified, path=str(path),
                rules=settings['rules'], kind='manual_collection', name=settings['name']), False
