# geoknit: component
# name: Predict Raster
# category: Model
# group: Apply
# icon: predict
# description: Apply a model to every pixel of a raster, window by window.
# inputs:
#   model: Model
#   raster: Raster
# outputs:
#   map: Raster
# requires: [numpy, dask]

# --- settings ---
window = 512  # range: 64..4096

# --- code ---
# The raster's band names must include the model's feature names. The result
# is lazy: it is computed one window at a time when it is written (the cache
# stores it as a COG).
import dask.array as da
import numpy as np
import xarray as xr

from geoknit.helpers import invalid_mask, nodata_value, raster_band_names

names = raster_band_names(raster)
missing = [f for f in model.feature_names if f not in names]
if missing:
    raise ValueError(
        f"the raster has no band {', '.join(missing)}, which the model needs "
        f"(the model uses {len(model.feature_names)} bands, the raster has {', '.join(names)})"
    )
order = [names.index(f) for f in model.feature_names]
nodata_in = nodata_value(raster)
estimator = model.estimator
size = int(window)

if model.task == "regression":
    out_dtype, fill = np.dtype("float32"), np.nan
    codes = None
else:
    classes = np.asarray(estimator.classes_)
    if np.issubdtype(classes.dtype, np.integer) or (
        np.issubdtype(classes.dtype, np.floating) and np.all(classes == np.round(classes))
    ):
        codes = None
        fill = 0 if 0 not in classes else int(classes.max()) + 1
        lo, hi = min(int(classes.min()), fill), max(int(classes.max()), fill)
        out_dtype = np.result_type(np.min_scalar_type(lo), np.min_scalar_type(hi))
    else:  # text classes: numbered 1…K in sorted order
        codes = {c: i for i, c in enumerate(classes, start=1)}
        fill = 0
        out_dtype = np.min_scalar_type(len(classes))
        print("class codes: " + ", ".join(f"{i} = {c}" for c, i in codes.items()))


def _predict(block):
    n_bands, h, w = block.shape
    pixels = block.reshape(n_bands, -1).T
    ok = ~invalid_mask(pixels, nodata_in).any(axis=1)
    out = np.full(h * w, fill, dtype=out_dtype)
    if ok.any():
        predicted = estimator.predict(pixels[ok])
        if codes is not None:
            predicted = np.array([codes[p] for p in predicted])
        out[ok] = predicted
    return out.reshape(1, h, w)


data = raster.isel(band=order).data
if not isinstance(data, da.Array):
    data = da.from_array(data)
data = data.rechunk({0: -1, 1: size, 2: size})
result = da.map_blocks(
    _predict, data, dtype=out_dtype, chunks=((1,), data.chunks[1], data.chunks[2])
)
map = xr.DataArray(
    result,
    dims=("band", "y", "x"),
    coords={"band": [1], "y": raster.y, "x": raster.x},
    attrs={"long_name": (model.target,)},
)
map = map.rio.write_crs(raster.rio.crs).rio.write_transform(raster.rio.transform())
map = map.rio.write_nodata(fill, encoded=False)
print(f"{model.task} map of {model.target}, {map.sizes['x']} × {map.sizes['y']} px, {out_dtype}")
