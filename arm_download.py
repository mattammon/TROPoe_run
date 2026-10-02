"""Small ARM Live Data client: validated files, atomic downloads, no token logging."""
import os
import logging
import time
from pathlib import Path
import tempfile

import json
from urllib.parse import urlencode
from urllib.request import urlopen
import xarray as xr


logger = logging.getLogger(__name__)


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
        started = time.monotonic()
        logger.info('Querying ARM catalog: %s [%s, %s]; request timeout=120s', stream, start, end)
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
        names = sorted(set(names))
        logger.info('Catalog returned %d files in %.1fs', len(names), time.monotonic()-started)
        records = []
        for number, name in enumerate(names, 1):
            file_started = time.monotonic()
            logger.info('File %d/%d: %s', number, len(names), name)
            path = directory/name
            record = {'stream': stream, 'filename': name, 'path': str(path.resolve()), 'status': 'unavailable'}
            temporary = None
            try:
                if path.exists():
                    logger.info('Validating existing file: %s', path)
                    validate_netcdf(path)
                    record['status'] = 'existing'
                else:
                    logger.info('Downloading %s; network timeout=180s', name)
                    received, last_report = 0, time.monotonic()
                    with tempfile.NamedTemporaryFile(dir=directory, prefix=name+'.', suffix='.part', delete=False) as out:
                        temporary = Path(out.name)
                        url = self.endpoint+'saveData?'+urlencode({'user': self._credentials, 'file': name})
                        with urlopen(url, timeout=180) as response:
                            while chunk := response.read(1024*1024):
                                out.write(chunk)
                                received += len(chunk)
                                if time.monotonic()-last_report >= 15:
                                    logger.info('%s: received %.1f MiB', name, received/1024**2)
                                    last_report = time.monotonic()
                    logger.info('Validating downloaded %s (%.1f MiB)', name, received/1024**2)
                    validate_netcdf(temporary)
                    os.replace(temporary, path)
                    record['status'] = 'downloaded'
            except Exception as exc:
                record['error'] = type(exc).__name__
                logger.error('%s: download/validation failed (%s); file unavailable', name, type(exc).__name__)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            logger.info('%s: %s (%.1fs)', name, record['status'], time.monotonic()-file_started)
            records.append(record)
        return records
