#################################
"""
Edit these parameters if running as standalone script:
"""
Ch2_bands_compile = [1,2,6,11,12]
max_height = 5 #km

#################################


import glob
import sys,os
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import xarray as xr
from collections import defaultdict
import math
from matplotlib.colors import TwoSlopeNorm
from mpl_toolkits.axes_grid1 import make_axes_locatable

from utils import *
from config import *
from spectralBands import *


class Aggregate_Retrievals:

    def __init__(self,max_hgt,eval_bands,plot_bands):

        self.max_hgt = max_hgt
        all_obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/{GROUP_NAME}/*sonde*'))

        obs_dts = []
        obs_snd_files = []
        for file in all_obs_snd_files:
            dt = f'{file[-19:-11]}{file[-10:-6]}'
            if GROUP_NAME in bad_dts and dt not in bad_dts[GROUP_NAME]:
                obs_dts.append(dt)
                obs_snd_files.append(file)
            elif GROUP_NAME not in bad_dts:
                obs_dts.append(dt)
                obs_snd_files.append(file)

        self.obs_dts = obs_dts
        self.obs_snd_files = obs_snd_files

        self.profile_data = {
            "observed_snd": defaultdict(dict),
            "retrieval_snd": defaultdict(dict),
            }

        self.good_dts = []

        for i,d in enumerate(self.obs_snd_files):
            dt = self.obs_dts[i]

            obs_dict = self.obs_profiles(d)

            try:
                retrieval_dict = self.ret_profiles_compile(dt,ch2Bands=eval_bands)
                self.profile_data['retrieval_snd'][dt] = retrieval_dict
                self.good_dts.append(dt)

                T_obs_interp = np.interp(retrieval_dict['Ch1']['hgt'],
                                         obs_dict['hgt'],
                                         obs_dict['T'])
                Td_obs_interp = np.interp(retrieval_dict['Ch1']['hgt'],
                                         obs_dict['hgt'],
                                         obs_dict['Td'])
                q_obs_interp = np.interp(retrieval_dict['Ch1']['hgt'],
                                         obs_dict['hgt'],
                                         obs_dict['q'])

                obs_dict['T'] = T_obs_interp
                obs_dict['Td'] = Td_obs_interp
                obs_dict['q'] = q_obs_interp

                self.profile_data['observed_snd'][dt] = obs_dict
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
        curr_ret_data['Ch1'] = self.tropoe_profiles(ch1_f)
        for f,b in enumerate(ch2Bands):
            curr_ret_data[f'Ch2_B{b}'] = self.tropoe_profiles(ch2_fs[f])
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
        files = sorted(glob.glob(f'{RETRIEVAL_DIR}/{GROUP_NAME}/*Ch1.{dt[:8]}*'))
        if len(files)>1:
            idx = np.argmin([abs(int(i[-9:-7]) - int(dt[8:10])) for i in files])
            file = files[idx]
        elif len(files)==1:
            file = files[0]
        else:
            raise ValueError("No Channel-1 Retrieval Exists Yet.")
        return file

    def ch2_files(self,dt,bands):
        files = sorted(glob.glob(f'{RETRIEVAL_DIR}/{GROUP_NAME}/*Ch2*.{dt}*'))
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
        rh = ds.rh.data
        Td = dew_point(T,rh)
        P = ds.pres.data
        q = rh_to_mixing_ratio(rh, T, P)
        ds.close()
        if max_hgt is not None:
            max_hgt_idx = CVI(hgt,max_hgt) + 2
            hgt = hgt[:max_hgt_idx]
            T = T[:max_hgt_idx]
            Td = Td[:max_hgt_idx]
            P = P[:max_hgt_idx]
            q = q[:max_hgt_idx]
        return {'hgt':hgt, 'T':T, 'Td':Td, 'q':q, 'P':P}

    def tropoe_profiles(self,file):
        max_hgt=self.max_hgt
        ds = xr.open_dataset(file)
        hgt = ds.height.data
        P = ds.pressure.data[0]
        T = ds.temperature.data[0]
        Td = ds.dewpt.data[0]
        q = ds.waterVapor.data[0]
        if max_hgt is not None:
            max_hgt_idx = CVI(hgt,max_hgt) + 2
            hgt = hgt[:max_hgt_idx]
            T = T[:max_hgt_idx]
            Td = Td[:max_hgt_idx]
            P = P[:max_hgt_idx]
            q = q[:max_hgt_idx]
        # rh = ds.rh.data[tropoe_time_idx,:]
        # q = ds.waterVapor.data[tropoe_time_idx,:]
        # err_q = ds.sigma_waterVapor.data[tropoe_time_idx,:]
        # err_T = ds.sigma_temperature.data[tropoe_time_idx,:]
        ds.close()
        return {'hgt':hgt, 'T':T, 'Td':Td, 'q':q, 'P':P}


if __name__ == "__main__":
    EVAL = Retrieval_Evaluation(max_height,Ch2_bands_compile)
    profile_data_dict = EVAL.profile_data

