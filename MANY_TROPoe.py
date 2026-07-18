import sys, os
import pandas as pd
from config import *
from vip_gen import write_vip

##########################################

cc_type_title = 'clear_sky'

df = pd.read_csv(f'{SCRIPT_DIR}/{cc_type_title}_sgp_sounding_times.csv')
dates = df['date']
tms = df['hr_dec']

##########################################

for i,d in enumerate(dates[:20]):
    write_vip(data_path='/sgp/clear_sky_days',
              irs_channel=2,
              band=12)
    date = d
    start_hr = tms[i]
    end_hr = tms[i]
    vip_file = f'{VIP_DIR}/curr_VIP.txt'
    prior_file = 'prior.MIDLAT.nc'
    verbose = '1'
    data_root = DATA_DIR

    os.system(f'python TROPoe.py {date} {vip_file} {data_root}/{prior_file} --shour={start_hr} --ehour={end_hr} --verbose={verbose}')

    print('####### DONE #######')
