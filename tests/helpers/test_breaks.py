"""Breaks syntax for Reclassify (SPEC 7)."""

import numpy as np
import pytest

from geoknit.helpers import classify, parse_breaks

IMD_BREAKS = "0 | 0-20 | 20-40 | 40-60 | 60-80 | 80-100 | 100"


def test_parse_exact_and_ranges_in_rule_order() -> None:
    rules = parse_breaks(IMD_BREAKS)
    assert [r.cls for r in rules] == [1, 2, 3, 4, 5, 6, 7]
    assert [r.kind for r in rules] == ["exact"] + ["range"] * 5 + ["exact"]
    assert (rules[1].lo, rules[1].hi) == (0, 20)
    assert str(rules[6]) == "100"


def test_exact_rules_win_and_ranges_are_open_below() -> None:
    rules = parse_breaks(IMD_BREAKS)
    values = np.array([0, 0.1, 20, 20.5, 40, 99.9, 100, -1, 101, np.nan])
    assert classify(values, rules).tolist() == [1, 2, 2, 3, 3, 6, 7, 0, 0, 0]


def test_negative_numbers_decimals_and_spaces() -> None:
    rules = parse_breaks(" -5--1 |-1 - 0.5|  1e2 ")
    assert [(r.kind, r.lo, r.hi) for r in rules] == [
        ("range", -5, -1),
        ("range", -1, 0.5),
        ("exact", 100, 100),
    ]
    assert classify(np.array([-3, -1, 0, 100]), rules).tolist() == [1, 1, 2, 3]


def test_dtype_follows_the_number_of_classes() -> None:
    assert classify(np.array([1.0]), parse_breaks("0-1")).dtype == np.uint8
    assert classify(np.array([1.0]), parse_breaks("0-1"), dtype="int16").dtype == np.int16


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("0 | | 5", "rule 2 is empty"),
        ("0 | abc", 'rule 2 "abc"'),
        ("20-10", "first number must be smaller"),
        ("1-2-3", 'rule 1 "1-2-3"'),
    ],
)
def test_malformed_rules_are_named(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_breaks(text)
