#################################

Evaluate_Ch1 = True
Ch2_bands_toEval = [1,2,6,11,12]

Plot_Ch1 = True
Ch2_bands_toPlot = [1,2,6,11,12]

Plot_Observed = True

max_height_eval = 5
max_height_plot = 5

#################################


import glob
import sys,os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr
from collections import defaultdict
import math

from utils import *
from config import *
from spectralBands import *
from profile_data import *


class Retrieval_Evaluation:

    def __init__(self,max_hgt = max_height_eval,
                 eval_bands = Ch2_bands_toEval,
                 plot_bands = Ch2_bands_toPlot):

        self.max_hgt = max_hgt
        self.obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/*sonde*'))
        self.obs_dts = [f'{file[-19:-11]}{file[-10:-6]}' for file in self.obs_snd_files]

        self.profile_data = {
            "observed_snd": defaultdict(dict),
            "retrieval_snd": defaultdict(dict),
            "rmse": defaultdict()
            }

        for i,d in enumerate(self.obs_snd_files):
            dt = self.obs_dts[i]
            obs_dict = self.obs_profiles(d)

            self.profile_data['observed_snd'][dt] = obs_dict

            try:
                retrieval_dict = self.ret_profiles_compile(dt,ch2Bands=eval_bands)
                self.profile_data['retrieval_snd'][dt] = retrieval_dict
                print(f'{dt} Retrievals Succeeded!')
            except:
                print(f'{dt} Retrievals Failed!')
                pass

        # for i, snd in enumerate(snd_files):
        #     ch1, ch2s = EVAL.retrieval_files(dts[i])
        #     hgt_obs, T_obs, Td_obs, P_obs = EVAL.obs_profiles(snd)
        #     hgt_ch1, T_ch1, Td_ch1, P_ch1 = EVAL.tropoe_profiles(ch1)

        #     T_obs_interp = np.interp(hgt_ch1,hgt_obs,T_obs)
        #     Td_obs_interp = np.interp(hgt_ch1,hgt_obs,Td_obs)

    def ret_profiles_compile(self,dt,ch2Bands=[None]):
        curr_ret_data = defaultdict(dict)
        ch1_f, ch2_fs = self.retrieval_files(dt,ch2Bands)
        curr_ret_data['ch1'] = self.tropoe_profiles(ch1_f)
        for f,b in enumerate(ch2Bands):
            curr_ret_data[f'ch2_B{b}'] = self.tropoe_profiles(ch2_fs[f])
        return curr_ret_data


    def retrieval_files(self,obs_dt,bands):
        try:
            Ch1_file = self.ch1_file(obs_dt)
            ret_dt = Ch1_file[-18:-3]
        except ValueError as error:
            print(error)
        try:
            Ch2_files = self.ch2_files(ret_dt,bands)
        except ValueError as error:
            print(error)
        return Ch1_file, Ch2_files


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

    def ch2_files(self,dt,bands):
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

    def obs_profiles(self,file):
        max_hgt=self.max_hgt
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
        return {'hgt':hgt, 'T':T, 'Td':Td, 'P':P}

    def tropoe_profiles(self,file):
        max_hgt=self.max_hgt
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
        return {'hgt':hgt, 'T':T, 'Td':Td, 'P':P}


if __name__ == "__main__":
    EVAL = Retrieval_Evaluation()
    profile_data_dict = EVAL.profile_data
    print(profile_data_dict)


