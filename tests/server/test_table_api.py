"""Panel views and table pages (change 01, section 11; PLAN step 8, backend).

"Done when": ``/api/table/{key}?offset=200&limit=200`` on a 1000-row Table
gives rows 200–399 and ``total_rows: 1000``; a Vector page shows ``Point`` in
its geometry column; an unknown key answers 404.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from geoknit.core.cache import DiskCache
from geoknit.server import tables
from geoknit.server.session import Session
from tests.server.conftest import collect_until_finished, make_client

ROWS = """\
# geoknit: component
# name: Rows
# category: Test
# outputs:
#   table: Table

# --- code ---
import pandas as pd

table = pd.DataFrame({
    "id": range(1000),
    "half": [i / 2 for i in range(1000)],
    "name": [f"row {i}" for i in range(1000)],
})
table.loc[3, "half"] = float("nan")
table.loc[4, "half"] = float("inf")
table["when"] = pd.Timestamp("2026-01-02T03:04:05")
"""

POINTS = """\
# geoknit: component
# name: Points
# category: Test
# outputs:
#   points: Vector
#   parts: {type: Vector, access: list}
#   labelled: Table

# --- code ---
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

points = gpd.GeoDataFrame(
    {"v": [1, 2, 3]}, geometry=[Point(0, 0), Point(1, 1), None], crs="EPSG:4326"
)
line = gpd.GeoDataFrame({"v": [9]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326")
parts = [points, line]
# A string index and a mixed-type column: Parquet refuses it, the cache pickles it.
labelled = pd.DataFrame({"mixed": [1, "a", 2.5]}, index=["x", "y", "z"])
"""


def _session(client: TestClient) -> Session:
    return client.app.state.session  # type: ignore[attr-defined,no-any-return]


def _add(client: TestClient, component: str, **extra: object) -> str:
    r = client.post("/api/nodes", json={"component": component, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wire(client: TestClient, src: str, sp: str, dst: str, dp: str) -> None:
    r = client.post("/api/wires", json={"from": [src, sp], "to": [dst, dp]})
    assert r.status_code == 201, r.text


def _page(client: TestClient, key: str, **query: int) -> dict[str, Any]:
    r = client.get(f"/api/table/{key}", params=query)
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, dict[str, str]]]:
    """Rows, Points and Params nodes, each with a Panel, run once."""
    root = tmp_path_factory.mktemp("tables")
    (root / "project").mkdir()
    with make_client(root / "project", root / "home" / "trusted.json") as client:
        nodes = {"rows": _add(client, "inline", source=ROWS)}
        nodes["points"] = _add(client, "inline", source=POINTS)
        for name in ("number", "color", "colormap", "toggle"):
            nodes[name] = _add(client, f"param/{name}")
        client.patch(f"/api/nodes/{nodes['number']}", json={"value": 2.5})
        for name, src, port in (
            ("p_rows", "rows", "table"),
            ("p_parts", "points", "parts"),
            ("p_number", "number", "value"),
            ("p_color", "color", "value"),
            ("p_colormap", "colormap", "value"),
        ):
            nodes[name] = _add(client, "param/panel")
            _wire(client, nodes[src], port, nodes[name], "data")
        nodes["p_empty"] = _add(client, "param/panel")
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
            assert client.post("/api/run", json={}).status_code == 202
            events = collect_until_finished(ws)
        assert events[-1]["report"]["ok"], events[-1]
        nodes["_events"] = events  # type: ignore[assignment]
        yield client, nodes


def _output(client: TestClient, nid: str) -> dict[str, Any]:
    r = client.get(f"/api/nodes/{nid}/output")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


def test_table_view_and_second_page(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    out = _output(client, nodes["rows"])
    assert out["disk_cache"] is True
    view, key = out["views"]["table"], out["keys"]["table"]
    assert view["kind"] == "table" and view["type"] == "Table"
    assert view["columns"] == ["id", "half", "name", "when"]
    assert view["total_rows"] == 1000 and view["offset"] == 0 and view["geometry"] == []
    assert len(view["rows"]) == 200 and view["index"] == list(range(200))
    # JSON-safe cells: NaN → null, inf → "inf", timestamps as ISO text.
    assert view["rows"][3] == [3, None, "row 3", "2026-01-02T03:04:05"]
    assert view["rows"][4][1] == "inf"

    # The Done-when check: rows 200–399 of 1000.
    page = _page(client, key, offset=200, limit=200)
    assert page["total_rows"] == 1000 and page["offset"] == 200
    assert page["columns"] == view["columns"]
    assert [row[0] for row in page["rows"]] == list(range(200, 400))
    assert page["index"] == list(range(200, 400))
    assert page["rows"][0] == [200, 100.0, "row 200", "2026-01-02T03:04:05"]

    # The Panel shows the same view and names the same key.
    panel = _output(client, nodes["p_rows"])
    assert panel["views"]["data"] == view and panel["keys"]["data"] == key

    # The end of the table, an empty page past it, and limits.
    assert [r[0] for r in _page(client, key, offset=990, limit=1000)["rows"]] == list(
        range(990, 1000)
    )
    assert _page(client, key, offset=5000)["rows"] == []
    assert client.get(f"/api/table/{key}", params={"limit": 1001}).status_code == 400
    assert client.get(f"/api/table/{key}", params={"offset": -1}).status_code == 400


def test_pages_read_row_groups_only(
    run: tuple[TestClient, dict[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyarrow.parquet as pq

    client, nodes = run
    key = _output(client, nodes["rows"])["keys"]["table"]
    read: list[list[int]] = []
    original = pq.ParquetFile.read_row_groups

    def spy(self: Any, row_groups: list[int], *args: Any, **kwargs: Any) -> Any:
        read.append(list(row_groups))
        return original(self, row_groups, *args, **kwargs)

    monkeypatch.setattr(pq.ParquetFile, "read_row_groups", spy)
    monkeypatch.setattr("geoknit.core.cache.ROW_GROUP_ROWS", 100)  # for the write below
    page = _page(client, key, offset=200, limit=200)
    assert read == [[0]] and len(page["rows"]) == 200  # 1000 rows < one row group

    # A table written with small row groups: a page reads only the groups it needs.
    import pandas as pd

    cache = DiskCache(Path(str(_session(client).executor.cache_dir)))
    cache.write("f" * 64, {"t": pd.DataFrame({"i": range(1000)})})
    read.clear()
    page = tables.table_page(cache, "f" * 64 + ".t", 250, 200)
    assert read == [[2, 3, 4]]
    assert [r[0] for r in page["rows"]] == list(range(250, 450))


def test_vector_page_shows_geometry_type(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    out = _output(client, nodes["points"])
    view = out["views"]["points"]
    assert view["kind"] == "table" and view["type"] == "Vector"
    assert view["columns"] == ["v", "geometry"] and view["geometry"] == ["geometry"]
    assert view["rows"] == [[1, "Point"], [2, "Point"], [3, None]]

    page = _page(client, out["keys"]["points"], offset=1, limit=5)
    assert page["rows"] == [[2, "Point"], [3, None]]
    assert page["index"] == [1, 2] and page["total_rows"] == 3
    assert page["geometry"] == ["geometry"]

    # A list element is addressed as <key>[i].
    parts_key = out["keys"]["parts"]
    line = _page(client, f"{parts_key}[1]")
    assert line["rows"] == [[9, "LineString"]] and line["total_rows"] == 1
    assert client.get(f"/api/table/{parts_key}[2]").status_code == 404
    assert client.get(f"/api/table/{parts_key}").status_code == 404  # the list itself


def test_list_view_shows_element_lines(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    view = _output(client, nodes["p_parts"])["views"]["data"]
    assert view["kind"] == "list" and view["type"] == "Vector" and view["count"] == 2
    assert view["items"] == [
        {"kind": "summary", "type": "Vector", "text": "Vector · 3 features · Point"},
        {"kind": "summary", "type": "Vector", "text": "Vector · 1 features · LineString"},
    ]


def test_pickled_table_is_paged_and_memoised(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    out = _output(client, nodes["points"])
    key = out["keys"]["labelled"]
    _, info = DiskCache(Path(str(_session(client).executor.cache_dir))).port_info(key)
    assert info["format"] == "pickle"
    tables._pickled.cache_clear()
    page = _page(client, key, offset=1, limit=2)
    assert page["rows"] == [["a"], [2.5]] and page["index"] == ["y", "z"]
    _page(client, key)
    assert tables._pickled.cache_info().hits == 1


def test_params_and_panels_carry_views(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    number = {"kind": "value", "type": "Number", "value": 2.5}
    assert _output(client, nodes["number"])["views"] == {"value": number}
    assert _output(client, nodes["p_number"])["views"] == {"data": number}
    assert _output(client, nodes["toggle"])["views"]["value"] == {
        "kind": "value", "type": "Boolean", "value": False,
    }  # fmt: skip
    assert _output(client, nodes["p_color"])["views"]["data"] == {
        "kind": "color", "type": "Color", "value": "#0B7A7C",
    }  # fmt: skip
    cmap = _output(client, nodes["p_colormap"])["views"]["data"]
    assert cmap["kind"] == "colormap" and cmap["value"]["name"] == "viridis"
    empty = _output(client, nodes["p_empty"])["views"]["data"]
    assert empty["kind"] == "summary" and empty["type"] is None

    # The done events carry the same views.
    events: list[dict[str, Any]] = nodes["_events"]  # type: ignore[assignment]
    done = {e["node"]: e for e in events if e["type"] == "done"}
    assert done[nodes["p_number"]]["views"] == {"data": number}
    assert done[nodes["rows"]]["views"]["table"]["total_rows"] == 1000


def test_unknown_keys_answer_404(run: tuple[TestClient, dict[str, str]]) -> None:
    client, _ = run
    r = client.get(f"/api/table/{'0' * 64}.table")
    assert r.status_code == 404 and r.json()["detail"] == "not in the cache; run first"
    assert client.get("/api/table/nonsense").status_code == 404
    assert client.get(f"/api/table/{'0' * 64}.table[0]").status_code == 404


def test_disk_cache_off(run: tuple[TestClient, dict[str, str]]) -> None:
    client, nodes = run
    ex = _session(client).executor
    key = _output(client, nodes["rows"])["keys"]["table"]
    folder, ex.cache_dir = ex.cache_dir, None
    try:
        out = _output(client, nodes["p_rows"])
        assert out["disk_cache"] is False and len(out["views"]["data"]["rows"]) == 200
        r = client.get(f"/api/table/{key}")
        assert r.status_code == 404 and "disk cache is off" in r.json()["detail"]
    finally:
        ex.cache_dir = folder
