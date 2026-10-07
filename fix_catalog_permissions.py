"""Repair existing generated catalogs; run as their owner or the container user."""
import argparse
import os
from pathlib import Path


def repair(root):
    root = Path(root).expanduser()
    changed, errors = 0, []
    if not root.exists():
        return changed, errors
    def chmod(path, mode):
        nonlocal changed
        try:
            if path.stat().st_mode & 0o7777 != mode:
                path.chmod(mode)
                changed += 1
        except OSError as exc:
            errors.append(str(path)+': '+str(exc))
    if root.is_symlink():
        return changed, ['Skipping symlink root: '+str(root)]
    if root.is_file():
        if root.suffix.lower() == '.csv':
            chmod(root, 0o777)
        return changed, errors
    chmod(root, (root.stat().st_mode & 0o7777) | 0o555)
    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=lambda exc: errors.append(str(exc))):
        subdirs[:] = [name for name in subdirs if not (Path(directory)/name).is_symlink()]
        for name in subdirs:
            child = Path(directory)/name
            chmod(child, (child.stat().st_mode & 0o7777) | 0o555)
        for name in files:
            path = Path(directory)/name
            if path.is_symlink():
                continue
            if path.suffix.lower() == '.csv':
                chmod(path, 0o777)
    return changed, errors


def main():
    import config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', help='Directory to repair recursively; repeat for multiple roots. Defaults to configured catalog/figure directories.')
    args = parser.parse_args()
    roots = args.root or [Path(config.DATA_DIR)/'cloud_classification', Path(config.DATA_DIR)/'cloud_screening',
                         Path(config.RETRIEVAL_DIR)/config.GROUP_NAME/'catalog', Path(config.FIG_SUBDIR),
                         Path(config.CLOUD_CLASSIFICATION_DIR)]
    if not args.root and getattr(config, 'RETRIEVAL_TODO_MANIFEST', None):
        roots.append(Path(config.RETRIEVAL_TODO_MANIFEST).parent)
    failures = []
    for root in dict.fromkeys(roots):
        count, errors = repair(root)
        print(f'{root}: {count} permissions updated; {len(errors)} errors')
        failures.extend(errors)
    if failures:
        for error in failures:
            print(error)
        print('Run this command as the user/container that owns the files (or with administrator privileges).')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
