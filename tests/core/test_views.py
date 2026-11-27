"""Panel views (change 01, section 11): shapes and JSON-safe values."""

import datetime as dt
import decimal
import json

import numpy as np
import pandas as pd
from shapely.geometry import Point

from geoknit.core import views
from geoknit.core.executor import InProcessExecutor
from geoknit.core.graph import INLINE, PARAM_COLOR, PARAM_PANEL, PARAM_TOGGLE, Graph
from geoknit.core.types import Color, Colormap


def test_simple_values() -> None:
    assert views.view(3) == {"kind": "value", "type": "Number", "value": 3}
    assert views.view(np.float32(0.5)) == {"kind": "value", "type": "Number", "value": 0.5}
    assert views.view(float("nan"))["value"] == "nan"
    assert views.view(float("-inf"))["value"] == "-inf"
    assert views.view(np.bool_(True)) == {"kind": "value", "type": "Boolean", "value": True}
    assert views.view("hi") == {"kind": "value", "type": "Text", "value": "hi"}
    assert views.view(Color("#0b7a7c")) == {"kind": "color", "type": "Color", "value": "#0B7A7C"}
    cmap = views.view(Colormap.named("magma"))
    assert cmap["kind"] == "colormap" and cmap["value"]["name"] == "magma"
    assert views.view(None) == {"kind": "summary", "type": None, "text": "NoneType: None"}


def test_list_shows_the_first_50_one_line_views() -> None:
    v = views.view([*range(60)])
    assert (v["kind"], v["type"], v["count"], len(v["items"])) == ("list", "Number", 60, 50)
    mixed = views.view([1, Color("#000000"), pd.DataFrame({"a": [1]})])
    assert mixed["type"] is None
    assert mixed["items"][1] == {"kind": "color", "type": "Color", "value": "#000000"}
    assert mixed["items"][2] == {
        "kind": "summary", "type": "Table", "text": "Table · 1 rows × 1 columns",
    }  # fmt: skip


def test_cells_are_json_safe() -> None:
    df = pd.DataFrame(
        {
            "i": np.array([1, 2], dtype="int64"),
            "f": [np.nan, np.inf],
            "b": [np.bool_(True), None],
            "t": [pd.Timestamp("2026-11-27 10:00", tz="UTC"), pd.NaT],
            "d": [dt.date(2026, 1, 2), decimal.Decimal("1.5")],
            "raw": [b"abc", None],
            "geom": [Point(1, 2), {"a": 1}],
            "na": pd.array([1, None], dtype="Int64"),
            "long": ["x" * 2000, "ok"],
        }
    )
    page = views.page_of(df, 0, 10)
    json.dumps(page, allow_nan=False)  # strictly valid JSON
    assert page["rows"][0][:8] == [
        1, None, True, "2026-11-27T10:00:00+00:00", "2026-01-02", "<3 bytes>", "Point", 1,
    ]  # fmt: skip
    assert page["rows"][1][:8] == [2, "inf", None, None, 1.5, None, "{'a': 1}", None]
    assert len(page["rows"][0][8]) == views.CELL_TEXT_MAX and page["rows"][0][8].endswith("…")
    assert page["index"] == [0, 1] and page["total_rows"] == 2 and page["geometry"] == []


def test_table_view_is_the_first_page() -> None:
    v = views.view(pd.DataFrame({"a": range(500)}))
    assert v["kind"] == "table" and v["total_rows"] == 500 and len(v["rows"]) == views.PAGE_ROWS


TABLE = """\
# geoknit: component
# name: T
# category: Test
# outputs:
#   t: Table

# --- code ---
import pandas as pd
t = pd.DataFrame({"a": [1, 2]})
"""


def test_in_process_executor_keeps_views_for_params_and_panels() -> None:
    g = Graph()
    toggle = g.add_component(PARAM_TOGGLE).id
    color = g.add_component(PARAM_COLOR).id
    table = g.add_component(INLINE, source=TABLE).id
    panel = g.add_component(PARAM_PANEL).id
    g.add_wire(table, "t", panel, "data")
    ex = InProcessExecutor(g)
    assert ex.run().ok
    assert ex.views[toggle] == {"value": {"kind": "value", "type": "Boolean", "value": False}}
    assert ex.views[color]["value"]["kind"] == "color"
    assert ex.views[panel]["data"] == ex.views[table]["t"]
    assert ex.views[panel]["data"]["rows"] == [[1], [2]]
