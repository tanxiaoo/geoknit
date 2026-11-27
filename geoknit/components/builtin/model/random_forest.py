# geoknit: component
# name: Random Forest
# category: Model
# group: Train
# icon: lucide:trees
# description: Train a random forest (regression or classification) on a table.
# inputs:
#   table: Table
#   target: Text
#   n_trees: Number
#   max_depth: Number
#   min_leaf: Number
#   seed: Number
# outputs:
#   model: Model
# requires: [scikit-learn]

# --- settings ---
n_trees = 300  # range: 1..5000
max_depth = None  # None or 0 = grow until leaves are pure
min_leaf = 1  # range: 1..1000
seed = 42
task = "regression"  # options: regression | classification
max_features = "sqrt"  # options: sqrt | log2 | 1.0
features = "auto"  # "auto" (the band columns), or column names such as A00,A01

# --- code ---
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from geoknit.core.types import ModelBundle
from geoknit.helpers.model import choose_features, training_data

feature_names = choose_features(table, target, features)
X, y = training_data(table, target, feature_names)
Forest = RandomForestRegressor if task == "regression" else RandomForestClassifier
params = {
    "n_estimators": int(n_trees),
    "max_depth": int(max_depth) if max_depth else None,
    "min_samples_leaf": int(min_leaf),
    "max_features": max_features,
    "random_state": int(seed),
    "oob_score": len(y) >= 10,
    "n_jobs": -1,
}
estimator = Forest(**params).fit(X, y)
# Predict on one thread: summing trees in parallel changes the last bits of
# the result from run to run. Predict Raster runs windows in parallel instead.
estimator.set_params(n_jobs=1)
info = {"n_samples": int(len(y)), "parameters": params}
if params["oob_score"]:
    info["oob_score"] = float(estimator.oob_score_)
    print(f"out-of-bag {'R²' if task == 'regression' else 'accuracy'}: {estimator.oob_score_:.3f}")
model = ModelBundle(
    estimator=estimator, task=task, target=target, feature_names=feature_names, info=info
)
print(f"trained on {len(y)} rows × {len(feature_names)} features")
