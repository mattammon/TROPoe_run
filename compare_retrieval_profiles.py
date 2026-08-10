

########### To Plot ###########

# profile_max_hgt = 5  #km
# date = '20250101'
# time = '1854'  #Omit minutes (only HH)

# Observed = True
# Ch1 = True
# Ch2_bands = [1,6,12]

###############################

# import os
# import numpy as np
# import pandas as pd
# from matplotlib import pyplot as plt
# from utils import *
# from config import *
# from profile_data import *
# from spectralBands import ch2_bands
# from write_stats import *


from work import Retrieval_Evaluation

Retrieval_Evaluation([1,10,11])








def MAIN(date,time,profile_max_hgt=5,Observed=True,Ch1=True,
         Ch2_bands = [1,2,3,4,5,6,7,8,9,12]):

    hgt_obs, T_obs, Td_obs, P_obs = obs_sonde(date, time, profile_max_hgt)
    hgt_ch1, T_ch1, Td_ch1, P_ch1 = tropoe_sonde(1,date,time,profile_max_hgt)

    T_obs_interp = np.interp(hgt_ch1,hgt_obs,T_obs)
    Td_obs_interp = np.interp(hgt_ch1,hgt_obs,Td_obs)

    rmse_T = [(np.nanmean((T_ch1 - T_obs_interp)**2))**0.5]
    rmse_Td = [(np.nanmean((Td_ch1 - Td_obs_interp)**2))**0.5]

    fig = plt.figure(figsize=(10,6))

    ax = plt.subplot(121)
    ax2 = plt.subplot(122)

    ax.plot(T_obs_interp,hgt_ch1,c='k',ls='--',label='Obs',lw=3)
    ax2.plot(Td_obs_interp,hgt_ch1,c='k',ls='--',label='Obs',lw=3)

    ax.plot(T_ch1,hgt_ch1,c='k',label='Ch1',lw=2)
    ax2.plot(Td_ch1,hgt_ch1,c='k',label='Ch1',lw=2)

    T_mins = [min(T_obs),min(T_ch1)]
    T_maxs = [max(T_obs),max(T_ch1)]
    Td_mins = [min(Td_obs),min(Td_ch1)]
    Td_maxs = [max(Td_obs),max(Td_ch1)]

    for b in Ch2_bands:
        hgt, T, Td, P = tropoe_sonde(2,date,time,profile_max_hgt,band=b)
        rmse_T.append((np.nanmean((T - T_obs_interp)**2))**0.5)
        rmse_Td.append((np.nanmean((Td - Td_obs_interp)**2))**0.5)

        ax.plot(T,hgt,label=f'Ch2-B{b}',lw=2)
        line, = ax2.plot(Td,hgt,label=f'Ch2-B{b}',lw=2)
        T_mins.append(min(T))
        T_maxs.append(max(T))
        Td_mins.append(min(Td))
        Td_maxs.append(max(Td))
        #clr = line.get_color()

    ax.set_xlim(min(T_mins)-2,max(T_maxs)+2)
    ax2.set_xlim(min(Td_mins)-2,max(Td_maxs)+2)

    ax.set_ylim(0,profile_max_hgt)
    ax2.set_ylim(0,profile_max_hgt)

    ax.legend(loc='lower left', framealpha=1)
    ax2.legend(loc='lower left', framealpha=1)

    ax.grid(alpha=0.6)
    ax2.grid(alpha=0.6)

    ax.set_xlabel('Temperature (C)', fontsize = 15)
    ax2.set_xlabel('Dewpoint (C)', fontsize = 15)

    ax.set_ylabel('Height (km)', fontsize = 15)
    ax2.set_ylabel('Height (km)', fontsize = 15)

    ax.set_title(f'TROPoe Retrieved T Profiles:\n {date} ({time} UTC)', fontsize = 15)
    ax2.set_title(f'TROPoe Retrieved Td Profiles:\n {date} ({time} UTC)', fontsize = 15)

    ax.tick_params('both',labelsize=12)
    ax2.tick_params('both',labelsize=12)

    plt.savefig(f'{profile_fig_dir}/{date}_{time}.png',bbox_inches='tight')
    plt.close()

    return rmse_T, rmse_Td



    # new_RMSE_T = update_df(RMSE_T,rets,rmse_T,f'{date}_{time}')
    # new_RMSE_Td = update_df(RMSE_Td,rets,rmse_Td,f'{date}_{time}')

    # new_RMSE_T.to_csv(RMSE_T_file)
    # new_RMSE_Td.to_csv(RMSE_Td_file)


if __name__ == "__main__":
    Ch2_bands = [1,2,3,4,5,6,7,8,9,12]
    rets = ['Ch1']
    rets.extend([f'Ch2-band{i}' for i in Ch2_bands])

    c = pd.read_csv('../clear_sky_sgp_sounding_times.csv')
    RMSE_T, RMSE_Td = init_files()

    for i,d in enumerate(c['date'][:20]):
        try:
            rmse_T, rmse_Td = MAIN(d,c['time'][i],Ch2_bands=Ch2_bands)
            print(f'{d}_{c["time"][i]}')
            add = pd.DataFrame({ret: rmse for ret, rmse in zip(rets,rmse_T)},
                       index = [f'{d}_{c["time"][i]}'])
            RMSE_T.update(add)
            add = pd.DataFrame({ret: rmse for ret, rmse in zip(rets,rmse_Td)},
                       index = [f'{d}_{c["time"][i]}'])
            RMSE_Td.update(add)
        except:
            pass
