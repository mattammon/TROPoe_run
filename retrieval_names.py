"""Names of retrievals launched at quarter-hour times by SINGLE_TROPoe."""
from datetime import datetime, timedelta


def retrieval_stamp(date):
    """Round a YYYYMMDDHHMM case to the nearest quarter hour, half up."""
    rounded = datetime.strptime(date, '%Y%m%d%H%M') + timedelta(minutes=7, seconds=30)
    return rounded.replace(minute=rounded.minute // 15 * 15, second=0).strftime('%Y%m%d.%H%M')


def completed_retrieval(date, channel, catalog_files, band=None):
    root = f'tropoeOutput_Ch{channel}' + (f'_B{band}' if band is not None else '')
    stem = f'{root}.{retrieval_stamp(date)}00.'
    return any(name.startswith(stem) and name[len(stem):] in ('nc', 'cdf') for name in catalog_files)
