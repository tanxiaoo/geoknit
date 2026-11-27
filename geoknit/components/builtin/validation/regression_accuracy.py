# geoknit: component
# name: Regression Accuracy
# category: Validation
# group: Regression
# icon: lucide:target
# description: Compare a continuous map with reference points (n, RMSE, MAE, R², bias).
# inputs:
#   map: Raster
#   reference: Vector
#   field: Text
# outputs:
#   metrics: Table
# requires: [numpy, pandas]

# --- code ---
# Each point is compared with the pixel it falls in. Points outside the map,
# on nodata, or without a reference value are dropped and counted.
# bias = mean(observed − predicted).
import numpy as np
import pandas as pd

from geoknit.helpers import values_at_points

if field not in reference.columns:
    raise ValueError(f'the reference points have no field "{field}"')
sampled = values_at_points(map.isel(band=[0]), reference)
observed = pd.to_numeric(reference[field], errors="coerce").to_numpy(dtype="float64")
predicted = sampled.values[:, 0]
no_reference = np.isnan(observed) & sampled.valid
keep = sampled.valid & ~np.isnan(observed)
obs, pred = observed[keep], predicted[keep]
dropped = int(len(observed) - keep.sum())
if dropped:
    print(
        f"dropped {dropped} points: {int(sampled.outside.sum())} outside the map, "
        f"{int(sampled.nodata.sum())} on nodata, {int(no_reference.sum())} without a value"
    )
if len(obs) == 0:
    raise ValueError("no reference point falls on a valid pixel of the map")
err = obs - pred
ss_tot = float(np.sum((obs - obs.mean()) ** 2))
metrics = pd.DataFrame(
    {
        "n": [len(obs)],
        "dropped": [dropped],
        "RMSE": [float(np.sqrt(np.mean(err**2)))],
        "MAE": [float(np.mean(np.abs(err)))],
        "R²": [1 - float(np.sum(err**2)) / ss_tot if ss_tot > 0 else float("nan")],
        "bias": [float(np.mean(err))],
    }
)
print(metrics.to_string(index=False))
