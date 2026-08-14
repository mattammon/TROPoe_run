import sys, os
from datetime import datetime
from config import *
from utils import *
import glob


def run_tropoe(dt_str,VIP_obj,vip_type='default',channel=None,band=None,verbose='1'):

    VIP_obj.write_vip(vip_type=vip_type,irs_channel=channel,band=band)

    dt = datetime.strptime(dt_str,'%Y%m%d%H%M')
    date = dt_str[:8]
    hr = datetime_to_decimal_hours([dt])[0]
    start_hr = hr
    end_hr = hr
    vip_file = VIP_obj.vip_file
    prior_file = 'prior.MIDLAT.nc'

    os.system(f'python TROPoe.py {date} {vip_file} {DATA_DIR}/{prior_file} --shour={start_hr} --ehour={end_hr} --verbose={verbose}')

    print('####### DONE #######')
