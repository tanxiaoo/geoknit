# geoknit: component
# name: Split Points
# category: Sampling
# group: Split
# icon: gis:split
# description: Split points or table rows into random training and test parts.
# inputs:
#   data: {type: [Table, Vector]}
# outputs:
#   train: {like: data}
#   test: {like: data}
# requires: [scikit-learn, geopandas]

# --- settings ---
test_fraction = 0.3  # range: 0..1
seed = 42
stratify_by = None  # a column name (e.g. cls), to keep its class shares in both parts

# --- code ---
# A Vector gives Vectors and a Table gives Tables. The table's attrs (such as
# feature_columns from Extract Values) are copied to both parts, so Random
# Forest's features="auto" still finds them.
import geopandas as gpd
from sklearn.model_selection import train_test_split

if not 0 < test_fraction < 1:
    raise ValueError("test_fraction must be between 0 and 1")
strata = None
if stratify_by:
    if stratify_by not in data.columns:
        raise ValueError(f'no column "{stratify_by}" to stratify by')
    strata = data[stratify_by]
train, test = train_test_split(
    data, test_size=test_fraction, random_state=int(seed), stratify=strata
)
train, test = train.reset_index(drop=True), test.reset_index(drop=True)
train.attrs = dict(data.attrs)
test.attrs = dict(data.attrs)
unit = "points" if isinstance(data, gpd.GeoDataFrame) else "rows"
print(f"{len(train)} training {unit}, {len(test)} test {unit}")
