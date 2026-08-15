import sys, os
import pandas as pd
from datetime import datetime
from config import *
from utils import *
import glob
from vip_gen import VIP
from TROPoe import run_tropoe

##########################################

obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/*sonde*'))
dates = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]
vip_type = 'default'

bands = [1,2,3,4,5,6,7,8,9,10,11,12]

##########################################

VIP_obj = VIP()

for d in dates:
    run_tropoe(d,VIP_obj,vip_type=vip_type,channel=1)
    for b in bands:
        run_tropoe(d,VIP_obj,vip_type=vip_type,channel=2,band=b)
    print(f'\nAll Retrievals for {d} Done!\n')
