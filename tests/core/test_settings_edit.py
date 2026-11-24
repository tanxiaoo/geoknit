"""Settings ↔ Code sync: in-place edits keep everything else (SPEC 4)."""

import difflib

import pytest

from geoknit.core.component import parse_component
from geoknit.core.settings_edit import format_literal, set_setting, set_settings

SOURCE = '''\
# geoknit: component
# name: Every Kind
# description: one setting of each kind
# inputs:
#   raster: Raster
# outputs:
#   y: Number

# --- settings ---
# a comment line that must survive
n_trees = 300        # range: 10..1000
ratio = 0.25         # range: 0..1
mode = "nodata"      # options: nodata | keep
quoted = 'single'
flag = True
nothing = None
negative = -3
bands = [1, 2, 3]    # bands to keep
pair = ("a", "b")
note = """first line
second line"""       # multiline
unicode = "città"; other = 1

# --- code ---
y = n_trees  # code must not change
'''

NEW_VALUES = {
    "n_trees": 500,
    "ratio": 0.5,
    "mode": "keep",
    "quoted": "it's",
    "flag": False,
    "nothing": "now text",
    "negative": 7,
    "bands": [4, 5],
    "pair": ("c",),
    "note": 'one\ntwo """ three',
    "unicode": "Milano – città",
    "other": 2.5,
}


def _changed_old_lines(old: str, new: str) -> set[int]:
    """1-based line numbers of ``old`` that differ in ``new``."""
    matcher = difflib.SequenceMatcher(a=old.splitlines(), b=new.splitlines(), autojunk=False)
    changed: set[int] = set()
    for tag, i1, i2, _, _ in matcher.get_opcodes():
        if tag != "equal":
            changed.update(range(i1 + 1, i2 + 1))
    return changed


@pytest.mark.parametrize(("name", "value"), list(NEW_VALUES.items()))
def test_each_kind_round_trips(name: str, value: object) -> None:
    before = parse_component(SOURCE)
    edited = set_setting(SOURCE, name, value)
    after = parse_component(edited)

    assert after.settings[name].value == value
    assert type(after.settings[name].value) is type(value)
    for other, setting in before.settings.items():
        if other != name:
            assert after.settings[other].value == setting.value
    assert after.settings["n_trees"].range == (10, 1000)
    assert after.settings["mode"].options == ("nodata", "keep")

    # Only the line(s) of the edited literal change; every comment survives.
    line = before.settings[name].line
    allowed = {line, line + 1} if name == "note" else {line}
    assert _changed_old_lines(SOURCE, edited) <= allowed
    for comment in ("# a comment line that must survive", "# bands to keep", "# multiline"):
        assert comment in edited
    assert edited.endswith("y = n_trees  # code must not change\n")


def test_comment_after_value_is_kept_byte_for_byte() -> None:
    assert "n_trees = 50        # range: 10..1000\n" in set_setting(SOURCE, "n_trees", 50)
    assert "quoted = 'x'\n" in set_setting(SOURCE, "quoted", "x")  # quote style kept
    assert 'unicode = "a"; other = 1\n' in set_setting(SOURCE, "unicode", "a")


def test_multiline_string_stays_triple_quoted() -> None:
    edited = set_setting(SOURCE, "note", "a\nb")
    assert 'note = """a\nb"""       # multiline\n' in edited


def test_several_settings_at_once_and_crlf() -> None:
    crlf = SOURCE.replace("\n", "\r\n")
    edited = set_settings(crlf, {"n_trees": 1, "bands": [], "other": 3})
    spec = parse_component(edited)
    assert (spec.settings["n_trees"].value, spec.settings["bands"].value) == (1, [])
    assert spec.settings["other"].value == 3
    assert edited.count("\r\n") == crlf.count("\r\n")


def test_unknown_setting_and_bad_value() -> None:
    with pytest.raises(KeyError):
        set_setting(SOURCE, "missing", 1)
    with pytest.raises(ValueError):
        set_setting(SOURCE, "n_trees", {"a": 1})
    with pytest.raises(ValueError):
        format_literal(float("nan"))
