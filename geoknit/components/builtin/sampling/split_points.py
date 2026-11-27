# geoknit: component
# name: Split Points
# category: Sampling
# group: Split
# icon: gis:split
# description: Split sample points into random training and test points (held out for validation).
# inputs:
#   points: Vector
# outputs:
#   train: Vector
#   test: Vector
# requires: [scikit-learn]

# --- settings ---
test_fraction = 0.3  # range: 0..1
seed = 42
stratify_by = None  # a column name (e.g. cls), to keep its class shares in both parts

# --- code ---
from sklearn.model_selection import train_test_split

if not 0 < test_fraction < 1:
    raise ValueError("test_fraction must be between 0 and 1")
strata = None
if stratify_by:
    if stratify_by not in points.columns:
        raise ValueError(f'no column "{stratify_by}" to stratify by')
    strata = points[stratify_by]
train, test = train_test_split(
    points, test_size=test_fraction, random_state=int(seed), stratify=strata
)
train, test = train.reset_index(drop=True), test.reset_index(drop=True)
print(f"{len(train)} training points, {len(test)} test points")
