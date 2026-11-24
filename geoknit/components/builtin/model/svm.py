# geoknit: component
# name: SVM
# category: Model
# icon: svm
# description: Train a support vector machine (regression or classification) on a table.
# inputs:
#   table: Table
#   target: Text
# outputs:
#   model: Model
# requires: [scikit-learn]

# --- settings ---
task = "regression"  # options: regression | classification
kernel = "rbf"  # options: rbf | linear | poly | sigmoid
C = 1.0
gamma = "scale"  # options: scale | auto
standardize = True  # options: True | False
features = "auto"  # "auto" (the band columns), or column names such as A00,A01

# --- code ---
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC, SVR

from geoknit.core.types import ModelBundle
from geoknit.helpers.model import choose_features, training_data

feature_names = choose_features(table, target, features)
X, y = training_data(table, target, feature_names)
Machine = SVR if task == "regression" else SVC
params = {"kernel": kernel, "C": float(C), "gamma": gamma}
estimator = Machine(**params)
if standardize:
    estimator = make_pipeline(StandardScaler(), estimator)
estimator.fit(X, y)
model = ModelBundle(
    estimator=estimator,
    task=task,
    target=target,
    feature_names=feature_names,
    info={"n_samples": int(len(y)), "parameters": {**params, "standardize": standardize}},
)
print(f"trained on {len(y)} rows × {len(feature_names)} features")
