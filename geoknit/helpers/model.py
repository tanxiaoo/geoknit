"""Training helpers shared by Random Forest and SVM."""

from __future__ import annotations

import warnings
from typing import Any


def choose_features(table: Any, target: str, features: str | list[str] = "auto") -> list[str]:
    """Feature columns for training.

    ``"auto"``: ``table.attrs["feature_columns"]`` (set by Extract Values), else
    every numeric column except the target. Otherwise a comma-separated list
    or a list of column names.
    """
    import pandas as pd

    if target not in table.columns:
        columns = ", ".join(map(str, table.columns))
        raise ValueError(f'the table has no target column "{target}" (columns: {columns})')
    if isinstance(features, str) and features.strip().lower() == "auto":
        chosen = list(table.attrs.get("feature_columns") or [])
        if not chosen:
            chosen = [
                str(c)
                for c in table.columns
                if c != target and pd.api.types.is_numeric_dtype(table[c])
            ]
    else:
        items = features.split(",") if isinstance(features, str) else list(features)
        chosen = [str(f).strip() for f in items if str(f).strip()]
    chosen = [c for c in chosen if c != target]
    missing = [c for c in chosen if c not in table.columns]
    if missing:
        raise ValueError(f"the table has no feature column {', '.join(missing)}")
    if not chosen:
        raise ValueError("no feature columns to train on")
    return chosen


def training_data(table: Any, target: str, features: list[str]) -> tuple[Any, Any]:
    """``(X, y)`` without rows that have a missing value (with a warning)."""
    data = table[[*features, target]]
    complete = data.notna().all(axis=1)
    if not complete.all():
        warnings.warn(f"dropped {int((~complete).sum())} rows with missing values", stacklevel=2)
    data = data[complete]
    if len(data) == 0:
        raise ValueError("no complete rows to train on")
    return data[features].to_numpy(), data[target].to_numpy()
