# geoknit: component
# name: Reclassify
# category: Raster
# group: Calculate
# icon: reclassify
# description: Turn a continuous raster into classes using break rules such as 0 | 0-20 | 20-40.
# inputs:
#   raster: Raster
#   breaks: Text
# outputs:
#   classes: Raster
# requires: [numpy]

# --- settings ---
no_match = "nodata"  # options: nodata | keep
dtype = "uint8"  # options: uint8 | int16

# --- code ---
# Rules: a single number is an exact match; a-b means a < x <= b. Exact rules
# are checked first. Classes are 1…N in rule order; 0 means no rule matched
# (and is also used for nodata pixels). no_match = "nodata" marks 0 as nodata.
import numpy as np
import xarray as xr

from geoknit.helpers import classify, invalid_mask, nodata_value, parse_breaks

rules = parse_breaks(breaks)
if len(rules) > np.iinfo(dtype).max:
    raise ValueError(f"{len(rules)} classes do not fit in {dtype}")
nodata_in = nodata_value(raster)


def _classify(block):
    out = classify(block, rules, dtype=dtype)
    out[invalid_mask(block, nodata_in)] = 0
    return out


classes = xr.apply_ufunc(_classify, raster, dask="parallelized", output_dtypes=[np.dtype(dtype)])
classes.attrs = {"long_name": ("classes",) * int(raster.sizes.get("band", 1))}
classes = classes.rio.write_nodata(0 if no_match == "nodata" else None, encoded=False)
print(f"{len(rules)} classes: " + " | ".join(f"{r.cls}: {r}" for r in rules))
