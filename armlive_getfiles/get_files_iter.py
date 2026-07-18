import pandas as pd
import os
import sys
sys.path.append('/data/script_repo')
from config import *

streams = {
    'ch1':'sgpaerich1C1.b1',
    'ch2':'sgpaerich2C1.b1',
    'eng':'sgpaeriengineerC1.b1',
    'sum':'sgpaerisummaryC1.b1',
    'asi':'sgpasiskycoverC1.b1',
    'sonde':'sgpsondewnpnC1.b1'
}

##########################################

strms = ['ch1','ch2','eng','sum','sonde']
rundir = f'{SCRIPT_DIR}/armlive_getfiles'
cc_type_title = 'clear_sky'

df = pd.read_csv(f'{SCRIPT_DIR}/{cc_type_title}_sgp_sounding_times.csv')
dates = df['date']
tms = df['hr_dec']

username = 'ammo0000'
token = '1135d911aebbb142'

##########################################

login = f'-u {username}:{token}'

for s in strms:
    datastream = streams[s]
    ds = f'-ds {datastream}'

    if s == 'sonde':
        filedir = f'{DATA_DIR}/radiosonde/sgp/{cc_type_title}_days'
    else:
        filedir = f'{DATA_DIR}/irs_{s}/sgp/{cc_type_title}_days'
    for d in dates:
        d = str(d)
        sdate = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        edate = f'{d[:4]}-{d[4:6]}-{d[6:]}'
        os.system(f'python {rundir}/src/getFiles.py {login} {ds} -s {sdate} -e {edate} -o {filedir}')


