import sys, os
import pandas as pd
from datetime import datetime
from config import *
from utils import *
import glob
from vip_gen import VIP
from SINGLE_TROPoe import run_tropoe
from get_sgp_data import SGP_DATA

##########################################

obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/{GROUP_NAME}/*sonde*'))[:40]
dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]

bands = [1,8,9]

##########################################

VIP_obj = VIP(in_group=True)

for d in dates:
    run_tropoe(d,VIP_obj,channel=1)
    for b in bands:
        run_tropoe(d,VIP_obj,channel=2,band=b)
    print(f'\nAll Retrievals for {d} Done!\n')
