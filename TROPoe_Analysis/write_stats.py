import pandas as pd
import os

from spectral_bands import ch2_bands
from config import *

RMSE_T_file = f'{retrieval_stats_dir}/T_RMSE.csv'
RMSE_Td_file = f'{retrieval_stats_dir}/Td_RMSE.csv'


def init_files():
    if not os.path.isfile(RMSE_T_file):
        create_csv(RMSE_T_file)
    if not os.path.isfile(RMSE_Td_file):
        create_csv(RMSE_Td_file)
    RMSE_T = pd.read_csv(RMSE_T_file)
    RMSE_Td = pd.read_csv(RMSE_Td_file)
    return RMSE_T, RMSE_Td


def update_df(df,retrievals,stats,timestamp):
    add = pd.DataFrame({ret: rmse for ret, rmse in zip(retrievals,stats)},
                       index = [timestamp])
    df.update(add)
    return df

def create_csv(file):
    snd_dates = pd.read_csv(snd_dates_file)
    tmstmps = [f'{d}_{snd_dates["time"][i]}' for i,d in enumerate(snd_dates['date'][:20])]
    retrievals = ['Ch1']
    retrievals.extend([f'Ch2-{i}' for i in ch2_bands])
    df = pd.DataFrame(index=tmstmps, columns=retrievals)
    df.index.name = 'Timestamp'
    df.to_csv(file)



