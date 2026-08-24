import xarray as xr
import numpy as np
import glob

from config import *
from utils import *

def obs_sonde(date,time,max_hgt):
    file = sorted(glob.glob(f'{SONDE_DIR}/{GROUP_NAME}/*{date}.{time}*'))[0]
    snd_ds = xr.open_dataset(file)
    hgt = snd_ds.alt.data
    hgt = hgt - hgt[0]
    if snd_ds.alt.units == 'm':
        hgt = hgt/1000
    max_hgt_idx = CVI(hgt,max_hgt) + 2
    hgt = hgt[:max_hgt_idx]
    T = snd_ds.tdry.data
    rh = snd_ds.rh.data
    Td = dew_point(T,snd_ds.rh.data)
    P = snd_ds.pres.data
    q = rh_to_mixing_ratio(rh, T, P)
    snd_ds.close()
    return hgt, T[:max_hgt_idx], Td[:max_hgt_idx], q[:max_hgt_idx], P[:max_hgt_idx]


def tropoe_sonde(date,time,max_hgt,channel=None,band=None):
    if channel == 1:
        files = sorted(glob.glob(f'{tropoe_dir}/*Ch1.{date}*'))
    else:
        files = sorted(glob.glob(f'{tropoe_dir}/*Ch2_B{band}.{date}*'))
    if len(files)>1:
        idx = np.argmin([abs(int(i[-9:-7]) - int(time[:2])) for i in files])
        file = files[idx]
    else:
        file = files[0]
    tropoe = xr.open_dataset(file)
    hgt = tropoe.height.data
    max_hgt_idx = CVI(hgt,max_hgt) + 2
    P = tropoe.pressure.data[0,:max_hgt_idx]
    T = tropoe.temperature.data[0,:max_hgt_idx]
    q = tropoe.waterVapor.data[0,:max_hgt_idx]
    Td = tropoe.dewpt.data[0,:max_hgt_idx]
    # rh = tropoe.rh.data[tropoe_time_idx,:]
    # err_q = tropoe.sigma_waterVapor.data[tropoe_time_idx,:]
    # err_T = tropoe.sigma_temperature.data[tropoe_time_idx,:]
    tropoe.close()
    return hgt[:max_hgt_idx], T, Td, q, P
