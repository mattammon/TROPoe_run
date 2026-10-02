import os
import subprocess
import sys
from config import *
from utils import *


def run_tropoe(dt_str,VIP_obj,channel=None,band=None,verbose='1'):

    VIP_obj.write_vip(irs_channel=channel,band=band)

    dt = rounded_retrieval_time(dt_str)
    date = dt.strftime('%Y%m%d')
    hr = f'{dt.hour + dt.minute / 60:.2f}'
    start_hr = hr
    end_hr = hr
    vip_file = VIP_obj.vip_file
    prior_file = 'prior.MIDLAT.nc'

    subprocess.run([sys.executable, 'TROPoe.py', date, vip_file,
                    f'{DATA_DIR}/{prior_file}', f'--shour={start_hr}',
                    f'--ehour={end_hr}', f'--verbose={verbose}'], check=True)

    print('####### DONE #######')
    try:
        os.remove(vip_file)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    import argparse
    from vip_gen import VIP
    from get_sgp_data import SGP_DATA

    parser = argparse.ArgumentParser()

    parser.add_argument("date", type=str, help="Datetime string in format yyyymmddHHMM")

    parser.add_argument("--channel", type=int, default=1, help="IRS Channel (1 or 2)")
    parser.add_argument("--band", type=int, default=None, help="Band number (ONLY for channel-2)")
    parser.add_argument("--verbose", type=str, default='1', help="Retrieval Verbosity")
    parser.add_argument("--group", action="store_true", help="Include Retrieval in GROUP_SUBDIR")

    args = parser.parse_args()

    if args.group:
        VIP_obj = VIP(in_group=True)
    else:
        VIP_obj = VIP()

    date = args.date
    data_obj = SGP_DATA(date[:8],date[:8])
    data_obj.single_data_download()

    run_tropoe(date,VIP_obj,channel=args.channel,band=args.band,verbose=args.verbose)
