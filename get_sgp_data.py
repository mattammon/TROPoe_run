###############################

start_date = '2025-01-26'
end_date = '2025-03-20'
cloud_cover_perc_range = [0,0]
cloud_cover_variable = 'near_zenith_percent_cloud'

###############################

from config import *
import os
import glob
import pandas as pd
import xarray as xr
import numpy as np
from datetime import datetime, timedelta

streams = {
    'ch1':'sgpaerich1C1.b1',
    'ch2':'sgpaerich2C1.b1',
    'eng':'sgpaeriengineerC1.b1',
    'sum':'sgpaerisummaryC1.b1',
    'asi':'sgpasiskycoverC1.b1',
    'sonde':'sgpsondewnpnC1.b1'
}

args = f'{login} -ds {streams["sonde"]} -s {start_date} -e {end_date} -o {SONDE_DIR}'
os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

args = f'{login} -ds {streams["asi"]} -s {start_date} -e {end_date} -o {ASI_DIR}'
os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

cc_min = cloud_cover_perc_range[0]
cc_max = cloud_cover_perc_range[1]
asi_files_keep = []

sonde_files = sorted(glob.glob(f'{SONDE_DIR}/sgpsonde*'))
for f in sonde_files:
    date_str = f[-19:-11]
    time_str = f[-10:-6]
    asi_file = sorted(glob.glob(f'{ASI_DIR}/sgpasiskycover*{date_str}*'))[0]
    ds_asi = xr.open_dataset(asi_file)
    time_asi = ds_asi.time.data
    perc_cld = ds_asi[cloud_cover_variable].data
    ds_asi.close()

    dt = datetime.strptime(f'{date_str}{time_str}','%Y%m%d%H%M')
    tdiffs = abs(pd.to_datetime(time_asi) - dt)
    if min(tdiffs) < pd.to_timedelta('15min'):
        idx = np.argmin(tdiffs)
        if (cc_min <= perc_cld[idx] <= cc_max):
            asi_files_keep.append(asi_file)

            sdate = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
            edate = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'

            args = f'{login} -ds {streams["ch1"]} -s {sdate} -e {edate} -o {CH1_DIR}'
            os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

            args = f'{login} -ds {streams["ch2"]} -s {sdate} -e {edate} -o {CH2_DIR}'
            os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

            args = f'{login} -ds {streams["sum"]} -s {sdate} -e {edate} -o {SUM_DIR}'
            os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

            args = f'{login} -ds {streams["eng"]} -s {sdate} -e {edate} -o {ENG_DIR}'
            os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')

        else:
            os.system(f'rm {f}')
    else:
        os.system(f'rm {f}')
