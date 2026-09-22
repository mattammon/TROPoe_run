"""Small ARM Live Data client: validated files, atomic downloads, no token logging."""
import os
from pathlib import Path
import tempfile

import json
from urllib.parse import urlencode
from urllib.request import urlopen
import xarray as xr


class CatalogError(RuntimeError):
    pass


def validate_netcdf(path):
    with xr.open_dataset(path) as ds:
        if not ds.variables:
            raise ValueError('Empty NetCDF dataset')


class ARMClient:
    endpoint = 'https://adc.arm.gov/armlive/livedata/'

    def __init__(self):
        username, token = os.environ.get('ARM_USERNAME'), os.environ.get('ARM_TOKEN')
        if not username or not token:
            raise ValueError('Set ARM_USERNAME and ARM_TOKEN for downloads, or use --offline')
        self._credentials = f'{username}:{token}'

    def download(self, stream, start, end, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Do not propagate HTTP exceptions: their URLs can contain credentials.
        try:
            url = self.endpoint+'query?'+urlencode({
                'user': self._credentials, 'ds': stream, 'start': start,
                'end': end, 'wt': 'json'})
            with urlopen(url, timeout=120) as response:
                payload = json.load(response)
            names = payload['files']
            if payload['status'] != 'success' or not isinstance(names, list):
                raise ValueError('Unsuccessful catalog response')
            if any(not isinstance(n, str) or Path(n).name != n or '\\' in n
                   or not n.startswith(stream+'.') for n in names):
                raise ValueError('Unexpected catalog filename')
        except Exception as exc:
            raise CatalogError(f'ARM catalog failed for {stream} ({type(exc).__name__}); check credentials/service') from None
        records = []
        for name in sorted(set(names)):
            path = directory/name
            record = {'stream': stream, 'filename': name, 'path': str(path.resolve()), 'status': 'unavailable'}
            temporary = None
            try:
                if path.exists():
                    validate_netcdf(path)
                    record['status'] = 'existing'
                else:
                    with tempfile.NamedTemporaryFile(dir=directory, prefix=name+'.', suffix='.part', delete=False) as out:
                        temporary = Path(out.name)
                        url = self.endpoint+'saveData?'+urlencode({'user': self._credentials, 'file': name})
                        with urlopen(url, timeout=180) as response:
                            while chunk := response.read(1024*1024):
                                out.write(chunk)
                    validate_netcdf(temporary)
                    os.replace(temporary, path)
                    record['status'] = 'downloaded'
            except Exception as exc:
                record['error'] = type(exc).__name__
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            records.append(record)
        return records
