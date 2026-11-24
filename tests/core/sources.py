"""Small component files used across the engine tests."""

REPEAT = """\
# geoknit: component
# name: Repeat
# category: Text
# description: Repeat a text several times.
# inputs:
#   text: Text
#   times: Number
# outputs:
#   repeated: Text

# --- settings ---
times = 2  # range: 1..10
sep = "-"  # options: - | _ | +

# --- code ---
repeated = sep.join([text] * int(times))
print(f"repeated {int(times)} times")
"""

LENGTH = """\
# geoknit: component
# name: Length
# category: Text
# inputs:
#   text: Text
# outputs:
#   n: Number

# --- code ---
n = len(text)
"""

TO_NUMBER = """\
# geoknit: component
# name: Half
# category: Math
# inputs:
#   x: Number
# outputs:
#   half: Number

# --- code ---
half = x / 2
"""

MAKE_RASTER = """\
# geoknit: component
# name: Fake Raster
# category: Raster
# outputs:
#   raster: Raster

# --- code ---
import numpy as np
import xarray as xr
raster = xr.DataArray(np.zeros((1, 2, 2)), dims=("band", "y", "x"))
"""

BOOM = """\
# geoknit: component
# name: Boom
# category: Script
# outputs:
#   y: Number

# --- code ---
def divide(a):
    return a / 0

y = divide(1)
"""
