# Copyright 2018-2019 CRS4
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from netCDF4 import Dataset
import argparse
import datetime
import os
import subprocess
import sys

import numpy as np

from tdm.radar import utils


strptime = datetime.datetime.strptime
strftime = datetime.datetime.strftime


def run_gdaltransform(s_srs, t_srs, x, y):
    args = ["gdaltransform", "-s_srs", s_srs, "-t_srs", t_srs, "-output_xy"]
    out = subprocess.check_output(args, input=b"%f %f\n" % (x, y))
    lon, lat = [float(_) for _ in out.strip().split(b" ")]
    return lat, lon


def check_time_unit(t):
    fmt = "%Y-%m-%d %H:%M:%S"
    parts = t.getncattr("units").strip().split(" ", 2)
    assert len(parts) == 3
    assert parts[:2] == ["seconds", "since"]
    return strptime(parts[2], fmt)


def check_geo(dataset, footprint):
    ga = utils.GeoAdapter(footprint)
    xpos, ypos = dataset.variables["x"], dataset.variables["y"]
    xpos.set_auto_mask(False)
    ypos.set_auto_mask(False)
    assert (xpos.size, ypos.size) == (ga.cols, ga.rows)
    assert np.allclose(xpos[:], ga.xpos())
    assert np.allclose(ypos[:], ga.ypos())
    lat, lon = dataset.variables["lat"], dataset.variables["lon"]
    s_srs = "%s:%s" % (ga.sr.GetAttrValue("AUTHORITY", 0),
                       ga.sr.GetAttrValue("AUTHORITY", 1))
    t_srs = "EPSG:4326"
    rows = np.sort(np.random.choice(np.arange(ypos.size), 10, replace=False))
    cols = np.sort(np.random.choice(np.arange(xpos.size), 10, replace=False))
    for i in rows:
        for j in cols:
            y, x = ypos[i], xpos[j]
            exp_lat, exp_lon = run_gdaltransform(s_srs, t_srs, x, y)
            assert abs(lat[i, j] - exp_lat) < 1e-4
            assert abs(lon[i, j] - exp_lon) < 1e-4


def check_time(dataset, dts, resolution=None):
    if resolution:
        dt_path_pairs = [(_, None) for _ in dts]
        delta = datetime.timedelta(seconds=resolution)
        dts = [_ for (_, g) in utils.group_images(dt_path_pairs, delta)]
    t = dataset.variables["time"]
    t.set_auto_mask(False)
    assert t.size == len(dts)
    start = check_time_unit(t)
    for i, dt in enumerate(dts):
        assert dt == start + datetime.timedelta(seconds=t[i].item())


def check_rainfall_rate(dataset, dts, img_dir, resolution=None):
    rr = dataset.variables["rainfall_rate"]
    dt_rr_pairs = []
    for i, dt in enumerate(dts):
        name = "%s.png" % strftime(dt, "%Y-%m-%d_%H:%M:%S")
        signal = utils.get_image_data(os.path.join(img_dir, name))
        rainfall = utils.estimate_rainfall(signal)
        if resolution:
            dt_rr_pairs.append((dt, rainfall))
        else:
            assert np.ma.allclose(rr[i], rainfall, atol=1e-4)
    if not resolution:
        return
    delta = datetime.timedelta(seconds=resolution)
    chunks = [[ma for dt, ma in g]
              for _, g in utils.group_images(dt_rr_pairs, delta)]
    assert len(chunks) == len(rr)
    for i, c in enumerate(chunks):
        avg_rr = np.ma.mean(c, axis=0)
        assert np.ma.allclose(rr[i], avg_rr, atol=1e-4)


def check(nc_path, img_dir, footprint, resolution=None):
    dts, paths = zip(*utils.get_images(img_dir))
    ds = Dataset(nc_path, "r")
    check_geo(ds, footprint)
    check_time(ds, dts, resolution=resolution)
    check_rainfall_rate(ds, dts, img_dir, resolution=resolution)


def main(args):
    nc_paths = [os.path.join(args.nc_dir, _) for _ in os.listdir(args.nc_dir)]
    print("found %d files" % len(nc_paths))
    print("checking:")
    for p in nc_paths:
        print(" ", p)
        check(p, args.img_dir, args.footprint, resolution=args.resolution)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("nc_dir", metavar="NETCDF_DIR")
    parser.add_argument("img_dir", metavar="PNG_IMG_DIR")
    parser.add_argument("footprint", metavar="GEOTIFF_FOOTPRINT")
    parser.add_argument("-r", "--resolution", metavar="N_SECONDS", type=int,
                        help="set to same value passed to the rainfall script")
    main(parser.parse_args(sys.argv[1:]))
