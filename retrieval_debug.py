"""Isolated TROPoe debug runs; preserve diagnostics from successes and failures."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def publish_netcdf(source, destination, clobber):
    """Publish a complete file atomically; respect no-clobber under races."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.debug_publish_', dir=destination.parent)
    os.close(fd)
    try:
        shutil.copy2(source, name)
        if clobber:
            os.replace(name, destination)
        else:
            try:
                os.link(name, destination)
            except FileExistsError:
                return False
        return True
    finally:
        Path(name).unlink(missing_ok=True)


def run_debug(dt_str, dt, vip, channel, band, verbose, root, prior_file):
    model = 'Ch1' if channel == 1 else 'Ch2_B'+str(band)
    parent = Path(root).expanduser().resolve()/str(dt_str)/model
    parent.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_'), dir=parent))
    original_output = Path(vip.output_dir).expanduser().resolve()
    local = copy.copy(vip)
    local.vip_file = str(attempt/'vip.txt')
    local.lbl_temp_dir = str(attempt/'work')
    local.output_dir = str(attempt/'output')
    Path(local.lbl_temp_dir).mkdir()
    Path(local.output_dir).mkdir()
    script = Path('TROPoe.py').resolve()
    hr = f'{dt.hour + dt.minute / 60:.2f}'
    command = [sys.executable, str(script), dt.strftime('%Y%m%d'), local.vip_file,
               str(Path(prior_file).expanduser().resolve()), '--shour='+hr,
               '--ehour='+hr, '--verbose='+str(verbose), '--debug']
    metadata = dict(requested_case_time=dt_str, rounded_retrieval_time=dt.isoformat(),
                    model=model, command=command, shared_output=str(original_output),
                    status='preparing', published=[], preserved_existing=[])
    def record():
        temp = attempt/'run.json.tmp'
        temp.write_text(json.dumps(metadata, indent=2)+'\n')
        temp.replace(attempt/'run.json')
    record()
    print('Debug diagnostics: '+str(attempt), flush=True)
    try:
        local.write_vip(irs_channel=channel, band=band)
        metadata['status']='running'
        record()
        # Absolute script path preserves imports; unique cwd preserves vip.npy.
        subprocess.run(command, cwd=str(attempt), check=True)
        metadata['status']='publishing'
        for path in sorted(Path(local.output_dir).glob('*.nc')):
            target = original_output/path.name
            key = 'published' if publish_netcdf(path,target,bool(local.clobber)) else 'preserved_existing'
            metadata[key].append(str(target))
        metadata['status']='finished'
        metadata['netcdf_count']=len(list(Path(local.output_dir).glob('*.nc')))
        print('Debug run finished; diagnostics retained in '+str(attempt),flush=True)
    except BaseException as exc:
        metadata['status']='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed'
        metadata['error']=str(exc)
        metadata['returncode']=getattr(exc,'returncode',None)
        raise
    finally:
        metadata['finished_utc']=datetime.now(timezone.utc).isoformat()
        record()
    return attempt

