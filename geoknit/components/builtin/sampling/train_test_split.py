# geoknit: component
# name: Train/Test Split
# category: Sampling
# group: Split
# icon: split
# description: Split a table into random training and test rows.
# inputs:
#   table: Table
# outputs:
#   train: Table
#   test: Table
# requires: [scikit-learn]

# --- settings ---
test_fraction = 0.3  # range: 0..1
seed = 42
stratify_by = None  # a column name, to keep its class shares in both parts

# --- code ---
from sklearn.model_selection import train_test_split

if not 0 < test_fraction < 1:
    raise ValueError("test_fraction must be between 0 and 1")
strata = None
if stratify_by:
    if stratify_by not in table.columns:
        raise ValueError(f'no column "{stratify_by}" to stratify by')
    strata = table[stratify_by]
train, test = train_test_split(
    table, test_size=test_fraction, random_state=int(seed), stratify=strata
)
train, test = train.reset_index(drop=True), test.reset_index(drop=True)
train.attrs = dict(table.attrs)
test.attrs = dict(table.attrs)
print(f"{len(train)} train rows, {len(test)} test rows")
