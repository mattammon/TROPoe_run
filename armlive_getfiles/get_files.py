streams = {
    'ch1':'sgpaerich1C1.b1',
    'ch2':'sgpaerich2C1.b1',
    'eng':'sgpaeriengineerC1.b1',
    'sum':'sgpaerisummaryC1.b1',
    'asi':'sgpasiskycoverC1.b1',
    'sonde':'sgpsondewnpnC1.b1'
}

#########
sdate = '2025-01-01'
edate = '2025-01-01'

stream = 'sum'

datastream = streams[stream]
#########

root = '/data'
rundir = f'{root}/armlive_getfiles'
filedir = f'{root}/irs_{stream}/sgp/clear_sky_days'

username = 'ammo0000'
token = '1135d911aebbb142'

import os

login = f'-u {username}:{token}'
ds = f'-ds {datastream}'

os.system(f'python {rundir}/src/getFiles.py {login} {ds} -s {sdate} -e {edate} -o {filedir}')
