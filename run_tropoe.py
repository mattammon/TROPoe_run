import sys, os

date = '20260509'
start_hr = '23.8'
end_hr = '24'
vip_file = 'vip_ch2.txt'
prior_file = 'prior.MIDLAT.nc'
verbose = '3'
data_root = '/data'

os.system(f'python TROPoe.py {date} {data_root}/{vip_file} {data_root}/{prior_file} --shour={start_hr} --ehour={end_hr} --verbose={verbose}')
