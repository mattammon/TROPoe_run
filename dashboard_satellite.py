"""Run a single satellite image request outside the Streamlit process."""
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd


def generate_satellite_image(sounding_time, output_dir, timeout=180):
    stamp = pd.to_datetime(sounding_time, utc=True, errors='raise')
    if pd.isna(stamp):
        raise ValueError('Sounding has no valid UTC time')
    root = Path(output_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    prefix = stamp.strftime('%Y%m%d%H%M')
    def existing():
        return sorted(p for p in root.glob(prefix+'*.png') if p.is_file() and p.stat().st_size > 0)
    if existing():
        return 'Using existing image: '+str(existing()[0])
    script = Path(__file__).resolve().with_name('satellite.py')
    command = [os.environ.get('TROPOE_SATELLITE_PYTHON') or sys.executable, '-u', str(script),
               stamp.strftime('%Y%m%d'), stamp.strftime('%H'), stamp.strftime('%M'),
               '--output-dir', str(root)]
    environment = dict(os.environ, MPLBACKEND='Agg', PYTHONUNBUFFERED='1')
    try:
        result = subprocess.run(command, cwd=str(script.parent), env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ''
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='replace')
        raise RuntimeError(f'Satellite generation timed out after {timeout}s.\n'+output[-12000:]) from exc
    output = result.stdout or ''
    if result.returncode:
        raise RuntimeError(f'satellite.py exited with status {result.returncode}.\n'+output[-12000:])
    if not existing():
        raise RuntimeError('satellite.py finished without creating the expected '+prefix+'*.png in '+str(root)+'\n'+output[-12000:])
    return output[-12000:] or 'Satellite image generated.'
