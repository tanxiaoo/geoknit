"""Break rules for Reclassify (SPEC 7).

Rules are separated by ``|``. A single number is an exact match; ``a-b``
matches ``a < x <= b``. Exact rules are checked before ranges. Classes are
numbered 1…N in rule order; 0 means no rule matched.

>>> [r.cls for r in parse_breaks("0 | 0-20 | 20-40")]
[1, 2, 3]
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_EXACT = re.compile(rf"^({_NUMBER})$")
_RANGE = re.compile(rf"^({_NUMBER})\s*-\s*({_NUMBER})$")


@dataclass(frozen=True)
class Rule:
    """One break rule: ``exact`` (``lo == hi``) or ``range`` (``lo < x <= hi``)."""

    kind: str
    lo: float
    hi: float
    cls: int

    def __str__(self) -> str:
        return f"{self.lo:g}" if self.kind == "exact" else f"{self.lo:g}-{self.hi:g}"


def parse_breaks(text: str) -> list[Rule]:
    """Parse ``"0 | 0-20 | 20-40 | 100"``; raise ``ValueError`` naming a bad rule."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("breaks are empty; write rules such as 0 | 0-20 | 20-40")
    rules: list[Rule] = []
    for i, raw in enumerate(text.split("|"), start=1):
        part = raw.strip()
        if m := _EXACT.match(part):
            value = float(m.group(1))
            rules.append(Rule("exact", value, value, i))
        elif m := _RANGE.match(part):
            lo, hi = float(m.group(1)), float(m.group(2))
            if not lo < hi:
                raise ValueError(f'break rule {i} "{part}": the first number must be smaller')
            rules.append(Rule("range", lo, hi, i))
        else:
            raise ValueError(
                f'break rule {i} "{part}" is not a number or a range like 20-40'
                if part
                else f"break rule {i} is empty"
            )
    return rules


def class_dtype(n_classes: int) -> str:
    """The smallest unsigned integer type that holds classes 0…n."""
    return "uint8" if n_classes < 256 else "uint16" if n_classes < 65536 else "uint32"


def classify(values: Any, rules: list[Rule], dtype: str | None = None) -> Any:
    """Class numbers for ``values`` (a numpy array); NaN and unmatched values get 0."""
    import numpy as np

    v = np.asarray(values)
    out = np.zeros(v.shape, dtype=dtype or class_dtype(len(rules)))
    done = np.zeros(v.shape, dtype=bool)
    for rule in [r for r in rules if r.kind == "exact"] + [r for r in rules if r.kind == "range"]:
        if rule.kind == "exact":
            hit = v == rule.lo
        else:
            hit = (v > rule.lo) & (v <= rule.hi)
        hit &= ~done
        out[hit] = rule.cls
        done |= hit
    return out
