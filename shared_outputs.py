"""Explicit shared permissions for generated CSVs, independent of process umask."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


def shared_directory(path, exist_ok=True):
    """Allow directory listing/traversal without granting new directory write access."""
    path = Path(path)
    missing = []
    ancestor = path
    while not ancestor.exists():
        missing.append(ancestor)
        ancestor = ancestor.parent
    path.mkdir(mode=0o755, parents=True, exist_ok=exist_ok)
    for directory in reversed(missing):
        directory.chmod(0o755)
    mode = path.stat().st_mode & 0o7777
    if mode | 0o555 != mode:
        path.chmod(mode | 0o555)
    return path


@contextmanager
def shared_output(path):
    """Write a complete file atomically; CSVs get 777, other metadata gets 644."""
    path = Path(path)
    shared_directory(path.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=path.parent, delete=False) as stream:
            temporary = stream.name
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o777 if path.suffix.lower() == '.csv' else 0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text(path, text):
    with shared_output(path) as stream:
        stream.write(text)


def shared_csv(frame, path, **kwargs):
    with shared_output(path) as stream:
        frame.to_csv(stream, **kwargs)
