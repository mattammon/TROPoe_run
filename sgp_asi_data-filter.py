import xarray as xr
from datetime import datetime, timedelta
from typing import Iterable
import numpy as np
import glob
import pandas as pd

import os, sys
sys.path.append('scripts')
from utils import datetime_to_decimal_hours as dt_to_hr

#####################################

RUNDIR = '/Users/matthew.ammon/PhD_Stuff'

CLOUD_COVER_PERC_RANGE = [0,0]
CLOUD_COVER_VARIABLE = 'near_zenith_percent_cloud'
SGP_DATA_DIR = f'{RUNDIR}/TROPoe/data/SGP_Data'
IRS_CHANNEL = 2

FILE_NAME = 'clear_sky'

#####################################


def SGP_snd_cldcvr_filter(perc_cloud_range,channel,directory,var):
    cc_min, cc_max = perc_cloud_range
    dir = directory
    snd_files = sorted(glob.glob(f'{dir}/sgpsonde*'))
    asi_files = sorted(glob.glob(f'{dir}/sgpasiskycover*'))
    irs_files = sorted(glob.glob(f'{dir}/sgpaerich{channel}*'))

    snd_dates = [i[-19:-11] for i in snd_files]
    asi_dates = [i[-18:-10] for i in asi_files]
    irs_dates = [i[-18:-10] for i in irs_files]

    all_dates = []
    for d in np.unique(snd_dates):
        if d in asi_dates:
            if d in irs_dates:
                all_dates.append(d)

    clear_sky_dates = []
    time_strs = []
    clear_sky_dts = []
    cloud_covers = []

    for d in all_dates:
        asi_file = sorted(glob.glob(f'{dir}/sgpasiskycover*{d}*'))[0]
        ds_asi = xr.open_dataset(asi_file)
        time_asi = ds_asi.time.data
        perc_cld = ds_asi[var].data
        ds_asi.close()

        snd_files_d = sorted(glob.glob(f'{dir}/sgpsonde*{d}*'))
        for i in snd_files_d:
            time = i[-10:-6]
            dt = datetime.strptime(f'{d}{time}','%Y%m%d%H%M')
            tdiffs = abs(pd.to_datetime(time_asi) - dt)
            if min(tdiffs) < pd.to_timedelta('15min'):
                idx = np.argmin(tdiffs)
                if (cc_min <= perc_cld[idx] <= cc_max):
                    clear_sky_dates.append(d)
                    time_strs.append(time)
                    clear_sky_dts.append(dt)
                    cloud_covers.append(perc_cld[idx])

    return clear_sky_dates, time_strs, clear_sky_dts, cloud_covers


if __name__ == "__main__":
    dates, tms, dts, cld_cvs = SGP_snd_cldcvr_filter(CLOUD_COVER_PERC_RANGE,
                                                IRS_CHANNEL,
                                                SGP_DATA_DIR,
                                                CLOUD_COVER_VARIABLE)


    df = pd.DataFrame({'date':dates,
                       'time':tms,
                       'hr_dec':dt_to_hr(dts),
                       'perc_cloud':cld_cvs})

    df.to_csv(f'{RUNDIR}/{FILE_NAME}_sgp_sounding_times.csv')

