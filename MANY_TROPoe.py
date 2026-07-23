import sys, os
import pandas as pd
from datetime import datetime
from config import *
from utils import *
from vip_gen import write_vip
import glob

##########################################

obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/*sonde*'))
dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]

bands = [1,2,3,4,5,6,7,8,9,10,11,12]

##########################################

for b in bands:
    for i,d in enumerate(dates[20:]):
        write_vip(data_path=GROUP_SUBDIR,
                irs_channel=2,
                band=b)
        dt = datetime.strptime(d,'%Y%m%d%H%M')

        date = d[:8]
        hr = datetime_to_decimal_hours([dt])[0]
        start_hr = hr
        end_hr = hr
        vip_file = f'{VIP_DIR}/curr_VIP.txt'
        prior_file = 'prior.MIDLAT.nc'
        verbose = '1'
        data_root = DATA_DIR

        os.system(f'python TROPoe.py {date} {vip_file} {data_root}/{prior_file} --shour={start_hr} --ehour={end_hr} --verbose={verbose}')

        print('####### DONE #######')
