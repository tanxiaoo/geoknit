# geoknit: component
# name: Confusion Matrix
# category: Validation
# group: Classification
# icon: lucide:grid-2x2-check
# description: Compare a class map with reference points (confusion matrix, accuracy, kappa, F1).
# inputs:
#   map: Raster
#   reference: Vector
#   field: Text
# outputs:
#   matrix: Table
#   metrics: Table
# requires: [numpy, pandas, scikit-learn]

# --- code ---
# Rows of the matrix are reference classes, columns are mapped classes. The
# metrics table lists overall accuracy and kappa first, then producer's
# accuracy, user's accuracy and F1 for each class. Points outside the map, on
# nodata, or without a reference class are dropped and counted.
import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, confusion_matrix

from geoknit.helpers import values_at_points

if field not in reference.columns:
    raise ValueError(f'the reference points have no field "{field}"')
sampled = values_at_points(map.isel(band=[0]), reference)
ref = reference[field].reset_index(drop=True)
keep = sampled.valid & ref.notna().to_numpy()
mapped = sampled.values[keep, 0]
ref = ref[keep]
if pd.api.types.is_numeric_dtype(ref):
    observed = ref.to_numpy(dtype="float64")
    predicted = mapped
    whole = np.all(observed == np.round(observed)) and np.all(predicted == np.round(predicted))
    if whole:
        observed, predicted = observed.astype("int64"), predicted.astype("int64")
else:  # text classes: compare as text
    observed = ref.astype(str).to_numpy()
    predicted = np.array([f"{v:g}" for v in mapped])
dropped = int(len(keep) - keep.sum())
if dropped:
    print(f"dropped {dropped} points (outside the map, on nodata, or without a class)")
if len(observed) == 0:
    raise ValueError("no reference point falls on a valid pixel of the map")

labels = sorted(set(observed.tolist()) | set(predicted.tolist()))
cm = confusion_matrix(observed, predicted, labels=labels)
matrix = pd.DataFrame(cm, index=[str(c) for c in labels], columns=[str(c) for c in labels])
matrix.index.name = "reference \\ map"
matrix = matrix.reset_index()

diag = np.diag(cm).astype("float64")
ref_totals, map_totals = cm.sum(axis=1), cm.sum(axis=0)
with np.errstate(divide="ignore", invalid="ignore"):
    producers = np.where(ref_totals > 0, diag / ref_totals, np.nan)
    users = np.where(map_totals > 0, diag / map_totals, np.nan)
    f1 = np.where(producers + users > 0, 2 * producers * users / (producers + users), np.nan)
rows = [
    ("overall accuracy", "", float(diag.sum() / cm.sum())),
    ("kappa", "", float(cohen_kappa_score(observed, predicted, labels=labels))),
]
for i, c in enumerate(labels):
    rows += [
        ("producer's accuracy", str(c), float(producers[i])),
        ("user's accuracy", str(c), float(users[i])),
        ("F1", str(c), float(f1[i])),
    ]
metrics = pd.DataFrame(rows, columns=["metric", "class", "value"])
print(f"overall accuracy {rows[0][2]:.3f}, kappa {rows[1][2]:.3f} on {len(observed)} points")
