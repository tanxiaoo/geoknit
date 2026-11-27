"""List values (change 01 step 3, SPEC 3 "List values", 6 "Cache", 10).

Engine side: list outputs in the header, element checks, concatenation of
list and single wires, the list → item refusal (Panel takes a list whole),
the disk cache list format, ``describe()`` and the export.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import numpy as np
import pytest

from geoknit.core import types
from geoknit.core.cache import DiskCache
from geoknit.core.component import ComponentParseError, parse_component, run_component
from geoknit.core.executor import InProcessExecutor
from geoknit.core.export import export_script
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_SLIDER, Graph, GraphError
from geoknit.core.settings_edit import set_ports
from geoknit.core.workflow import graph_from_dict, graph_to_dict
from geoknit.runtime import protocol as p
from geoknit.runtime.worker import Worker


def _component(name: str, ports: str, code: str) -> str:
    return (
        f"# geoknit: component\n# name: {name}\n# category: Test\n{ports}\n# --- code ---\n{code}\n"
    )


NUMBERS = _component(
    "Numbers", "# outputs:\n#   values: {type: Number, access: list}\n", "values = (3, 1, 2)"
)
COLLECT = _component(
    "Collect",
    "# inputs:\n#   items: {type: Number, access: list}\n# outputs:\n#   got: Text\n",
    "got = repr(items)",
)
JOIN_TEXT = _component(
    "Join Text",
    "# inputs:\n#   items: {type: Text, access: list}\n# outputs:\n#   joined: Text\n",
    "joined = ','.join(items)",
)
SORT = _component(
    "Sort List",
    "# inputs:\n#   items: {type: Any, access: list}\n"
    "# outputs:\n#   sorted_items: {like: items, access: list}\n",
    "sorted_items = sorted(items)",
)
TAKES_NUMBER = _component(
    "Takes Number",
    "# inputs:\n#   x: Number\n# outputs:\n#   y: Number\n# --- settings ---\nx = 0\n",
    "y = x",
)


def _add(g: Graph, source: str) -> str:
    return g.add_component(INLINE, source=source).id


def _slider(g: Graph, value: float) -> str:
    nid = g.add_component(PARAM_SLIDER).id
    g.set_value(nid, value)
    return nid


# ── header ──


def test_list_outputs_parse_and_round_trip_through_set_ports() -> None:
    spec = parse_component(SORT)
    out = spec.outputs["sorted_items"]
    assert out.access == "list" and out.like == "items"
    assert parse_component(NUMBERS).outputs["values"].access == "list"

    ports = [
        {"name": "values", "type": "Number", "access": "list"},
        {"name": "same", "type": "Any", "like": "items", "access": "list"},
    ]
    new = set_ports(SORT, [{"name": "items", "type": "Any", "access": "list"}], ports)
    assert "#   values: {type: Number, access: list}" in new
    assert "#   same: {like: items, access: list}" in new
    spec = parse_component(new)
    assert spec.outputs["values"].access == "list" and spec.outputs["same"].like == "items"


def test_invalid_access_is_a_parse_error() -> None:
    with pytest.raises(ComponentParseError, match='invalid access "many"'):
        parse_component(NUMBERS.replace("access: list", "access: many"))


# ── running one component ──


def test_list_output_is_a_list_and_its_elements_are_checked() -> None:
    result = run_component(parse_component(NUMBERS), {})
    assert result.ok and result.outputs == {"values": [3, 1, 2]}  # the tuple became a list

    bad = run_component(parse_component(NUMBERS.replace("(3, 1, 2)", "[3, 'a']")), {})
    assert bad.error == 'output "values": item 1: expected Number, got Text'
    single = run_component(parse_component(NUMBERS.replace("(3, 1, 2)", "3")), {})
    assert single.error == 'output "values": expected a list of Number, got Number'
    flags = _component(
        "Flags", "# outputs:\n#   f: {type: Boolean, access: list}\n",
        "import numpy as np\nf = [np.float64(2) > 1]",
    )  # fmt: skip
    result = run_component(parse_component(flags), {})
    assert result.ok and type(result.outputs["f"][0]) is bool


PASS_ANY = _component(
    "Pass", "# inputs:\n#   data: Any\n# outputs:\n#   out: {like: data}\n", "out = data"
)


def test_like_output_of_an_any_item_input_fed_by_a_list_is_a_list(tmp_path: Path) -> None:
    """A ``like:`` output of an ``Any`` item input fed by a list carries that list:
    its value is checked as a list of the resolved type, not as one Number."""
    g = Graph()
    nums, through = _add(g, NUMBERS), _add(g, PASS_ANY)
    g.add_wire(nums, "values", through, "data")
    assert g.output_is_list(through, "out") and g.output_type(through, "out") == "Number"
    assert g.list_outputs(through) == {"out"}
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.output(through, "out") == [3, 1, 2]
    # the elements are still checked against the resolved type
    bad = _add(g, PASS_ANY.replace("out = data", "out = data + ['x']"))
    g.add_wire(nums, "values", bad, "data")
    ex.run()
    assert ex.errors[bad] == 'output "out": item 3: expected Number, got Text'

    # the worker gets the same from the server (``RunNode.list_outputs``)
    sent: list[object] = []
    w = Worker(sent.append, tmp_path, None)
    w.handle(p.RunNode("a", NUMBERS, {}, "k1"))
    w.handle(
        p.RunNode("b", PASS_ANY, {"data": "k1.values"}, "k2", {"out": "Number"}, frozenset(),
                  frozenset({"out"}))
    )  # fmt: skip
    assert not [m for m in sent if isinstance(m, p.Error)]
    assert w.memory["k2.out"] == [3, 1, 2]


def test_list_input_elements_are_checked() -> None:
    result = run_component(parse_component(COLLECT), {"items": [1, "x"]})
    assert result.error == 'input "items": item 1: expected Number, got Text'


# ── wiring ──


def test_list_and_single_wires_concatenate_in_wire_order() -> None:
    """Done when: ``[3, 1, 2]`` as ``list Number`` plus a single 7 gives ``[3, 1, 2, 7]``."""
    g = Graph()
    nums, seven, coll = _add(g, NUMBERS), _slider(g, 7), _add(g, COLLECT)
    g.add_wire(nums, "values", coll, "items")
    g.add_wire(seven, "value", coll, "items")
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.output(coll, "got") == "[3, 1, 2, 7]"

    # The worker decides by the port (``list_keys``), not by the value.
    sent: list[object] = []
    worker = Worker(sent.append)
    worker.handle(p.PutValue("seven.value", 7))
    worker.handle(p.PutValue("nums.values", [3, 1, 2]))
    worker.handle(p.PutValue("one.value", [5, 6]))  # a list value on a single port
    inputs = {"items": ["nums.values", "seven.value", "one.value", "nums.values"]}
    worker.handle(p.RunNode("c", COLLECT, inputs, "ck", list_keys=frozenset({"nums.values"})))
    assert isinstance(sent[-1], p.Error)  # [5, 6] is one element, and not a Number
    assert "item 4: expected Number, got list" in sent[-1].traceback
    worker.handle(p.PutValue("one.value", 5))
    worker.handle(p.RunNode("c", COLLECT, inputs, "ck2", list_keys=frozenset({"nums.values"})))
    assert isinstance(sent[-1], p.Done), sent[-1]
    assert worker.memory["ck2.got"] == "[3, 1, 2, 7, 5, 3, 1, 2]"


def test_number_list_into_text_list_converts_each_element() -> None:
    g = Graph()
    nums, join = _add(g, NUMBERS), _add(g, JOIN_TEXT)
    g.add_wire(nums, "values", join, "items")
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.output(join, "joined") == "3,1,2"


def test_list_output_into_an_item_input_is_refused() -> None:
    """Done when: refused with the spec message; a Panel takes the list whole."""
    g = Graph()
    nums, take = _add(g, NUMBERS), _add(g, TAKES_NUMBER)
    with pytest.raises(GraphError) as exc:
        g.add_wire(nums, "values", take, "x")
    assert str(exc.value) == 'Numbers gives a list; "x" takes one value — use List Item'

    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(nums, "values", panel, "data")
    assert g.output_is_list(panel, "data") and g.output_type(panel, "data") == "Number"
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.summaries[panel]["data"].splitlines()[0] == "list of 3 Number"

    # The Panel's pass-through is a list of Number: only list inputs take it.
    with pytest.raises(GraphError, match='Panel gives a list; "x" takes one value'):
        g.add_wire(panel, "data", take, "x")
    coll = _add(g, COLLECT)
    g.add_wire(panel, "data", coll, "items")
    g.add_wire(_slider(g, 7), "value", coll, "items")
    assert ex.run().ok, ex.errors
    assert ex.output(coll, "got") == "[3, 1, 2, 7]"


def test_rewiring_a_panel_with_a_list_removes_its_item_wires() -> None:
    g = Graph()
    seven, panel, take = _slider(g, 7), g.add_component(PARAM_PANEL).id, _add(g, TAKES_NUMBER)
    g.add_wire(seven, "value", panel, "data")
    g.add_wire(panel, "data", take, "x")
    g.remove_wire(seven, "value", panel, "data")
    g.add_wire(_add(g, NUMBERS), "values", panel, "data")
    assert g.wires_into(take, "x") == []


def test_like_list_output_follows_its_input_and_loads_back() -> None:
    g = Graph()
    nums, sort, coll = _add(g, NUMBERS), _add(g, SORT), _add(g, COLLECT)
    g.add_wire(nums, "values", sort, "items")
    assert g.output_type(sort, "sorted_items") == "Number"
    assert g.output_is_list(sort, "sorted_items")
    g.add_wire(sort, "sorted_items", coll, "items")
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert ex.output(coll, "got") == "[1, 2, 3]"
    again = graph_from_dict(graph_to_dict(g))
    assert len(again.wires) == 2


# ── describe() ──


def test_describe_names_the_element_type_and_shows_50() -> None:
    text = types.describe(list(range(60)))
    lines = text.splitlines()
    assert lines[0] == "list of 60 Number"
    assert lines[1] == "[0] 0" and lines[50] == "[49] 49"
    assert lines[51] == "… 10 more" and len(lines) == 52
    assert types.describe([1, "a"]).splitlines()[0] == "list of 2"
    assert types.describe([]) == "list of 0"
    assert types.describe(["two\nlines"]) == "list of 1 Text\n[0] two"


# ── disk cache ──


def _raster(names: tuple[str, ...], offset: float) -> object:
    import rioxarray  # noqa: F401
    import xarray as xr

    data = np.arange(len(names) * 4 * 5, dtype="float32").reshape(len(names), 4, 5) + offset
    da = xr.DataArray(
        data,
        dims=("band", "y", "x"),
        coords={"band": list(range(1, len(names) + 1)), "y": 5000000 - np.arange(4) * 10.0,
                "x": 500000 + np.arange(5) * 10.0},
    )  # fmt: skip
    da = da.rio.write_crs("EPSG:32632")
    da.attrs["long_name"] = names
    return da


def test_simple_lists_are_one_json_file(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    viridis = types.Colormap.named("viridis")
    outputs = {"n": [3, 1, 2], "c": [types.Color("#0B7A7C")], "m": [viridis], "e": []}
    cache.write("k" * 64, outputs, {})
    back, _ = DiskCache(tmp_path / "cache").read("k" * 64)
    assert back == outputs
    ports = cache.meta("k" * 64)["ports"]
    assert ports["n"] == {
        "type": "Number", "access": "list", "count": 3, "file": "n.json", "format": "json",
    }  # fmt: skip
    assert ports["e"]["type"] is None and ports["e"]["format"] == "json"


def test_numpy_scalars_are_cached_as_python_numbers(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path / "cache")
    outputs = {
        "ns": [np.int64(3), np.float32(1.5), 2],
        "n": np.int64(7),
        "f": np.float32(0.25),
        "b": np.bool_(True),
        "bs": [np.bool_(False)],
    }
    cache.write("k" * 64, outputs, {})
    back, _ = DiskCache(tmp_path / "cache").read("k" * 64)
    assert back == {"ns": [3, 1.5, 2], "n": 7, "f": 0.25, "b": True, "bs": [False]}
    assert [type(v) for v in back["ns"]] == [int, float, int]
    assert type(back["n"]) is int and type(back["b"]) is bool


def test_list_of_rasters_and_tables_is_a_folder_with_index(tmp_path: Path) -> None:
    import pandas as pd

    key = "r" * 64
    cache = DiskCache(tmp_path / "cache")
    rasters = [_raster(("red", "nir"), i) for i in range(3)]
    mixed = [pd.DataFrame({"a": [1]}), 4]
    cache.write(key, {"rasters": rasters, "mixed": mixed}, {})
    entry = tmp_path / "cache" / key
    index = json.loads((entry / "rasters" / "index.json").read_text(encoding="utf-8"))
    assert [i["file"] for i in index["items"]] == ["0.tif", "1.tif", "2.tif"]
    assert (entry / "mixed" / "0.parquet").is_file() and (entry / "mixed" / "1.json").is_file()
    assert cache.meta(key)["ports"]["mixed"]["type"] is None

    back, _ = DiskCache(tmp_path / "cache").read(key)
    assert [types.raster_band_names(r) for r in back["rasters"]] == [["red", "nir"]] * 3
    assert float(back["rasters"][2].values[0, 0, 0]) == 2.0
    assert back["mixed"][0].equals(mixed[0]) and back["mixed"][1] == 4
    written = cache.written_rasters(key)
    assert list(written) == ["rasters"] and len(written["rasters"]) == 3


# ── export ──


def test_export_builds_starred_lists_in_wire_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = Graph()
    nums, seven, coll = _add(g, NUMBERS), _slider(g, 7), _add(g, COLLECT)
    g.add_wire(nums, "values", coll, "items")
    g.add_wire(seven, "value", coll, "items")
    g.add_wire(nums, "values", (join := _add(g, JOIN_TEXT)), "items")
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(coll, "got", panel, "data")
    panel2 = g.add_component(PARAM_PANEL).id
    g.add_wire(join, "joined", panel2, "data")
    lists = g.add_component(PARAM_PANEL).id
    g.add_wire(nums, "values", lists, "data")

    script = export_script(g).script
    assert "items=[*n01_values, N02_ITEMS]" in script
    assert "items=[*[str(_v) for _v in n01_values]]" in script
    assert "    return list(values)\n" in script
    path = tmp_path / "exported.py"
    path.write_text(script, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    shown = runpy.run_path(str(path))["main"]()
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert shown == {panel: "[3, 1, 2, 7]", panel2: "3,1,2", lists: [3, 1, 2]}
    assert shown[lists] == ex.output(lists, "data")


FLAGS = _component(
    "Flags",
    "# outputs:\n#   one: Boolean\n#   many: {type: Boolean, access: list}\n",
    "import numpy as np\none = np.float64(2) > 1\nmany = (np.float64(0) > 1, np.float64(3) > 1)",
)


def test_export_turns_numpy_booleans_into_bool_as_geoknit_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = Graph()
    flags = _add(g, FLAGS)
    one, many = g.add_component(PARAM_PANEL).id, g.add_component(PARAM_PANEL).id
    g.add_wire(flags, "one", one, "data")
    g.add_wire(flags, "many", many, "data")
    script = export_script(g).script
    assert "    return bool(one), [bool(_v) for _v in many]\n" in script
    path = tmp_path / "exported.py"
    path.write_text(script, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    shown = runpy.run_path(str(path))["main"]()
    ex = InProcessExecutor(g)
    assert ex.run().ok, ex.errors
    assert shown == {one: True, many: [False, True]}
    assert type(shown[one]) is bool and [type(v) for v in shown[many]] == [bool, bool]
    assert shown[many] == ex.output(many, "data") and type(ex.output(one, "data")) is bool
