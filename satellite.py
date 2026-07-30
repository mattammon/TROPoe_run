from config import *
from utils import *
install_and_import("boto3")
install_and_import("cartopy")

import argparse
import math
import sys, os
from datetime import datetime
import glob

import boto3
import cartopy
import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import netCDF4
import numpy as np
import requests
import xarray as xr
from botocore import UNSIGNED
from botocore.config import Config

import warnings
warnings.filterwarnings("ignore")

class GOES:
    def __init__(self, dt, band=2, goes=19):
        date = datetime.strptime(dt, "%Y%m%d")
        self.dt = dt
        self.doy = int(date.strftime("%j"))
        self.goes = goes
        self.date = date
        self.bucket = f"noaa-goes{goes}"
        self.band = band
        self.is_ir = False
        self.cmap = truncate_colormap("Greys_r", minval=0.1)
        self.site_loc=site_coordinates[SITE]
        self.area=[self.site_loc[0]-4, self.site_loc[0]+4,
                   self.site_loc[1]-3, self.site_loc[1]+3]

    def goes_projection(self, ds):
        goes_proj = ds.goes_imager_projection
        goes_h = int(goes_proj.perspective_point_height)
        r_eq = int(goes_proj.semi_major_axis)
        r_pol = int(goes_proj.semi_minor_axis)
        lon_0 = int(goes_proj.longitude_of_projection_origin)
        self.lon_origin = lon_0
        lon0 = np.radians(lon_0)
        return goes_h, r_eq, r_pol, lon0

    def calculate_solar_zenith(self, dt_utc, lat, lon):
        """Calculates solar zenith angle to determine if it is Day or Night."""
        day_of_year = dt_utc.timetuple().tm_yday

        # Fractional year in radians
        gamma = 2 * math.pi / 365 * (day_of_year - 1 + (dt_utc.hour - 12) / 24)

        # Equation of time (in minutes)
        eqtime = 229.18 * (
            0.000075
            + 0.001868 * math.cos(gamma)
            - 0.032077 * math.sin(gamma)
            - 0.014615 * math.cos(2 * gamma)
            - 0.040849 * math.sin(2 * gamma)
        )

        # Solar declination angle (in radians)
        decl = (
            0.006918
            - 0.399912 * math.cos(gamma)
            + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma)
            + 0.00148 * math.sin(3 * gamma)
        )

        # True solar time (in minutes)
        time_offset = eqtime + 4 * lon
        tst = dt_utc.hour * 60 + dt_utc.minute + dt_utc.second / 60 + time_offset

        # Solar hour angle (in degrees, then to radians)
        ha_rad = math.radians((tst / 4) - 180)
        lat_rad = math.radians(lat)

        # Solar zenith angle
        cos_zenith = math.sin(lat_rad) * math.sin(decl) + math.cos(lat_rad) * math.cos(
            decl
        ) * math.cos(ha_rad)

        # Clamp to avoid floating point domain errors
        cos_zenith = max(-1.0, min(1.0, cos_zenith))
        zenith = math.degrees(math.acos(cos_zenith))

        return zenith

    def rad_image(self, hr, mn):
        irs_loc = self.site_loc
        data = self.single_rad(hr, mn)
        print("Data successfully retrieved!")
        fig = plt.figure(figsize=(8, 5))
        ax, projection = self.base_map()

        # Use self.cmap which is dynamically set based on day/night
        print('Plotting Satellite Image')
        ax.pcolormesh(
            data.x.data, data.y.data, data, cmap=self.cmap, transform=projection
        )

        xloc, yloc = self.geodetic_to_geostat(irs_loc[0], irs_loc[1])
        ax.scatter(xloc * self.goes_h, yloc * self.goes_h, c="r", transform=projection)

        # Dynamically update the plot title and filename string
        band_str = "IR (Band 13)" if self.is_ir else "Visible (Band 2)"
        file_band_str = "IR" if self.is_ir else "VIS"

        ax.set_title(f"GOES-19 {band_str} Imagery: {self.timestamp}")
        img_name = f"GOES-{self.goes}_{file_band_str}_{self.timestamp}"
        img_loc = SAT_IMAGERY_DIR

        # Make the directory if it doesn't already exist
        os.makedirs(img_loc, exist_ok=True)

        plt.tight_layout()
        figname = f"{img_loc}/{img_name}.png"
        plt.savefig(figname)
        print(f'Image successfully saved to: {figname}')

    def single_rad(self, hr, mn):
        print(f"Fetching satellite imagery data for {hr}:{mn}Z on {self.dt}")
        area = self.area
        # 1. Determine whether we need Vis or IR based on Solar Zenith Angle
        dt_req = self.date.replace(hour=int(hr), minute=int(mn))
        center_lon = (area[0] + area[1]) / 2.0
        center_lat = (area[2] + area[3]) / 2.0

        sza = self.calculate_solar_zenith(dt_req, center_lat, center_lon)

        if sza > 85.0:
            print(
                f"Solar Zenith Angle: {sza:.1f}°. Too dark for visible imagery. Switching to IR (Band 13)."
            )
            self.band = 13
            self.is_ir = True
            # Greys_r works excellent for IR: lower radiances (colder clouds) will appear whiter
            self.cmap = plt.get_cmap("Greys")
        else:
            self.band = 2
            self.is_ir = False
            self.cmap = truncate_colormap("Greys_r", minval=0.1)

        # 2. Fetch the appropriate file
        keys = self.files(hr)
        idx = round((int(mn) / 60) * len(keys))
        key = keys[idx]
        ds = self.data(key)
        self.timestamp = ds.time_coverage_start

        # 3. Pass ds to subsection so dynamic NetCDF coords are used
        imin, imax, jmin, jmax = self.subsection(ds, area=area)

        sub = ds.isel(x=slice(imin, imax), y=slice(jmax, jmin))
        data = sub["Rad"].load()
        data["x"] = data["x"] * self.goes_h
        data["y"] = data["y"] * self.goes_h

        return data

    def base_map(self):
        proj = ccrs.Geostationary(
            central_longitude=self.lon_origin, satellite_height=self.goes_h
        )
        ax = plt.subplot(111, projection=proj)
        ax.add_feature(cartopy.feature.STATES, zorder=3, linewidth=2)
        return ax, proj

    def data(self, key):
        bucket_path = f"https://{self.bucket}.s3.amazonaws.com/{key}"
        resp = requests.get(bucket_path)
        file_name = key.split("/")[-1].split(".")[0]
        nc4_ds = netCDF4.Dataset(file_name, memory=resp.content)
        store = xr.backends.NetCDF4DataStore(nc4_ds)
        DS = xr.open_dataset(store)
        self.goes_h, self.r_eq, self.r_pol, self.lon_0 = self.goes_projection(DS)
        return DS

    def subsection(self, ds, area=[-101, -94.5, 33, 38]):
        # Extract x and y directly from the dataset to account for positional shifts
        x = ds.x.data
        y = ds.y.data

        xmin, ymin = self.geodetic_to_geostat(area[0], area[2])
        xmax, ymax = self.geodetic_to_geostat(area[1], area[3])

        imin = CVI(x, xmin)
        imax = CVI(x, xmax)
        jmin = CVI(y, ymin)
        jmax = CVI(y, ymax)
        return imin, imax, jmin, jmax

    def geodetic_to_geostat(self, lon, lat):
        lats = np.radians(lat)
        longs = np.radians(lon)

        H = 42164160
        e = 0.0818191910435
        r_pol = self.r_pol
        r_eq = self.r_eq
        lon_0 = self.lon_0
        lat_c = np.arctan(((r_pol**2) / (r_eq**2)) * np.tan(lats))
        rc = r_pol / np.sqrt(1 - (e**2) * (np.cos(lat_c) ** 2))
        sx = H - (((rc) * np.cos(lat_c)) * (np.cos(longs - lon_0)))
        sy = -((rc) * np.cos(lat_c)) * (np.sin(longs - lon_0))
        sz = (rc) * np.sin(lat_c)

        y = np.arctan(sz / sx)
        x = np.arcsin(-sy / np.sqrt((sx**2) + (sy**2) + (sz**2)))
        return x, y

    def files(self, hour, product="ABI-L1b-RadC"):
        yr = self.date.year
        prefix = f"{product}/{yr}/{self.doy:03.0f}/{int(hour):02.0f}"
        prefix = f"{prefix}/OR_{product}-M6C{self.band:02.0f}_G19"
        s3_keys = self.get_s3_keys(prefix)
        keys = [key for key in s3_keys]
        return keys

    def get_s3_keys(self, prefix):
        s3_client = boto3.client("s3", config=Config(signature_version=UNSIGNED))
        bucket = self.bucket
        kwargs = {"Bucket": bucket}
        if isinstance(prefix, str):
            kwargs["Prefix"] = prefix
        while True:
            resp = s3_client.list_objects_v2(**kwargs)
            for obj in resp["Contents"]:
                key = obj["Key"]
                if key.startswith(prefix):
                    yield key
            try:
                kwargs["ContinuationToken"] = resp["NextContinuationToken"]
            except KeyError:
                break

def group_plot():
    obs_snd_files = sorted(glob.glob(f'{SONDE_DIR}/*sonde*'))
    dates = [f'{file[-19:-11]}' for file in obs_snd_files]
    hrs = [f'{file[-10:-8]}' for file in obs_snd_files]
    mns = [f'{file[-8:-6]}' for file in obs_snd_files]

    for i, d in enumerate(dates):
        try:
            sat = GOES(d)
            sat.rad_image(hrs[i], mns[i])
        except:
            print(f'DATA UNAVAILABLE FOR {d} at {hrs[i]}:{mns[i]}!')
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1:
        parser = argparse.ArgumentParser()
        parser.add_argument("datestr", help="Date in format YYYYMMDD")
        parser.add_argument("h", help="Hour of desired time (UTC)")
        parser.add_argument("m", help="Minute of desired time (UTC)")
        args = parser.parse_args()
        sat = GOES(args.datestr)
        sat.rad_image(args.h, args.m)
    else:
        group_plot()

