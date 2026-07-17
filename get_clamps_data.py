import glob
from siphon.catalog import TDSCatalog
import sys

date = sys.argv[1]
clamps = sys.argv[2][1]

def clamps_aeri_data(date=date,clamps=clamps,which={'ch1':True,'ch2':True,'summ':True}):
    data_base = f'/data'

    if which['ch1']:
        if len(sorted(glob.glob(f'{data_base}/irs_ch1/clamps/*C{clamps}*{date}*')))<1:
            base_url = 'https://data.nssl.noaa.gov/thredds/catalog/FRDD/CLAMPS/clamps'
            url = f'{base_url}/clamps{clamps}/ingested/clampsaerich1C{clamps}.b1'
            cat = TDSCatalog(f'{url}/catalog.html')
            cat_date = [i for i in cat.datasets if date in i]
            nc = cat.datasets.get(cat_date[0])
            nc.download(filename = f'{data_base}/irs_ch1/clamps/{cat_date[0]}')
    if which['ch2']:
        if len(sorted(glob.glob(f'{data_base}/irs_ch2/clamps/*C{clamps}*{date}*')))<1:
            base_url = 'https://data.nssl.noaa.gov/thredds/catalog/FRDD/CLAMPS/clamps'
            url = f'{base_url}/clamps{clamps}/ingested/clampsaerich2C{clamps}.b1'
            cat = TDSCatalog(f'{url}/catalog.html')
            cat_date = [i for i in cat.datasets if date in i]
            nc = cat.datasets.get(cat_date[0])
            nc.download(filename = f'{data_base}/irs_ch2/{cat_date[0]}')
    if which['summ']:
        if len(sorted(glob.glob(f'{data_base}/irs_sum/clamps/*C{clamps}*{date}*')))<1:
            base_url = 'https://data.nssl.noaa.gov/thredds/catalog/FRDD/CLAMPS/clamps'
            url = f'{base_url}/clamps{clamps}/ingested/clampsaerisummaryC{clamps}.b1'
            cat = TDSCatalog(f'{url}/catalog.html')
            cat_date = [i for i in cat.datasets if date in i]
            nc = cat.datasets.get(cat_date[0])
            nc.download(filename = f'{data_base}/irs_sum/clamps/{cat_date[0]}')


clamps_aeri_data()
