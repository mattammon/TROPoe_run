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


if __name__ == "__main__":
    import argparse
    from vip_gen import VIP
    from get_sgp_data import SGP_DATA

    VIP_obj = VIP()

    parser = argparse.ArgumentParser()

    parser.add_argument("date", type=str, help="Datetime string in format yyyymmddHHMM")

    parser.add_argument("--vipType", type=str, default='default', help="Type of Retrieval")
    parser.add_argument("--channel", type=int, default=1, help="IRS Channel (1 or 2)")
    parser.add_argument("--band", type=int, default=None, help="Band number (ONLY for channel-2)")
    parser.add_argument("--verbose", type=str, default='1', help="Retrieval Verbosity")
    parser.add_argument("--group", action="store_true", help="Include Retrieval in GROUP_SUBDIR")

    args = parser.parse_args()

    date = args.date
    data_obj = SGP_DATA(date[:8],date[:8])
    data_obj.single_data_download()

    run_tropoe(date,VIP_obj,vip_type=args.vipType,channel=args.channel,
               band=args.band,verbose=args.verbose)


