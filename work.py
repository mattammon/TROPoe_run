import glob
import sys,os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr

from utils import *
from config import *
from spectralBands import *
from profile_data import *


class Retrieval_Evaluation:

    def __init__(self,bands,max_hgt=5):
        self.bands = bands
        obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/*sonde*'))
        obs_dts = [f'{file[-19:-11]}{file[-10:-6]}' for file in obs_snd_files]



        # hgt_obs, T_obs, Td_obs, P_obs = self.obs_profiles(date, time, profile_max_hgt)
        # hgt_ch1, T_ch1, Td_ch1, P_ch1 = tropoe_sonde(1,date,time,profile_max_hgt)

        # T_obs_interp = np.interp(hgt_ch1,hgt_obs,T_obs)
        # Td_obs_interp = np.interp(hgt_ch1,hgt_obs,Td_obs)

    def retrieval_files(self,obs_dt):
        try:
            Ch1_file = self.ch1_file(obs_dt)
            ret_dt = Ch1_file[-18:-3]
        except ValueError as error:
            print(error)
        try:
            Ch2_files = self.ch2_files(obs_dt)
        except ValueError as error:
            print(error)
        return Ch1_file, Ch2_files

        #print(Ch1_file)
        #print(*Ch2_files, sep='\n')



    def ch1_file(self,dt):
        files = sorted(glob.glob(f'{RETRIEVAL_DIR}/*Ch1.{dt[:8]}*'))
        if len(files)>1:
            idx = np.argmin([abs(int(i[-9:-7]) - int(dt[8:10])) for i in files])
            file = files[idx]
        elif len(files)==1:
            file = files[0]
        else:
            raise ValueError("No Channel-1 Retrieval Exists Yet.")
        return file

    def ch2_files(self,dt):
        bands = self.bands
        files = sorted(glob.glob(f'{RETRIEVAL_DIR}/*Ch2*.{dt}*'))
        bands_done = np.unique([s[(s.rindex('B')+1):-19] for s in files])
        bands_not_done = [f'{b}' for b in bands if f'{b}' not in bands_done]
        if len(bands_not_done)>0:
            bnd = ", ".join(bands_not_done)
            raise ValueError(f"Retrievals for desired Ch-2 band(s) {bnd} have not been done!")
        files_bands = []
        for b in bands:
            files_bands.extend(file for file in files if f'B{b}.' in file)
        return files_bands

    def obs_profiles(self,file,max_hgt):
        ds = xr.open_dataset(file)
        hgt = ds.alt.data
        hgt = hgt - hgt[0]
        if ds.alt.units == 'm':
            hgt = hgt/1000
        T = ds.tdry.data
        Td = dew_point(T,ds.rh.data)
        P = ds.pres.data
        ds.close()
        if max_hgt is not None:
            max_hgt_idx = CVI(hgt,max_hgt) + 2
            hgt = hgt[:max_hgt_idx]
            T = T[:max_hgt_idx]
            Td = Td[:max_hgt_idx]
            P = P[:max_hgt_idx]
        return hgt, T, Td, P

    def tropoe_profiles(self,file,max_hgt):
        ds = xr.open_dataset(file)
        hgt = ds.height.data
        P = ds.pressure.data[0]
        T = ds.temperature.data[0]
        Td = ds.dewpt.data[0]
        if max_hgt is not None:
            max_hgt_idx = CVI(hgt,max_hgt) + 2
            hgt = hgt[:max_hgt_idx]
            T = T[:max_hgt_idx]
            Td = Td[:max_hgt_idx]
            P = P[:max_hgt_idx]
        # rh = ds.rh.data[tropoe_time_idx,:]
        # q = ds.waterVapor.data[tropoe_time_idx,:]
        # err_q = ds.sigma_waterVapor.data[tropoe_time_idx,:]
        # err_T = ds.sigma_temperature.data[tropoe_time_idx,:]
        ds.close()
        return hgt, T, Td, P


