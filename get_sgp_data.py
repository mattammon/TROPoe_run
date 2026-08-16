###############################

start_date = '2025-01-01'
end_date = '2025-02-01'
cloud_cover_perc_range = [0,0]
cloud_cover_variable = 'near_zenith_percent_cloud'
#cloud_cover_variable = 'percent_cloud'

###############################

from config import *
import os
import glob
import pandas as pd
import xarray as xr
import numpy as np
from datetime import datetime, timedelta




class SGP_DATA:
    streams = {
    'ch1':'sgpaerich1C1.b1',
    'ch2':'sgpaerich2C1.b1',
    'eng':'sgpaeriengineerC1.b1',
    'sum':'sgpaerisummaryC1.b1',
    'asi':'sgpasiskycoverC1.b1',
    'sonde':'sgpsondewnpnC1.b1',
    'sfc':'sgpmetE13.b1'
    }
    #### ARM Profile ####
    username = 'ammo0000'
    token = '1135d911aebbb142'
    #####################
    def __init__(self,sdate,edate):
        self.login = f'-u {self.username}:{self.token}'
        self.start_date = f'{sdate[:4]}-{sdate[4:6]}-{sdate[6:]}'
        self.end_date = f'{edate[:4]}-{edate[4:6]}-{edate[6:]}'


    def group_data(self,GROUP=GROUP_NAME,cloud_cover_perc_range=None,
                   cloud_cover_variable='near_zenith_percent_cloud'):
        self.directory_setup(GROUP)

        if "clear_sky" in GROUP:
            cloud_cover_perc_range = [0,0]

        if cloud_cover_perc_range is not None:
            check_cloud_cover = True
            cc_min = cloud_cover_perc_range[0]
            cc_max = cloud_cover_perc_range[1]
            self.dataset_download("asi",ASI_DIR,self.start_date,self.end_date)

        self.dataset_download("sonde",f'{SONDE_DIR}/{GROUP}',self.start_date,self.end_date)
        self.cloud_cover_filter(cc_min,cc_max,cloud_cover_variable)


    def cloud_cover_filter(self,cc_min,cc_max,cc_var):
        sonde_files = sorted(glob.glob(f'{SONDE_DIR}/{GROUP}/{SITE}sonde*'))
        for f in sonde_files:
            date_str = f[-19:-11]
            time_str = f[-10:-6]
            asi_file = sorted(glob.glob(f'{ASI_DIR}/{SITE}*{date_str}*'))[0]
            ds_asi = xr.open_dataset(asi_file)
            time_asi = ds_asi.time.data
            perc_cld = ds_asi[cc_var].data
            if cc_max <= 10 and cc_var=='near_zenith_percent_cloud':
                perc_cld_full = ds_asi['percent_cloud'].data
            else:
                perc_cld_full = None
            ds_asi.close()

            dt = datetime.strptime(f'{date_str}{time_str}','%Y%m%d%H%M')
            tdiffs = abs(pd.to_datetime(time_asi) - dt)
            if min(tdiffs) < pd.to_timedelta('15min'):
                idx = np.argmin(tdiffs)
                if (perc_cld_full is None or perc_cld_full[idx] <= 10) and (cc_min <= perc_cld[idx] <= cc_max):
                    sdate = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
                    edate = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
                    self.download_data_retrieval(self,sdate,edate)
                else:
                    os.system(f'rm {f}')
            else:
                os.system(f'rm {f}')


    def dataset_download(self,stream,stream_dir,sdate,edate):
        date_args = f'-s {sdate} -e {edate}'
        if stream == "sonde":
            dir_arg = f'-o {stream_dir}'
        else:
            dir_arg = f'-o {stream_dir}/{MASTER_DATA_FOLDER}'
        args = f'{self.login} -ds {self.streams[stream]} {date_args} {dir_arg}'
        os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')


    def download_data_retrieval(self,sdate,edate):
        self.dataset_download("ch1",CH1_DIR,sdate,edate)
        self.dataset_download("ch2",CH2_DIR,sdate,edate)
        self.dataset_download("sum",SUM_DIR,sdate,edate)
        self.dataset_download("eng",ENG_DIR,sdate,edate)
        self.dataset_download("sfc",SFC_DIR,sdate,edate)


    def group_dir_setup(self,group):
        subdir = group

        directories = [FIG_SUBDIR,SONDE_DIR,ASI_DIR,
                       CH1_DIR,CH2_DIR,SUM_DIR,
                       ENG_DIR,SFC_DIR,RETRIEVAL_DIR]

        for directory in directories:
            directory = f'{directory}/{subdir}'
            if not os.path.isdir(directory):
                try:
                    os.makedirs(directory, exist_ok=True)
                    print(f"Created/Verified: {directory}")
                except PermissionError:
                    print(f"Permission denied: {directory}. Try updating DATA_DIR in config.py to a local path.")
                except Exception as e:
                    print(f"Error creating {directory}: {e}")






















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
    if cc_max <= 10 and cloud_cover_variable=='near_zenith_percent_cloud':
        perc_cld_full = ds_asi['percent_cloud'].data
    else:
        perc_cld_full = None
    ds_asi.close()

    dt = datetime.strptime(f'{date_str}{time_str}','%Y%m%d%H%M')
    tdiffs = abs(pd.to_datetime(time_asi) - dt)
    if min(tdiffs) < pd.to_timedelta('15min'):
        idx = np.argmin(tdiffs)
        if (perc_cld_full is None or perc_cld_full[idx] <= 10) and (cc_min <= perc_cld[idx] <= cc_max):
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

            args = f'{login} -ds {streams["sfc"]} -s {sdate} -e {edate} -o {SFC_DIR}'
            os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')
        else:
            os.system(f'rm {f}')
    else:
        os.system(f'rm {f}')



def download_datasets():
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

    args = f'{login} -ds {streams["sfc"]} -s {sdate} -e {edate} -o {SFC_DIR}'
    os.system(f'python {RUN_DIR}/armlive_getfiles/src/getFiles.py {args}')
