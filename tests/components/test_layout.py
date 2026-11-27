"""Ribbon layout: ``builtin/_layout.yaml``, tabs, groups and order (change 01, section 7)."""

import copy
from pathlib import Path

import pytest

from geoknit.components.layout import (
    OTHER,
    PACK_COLOUR,
    TABS,
    Layout,
    check_layout,
    library,
    load_layout,
)
from geoknit.components.registry import Registry, default_registry
from geoknit.core.component import ComponentParseError, parse_component
from geoknit.core.graph import PARAMS


def _component(name: str, category: str, group: str | None = None) -> str:
    group_line = f"# group: {group}\n" if group is not None else ""
    return (
        "# geoknit: component\n"
        f"# name: {name}\n"
        f"# category: {category}\n"
        f"{group_line}"
        "# inputs:\n"
        "#   raster: Raster\n"
        "# outputs:\n"
        "#   out: Raster\n"
        "# --- code ---\n"
        "out = raster\n"
    )


@pytest.fixture
def builtins(tmp_path: Path) -> Registry:
    return default_registry(tmp_path / "none", packs=False)


@pytest.fixture
def layout() -> Layout:
    return load_layout()


def _remove(layout: Layout, ref: str) -> Layout:
    out = copy.deepcopy(layout)
    for groups in out.values():
        for refs in groups.values():
            if ref in refs:
                refs.remove(ref)
    return out


def test_the_layout_lists_every_builtin_and_params_node_once(
    builtins: Registry, layout: Layout
) -> None:
    assert check_layout(layout, builtins) == []
    listed = [ref for groups in layout.values() for refs in groups.values() for ref in refs]
    builtin_refs = [r for r in builtins.refs() if builtins.item(r).origin == "builtin"]
    assert sorted(listed) == sorted(builtin_refs + list(PARAMS))


@pytest.mark.parametrize("ref", ["builtin/raster/reclassify", "param/slider"])
def test_removing_an_entry_fails_the_layout_test(
    builtins: Registry, layout: Layout, ref: str
) -> None:
    assert check_layout(_remove(layout, ref), builtins) == [f"{ref} is missing from the layout"]


def test_twice_unknown_out_of_order_and_disagreeing_headers(
    builtins: Registry, layout: Layout
) -> None:
    bad = copy.deepcopy(layout)
    bad["Raster"]["Files"].append("builtin/raster/clip")
    bad["Raster"]["Extent"].append("builtin/raster/no_such")
    bad["Vector"]["CRS"].append("builtin/model/svm")
    problems = check_layout(bad, builtins)
    assert "builtin/raster/clip is listed twice (Raster › Files and Raster › Extent)" in problems
    assert "builtin/raster/no_such is not a built-in component or Params node" in problems
    assert 'builtin/model/svm has "category: Model" but is in Vector › CRS' in problems
    assert 'builtin/model/svm has "group: Train" but is in Vector › CRS' in problems

    moved = {"Raster": layout["Raster"], **{k: v for k, v in layout.items() if k != "Raster"}}
    assert any(p.startswith("tabs out of order") for p in check_layout(moved, builtins))
    assert check_layout({**layout, "Plots": {}}, builtins)[0].startswith('unknown tab "Plots"')


def test_group_header(tmp_path: Path) -> None:
    assert parse_component(_component("A", "Raster", "Overlay")).group == "Overlay"
    assert parse_component(_component("A", "Raster")).group is None
    with pytest.raises(ComponentParseError, match="group must be a name"):
        parse_component(_component("A", "Raster", "[a, b]"))


def test_tabs_groups_and_order_of_the_builtins(builtins: Registry) -> None:
    lib = library(builtins.entries())
    tabs = {t["name"]: t for t in lib["tabs"]}
    assert list(tabs) == ["Params", "Vector", "Raster", "Sampling", "Model", "Validation", "Script"]
    assert tabs["Raster"] == {
        "name": "Raster",
        "colour": "#0B7A7C",
        "groups": ["Files", "Bands", "Calculate", "Extent"],
    }
    assert tabs["Sampling"]["colour"] == "#B45309"
    assert tabs["Params"]["groups"] == ["Input", "Inspect", "Map"]
    refs = [c["ref"] for c in lib["components"]]
    assert refs[:4] == ["param/text", "param/slider", "param/panel", "param/map"]
    raster = [c["ref"] for c in lib["components"] if c["category"] == "Raster"]
    assert raster == [
        "builtin/raster/read_raster",
        "builtin/raster/write_raster",
        "builtin/raster/band_select",
        "builtin/raster/reclassify",
        "builtin/raster/clip",
        "builtin/raster/align_raster",
    ]
    panel = next(c for c in lib["components"] if c["ref"] == "param/panel")
    assert panel["category"] == "Params" and panel["group"] == "Inspect"
    assert panel["inputs"] == [{"name": "data", "type": "Any", "types": ["Any"], "access": "item"}]
    assert panel["outputs"][0]["like"] == "data"
    viewer = next(c for c in lib["components"] if c["ref"] == "param/map")
    assert viewer["inputs"][0]["access"] == "list" and viewer["outputs"] == []


def test_pack_groups_come_after_the_builtin_groups_other_last(builtins: Registry, tmp_path: Path):
    pack = tmp_path / "pack"
    for folder, name, category, group in [
        ("raster", "zebra", "Raster", "Zeta"),
        ("raster", "loose", "Raster", None),
        ("raster", "alpha", "Raster", "Alpha"),
        ("raster", "extra_file", "Raster", "Files"),
        ("zeta", "one", "Zeta", None),
        ("beta", "two", "Beta", "Tools"),
    ]:
        (pack / folder).mkdir(parents=True, exist_ok=True)
        (pack / folder / f"{name}.py").write_text(_component(name, category, group), "utf-8")
    builtins.add_folder(pack, "fake", "1.0", origin="pack")

    lib = library(builtins.entries())
    tabs = {t["name"]: t for t in lib["tabs"]}
    assert list(tabs)[-3:] == ["Script", "Beta", "Zeta"]
    assert tabs["Zeta"] == {"name": "Zeta", "colour": PACK_COLOUR, "groups": [OTHER]}
    assert tabs["Raster"]["groups"] == [
        "Files",
        "Bands",
        "Calculate",
        "Extent",
        "Alpha",
        "Zeta",
        OTHER,
    ]
    raster = [c["ref"] for c in lib["components"] if c["category"] == "Raster"]
    assert raster[:3] == [
        "builtin/raster/read_raster",
        "builtin/raster/write_raster",
        "fake/raster/extra_file",
    ]
    assert raster[-3:] == ["fake/raster/alpha", "fake/raster/zebra", "fake/raster/loose"]
    loose = next(c for c in lib["components"] if c["ref"] == "fake/raster/loose")
    assert loose["group"] == OTHER


def test_every_builtin_tab_has_a_colour() -> None:
    assert list(TABS) == [
        "Params", "Maths", "Sets", "Table", "Vector", "Raster",
        "Sampling", "Model", "Validation", "Display", "Script",
    ]  # fmt: skip
