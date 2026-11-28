"""Map Viewer data (SPEC 8, 9): layers, tiles, GeoJSON, inspect, overviews, styles.

PLAN Phase 7 "Done when" (server side): the predicted raster and the reference
points sit in the right place, and a clicked pixel's value equals the value
rasterio reads at that coordinate.
"""

import json
import shutil
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import morecantile
import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from rasterio.warp import transform_bounds

from geoknit.core.cache import DiskCache
from geoknit.server import tiles
from geoknit.server.session import Session
from tests.conftest import SYNTHETIC
from tests.server.conftest import make_client

TMS = morecantile.tms.get("WebMercatorQuad")


def _session(client: TestClient) -> Session:
    return client.app.state.session  # type: ignore[attr-defined,no-any-return]


def _add(client: TestClient, component: str) -> str:
    r = client.post("/api/nodes", json={"component": component, "position": [0, 0]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wire(client: TestClient, src: str, port: str, dst: str) -> None:
    r = client.post("/api/wires", json={"from": [src, port], "to": [dst, "layers"]})
    assert r.status_code == 201, r.text


def _run(client: TestClient) -> None:
    r = client.post("/api/run", json={"mode": "all"})
    assert r.status_code == 202, r.text
    _session(client).wait(120)
    states = client.get("/api/graph").json()["nodes"]
    failed = {k: v["state"] for k, v in states.items() if v["state"] != "done"}
    assert not failed, failed


def _png(data: bytes) -> np.ndarray:
    """RGBA PNG → (256, 256, 4) array."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with MemoryFile(data) as mem, mem.open() as ds:
            assert ds.count == 4
            return np.moveaxis(ds.read(), 0, -1)


def _tile_at(lon: float, lat: float, z: int) -> tuple[int, int, int]:
    t = TMS.tile(lon, lat, z)
    return t.z, t.x, t.y


@pytest.fixture(scope="module")
def imd(
    tmp_path_factory: pytest.TempPathFactory, synthetic_data: dict[str, Path]
) -> Iterator[tuple[TestClient, str, Path]]:
    """The synthetic workflow, run once, with a Map Viewer wired to five outputs.

    Layers in wire order: prediction (n17.map, a COG), reference test points
    (n10.test), classes (n4.classes), predictors (n12.raster, a ref to the
    source file). The model (n16.model) cannot be wired in since change 03.
    """
    root = tmp_path_factory.mktemp("map")
    project = root / "project"
    (project / "data").mkdir(parents=True)
    for path in synthetic_data.values():
        shutil.copy(path, project / "data" / path.name)
    shutil.copy(SYNTHETIC / "imd.geoknit", project / "imd.geoknit")
    with make_client(project, root / "home" / "trusted.json") as client:
        client.post("/api/workflow/open", json={"path": "imd.geoknit"})
        client.post("/api/workflow/trust")
        viewer = _add(client, "param/map")
        for src, port in (
            ("n17", "map"),
            ("n10", "test"),
            ("n4", "classes"),
            ("n12", "raster"),
        ):
            _wire(client, src, port, viewer)
        r = client.post("/api/wires", json={"from": ["n16", "model"], "to": [viewer, "layers"]})
        assert r.status_code == 400 and "Raster | Vector | Layer" in r.json()["detail"]
        before = client.get(f"/api/map/{viewer}").json()
        assert {layer["status"] for layer in before["layers"]} == {"not_run"}
        _run(client)
        yield client, viewer, project


def _layers(client: TestClient, viewer: str) -> dict[str, Any]:
    r = client.get(f"/api/map/{viewer}")
    assert r.status_code == 200, r.text
    return {layer["id"]: layer for layer in r.json()["layers"]}


def _cache(client: TestClient) -> DiskCache:
    return _session(client).map_cache()


def test_layers_describe_each_wire(imd: tuple[TestClient, str, Path]) -> None:
    client, viewer, _ = imd
    view = client.get(f"/api/map/{viewer}").json()
    assert view["basemap"] == "auto" and "viridis" in view["colormaps"]
    layers = {layer["id"]: layer for layer in view["layers"]}
    assert list(layers) == ["n17.map", "n10.test", "n4.classes", "n12.raster"]
    assert layers["n17.map"]["title"] == "Predict Raster › map"
    assert {k: v["status"] for k, v in layers.items()} == {
        "n17.map": "ready",
        "n10.test": "ready",
        "n4.classes": "ready",
        "n12.raster": "ready",
    }
    assert all(layer["from_layer"] is None and layer["locked"] == [] for layer in layers.values())

    pred = layers["n17.map"]
    assert pred["type"] == "Raster"
    assert pred["style"]["colormap"] == "viridis" and pred["style"]["bands"] == [1]
    assert pred["style"]["min"] < pred["style"]["max"]

    classes = layers["n4.classes"]
    assert classes["style"]["colormap"] == "categorical"
    values = [c["value"] for c in classes["raster"]["stats"]["classes"]]
    assert set(values) <= set(range(8)) and len(values) >= 3

    predictors = layers["n12.raster"]
    assert predictors["raster"]["bands"][:2] == ["A00", "A01"]
    assert len(predictors["raster"]["bands"]) == 8

    points = layers["n10.test"]
    assert points["type"] == "Vector" and points["vector"]["features"] == 42
    assert points["vector"]["geometry"] == ["Point"]


def test_layers_sit_in_the_right_place(
    imd: tuple[TestClient, str, Path], synthetic_data: dict[str, Path]
) -> None:
    client, viewer, _ = imd
    layers = _layers(client, viewer)
    with rasterio.open(synthetic_data["predictors"]) as ds:
        expected = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds, densify_pts=21)
    for layer in ("n17.map", "n12.raster", "n4.classes"):
        assert layers[layer]["raster"]["bounds"] == pytest.approx(expected, abs=1e-9)
    west, south, east, north = layers["n10.test"]["vector"]["bounds"]
    assert expected[0] <= west < east <= expected[2]
    assert expected[1] <= south < north <= expected[3]


def test_raster_tiles(imd: tuple[TestClient, str, Path]) -> None:
    client, viewer, _ = imd
    layers = _layers(client, viewer)
    key = layers["n17.map"]["key"]
    west, south, east, north = layers["n17.map"]["raster"]["bounds"]
    z, x, y = _tile_at((west + east) / 2, (south + north) / 2, 14)

    r = client.get(f"/tiles/{key}/{z}/{x}/{y}.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = _png(r.content)
    assert img.shape == (256, 256, 4)
    assert (img[..., 3] == 255).sum() > 1000  # the raster covers part of the tile
    assert len(np.unique(img[..., :3].reshape(-1, 3), axis=0)) > 10  # a colour ramp

    # far away: fully transparent
    fz, fx, fy = _tile_at(-70.0, -40.0, 14)
    far = _png(client.get(f"/tiles/{key}/{fz}/{fx}/{fy}.png").content)
    assert (far[..., 3] == 0).all()

    # classes in the categorical palette; three predictor bands as RGB
    ckey = layers["n4.classes"]["key"]
    cls = _png(client.get(f"/tiles/{ckey}/{z}/{x}/{y}.png?colormap=categorical").content)
    shown = {tuple(int(v) for v in c) for c in cls[cls[..., 3] == 255][:, :3]}
    palette = {tuple(int(h[i : i + 2], 16) for i in (1, 3, 5)) for h in tiles.PALETTE}
    assert shown and shown <= palette
    pkey = layers["n12.raster"]["key"]
    rgb = client.get(f"/tiles/{pkey}/{z}/{x}/{y}.png?bands=3,2,1&min=0&max=1")
    assert rgb.status_code == 200

    assert client.get(f"/tiles/{key}/{z}/{x}/{y}.png?bands=9").status_code == 400
    assert client.get(f"/tiles/{key}/{z}/{x}/{y}.png?colormap=nope").status_code == 400
    assert client.get(f"/tiles/{'0' * 64}.map/{z}/{x}/{y}.png").status_code == 404
    assert client.get(f"/tiles/..%2F..%2Fsecret/{z}/{x}/{y}.png").status_code == 404


def _centre_tile(layer: dict[str, Any], z: int = 14) -> tuple[int, int, int]:
    west, south, east, north = layer["raster"]["bounds"]
    return _tile_at((west + east) / 2, (south + north) / 2, z)


def _cmap_tile(client: TestClient, key: str, tile: tuple[int, int, int], cmap: Any) -> np.ndarray:
    z, x, y = tile
    text = json.dumps(cmap, separators=(",", ":"))
    r = client.get(f"/tiles/{key}/{z}/{x}/{y}.png", params={"cmap": text})
    assert r.status_code == 200, r.text
    return _png(r.content)


def _class_values(client: TestClient, key: str, tile: tuple[int, int, int]) -> np.ndarray:
    """Class value of each pixel of the tile (-1 where transparent), read back from the
    categorical palette (the synthetic classes are 0-7, so each has its own colour)."""
    z, x, y = tile
    img = _png(client.get(f"/tiles/{key}/{z}/{x}/{y}.png?colormap=categorical").content)
    out = np.full(img.shape[:2], -1)
    for value, colour in enumerate(tiles.PALETTE[:8]):
        rgb = [int(colour[i : i + 2], 16) for i in (1, 3, 5)]
        out[(img[..., :3] == rgb).all(axis=-1) & (img[..., 3] == 255)] = value
    return out


def test_classes_colormap_tiles(imd: tuple[TestClient, str, Path]) -> None:
    """Done when: classes {1: red, 2: blue} colour exactly those classes, the rest
    transparent with other: None."""
    client, viewer, _ = imd
    layer = _layers(client, viewer)["n4.classes"]
    key, tile = layer["key"], _centre_tile(layer)
    values = _class_values(client, key, tile)
    assert (values == 1).sum() > 0 and (values == 2).sum() > 0 and (values > 2).sum() > 0

    cmap = {
        "kind": "classes",
        "classes": [[1, "#FF0000", "low"], [2, "#0000FF", ""]],
        "other": None,
    }
    img = _cmap_tile(client, key, tile, cmap)
    assert (img[values == 1] == [255, 0, 0, 255]).all()
    assert (img[values == 2] == [0, 0, 255, 255]).all()
    assert (img[(values != 1) & (values != 2)][:, 3] == 0).all()

    # `other` colours the rest; an #RRGGBBAA alpha multiplies the tile's
    cmap = {"kind": "classes", "classes": [[1, "#FF000080", ""]], "other": "#00FF00"}
    img = _cmap_tile(client, key, tile, cmap)
    assert (img[values == 1] == [255, 0, 0, 128]).all()
    assert (img[values >= 2] == [0, 255, 0, 255]).all()
    assert (img[values == -1][:, 3] == 0).all()  # outside the raster stays transparent


def test_continuous_colormap_tiles(imd: tuple[TestClient, str, Path]) -> None:
    """Done when: a custom ramp with fixed min/max gives the stop colour at the stop's value."""
    client, viewer, _ = imd
    layer = _layers(client, viewer)["n4.classes"]
    key, tile = layer["key"], _centre_tile(layer)
    values = _class_values(client, key, tile)
    stops = [[0, "#000000"], [0.2, "#FF8000"], [0.6, "#20C0A0"], [1, "#FFFFFF"]]
    cmap = {"kind": "continuous", "stops": stops, "min": 0, "max": 5, "reverse": False}
    img = _cmap_tile(client, key, tile, cmap)
    for value, colour in ((1, (255, 128, 0)), (3, (32, 192, 160))):  # 1 → 0.2, 3 → 0.6
        shown = img[values == value]
        assert len(shown) and (np.abs(shown[:, :3].astype(int) - colour) <= 1).all()
        assert (shown[:, 3] == 255).all()

    # reversed: 1 now sits at 0.8, between the 0.6 and 1 stops
    img = _cmap_tile(client, key, tile, {**cmap, "reverse": True})
    expected = np.round((np.array([32, 192, 160]) + 255) / 2)
    assert (np.abs(img[values == 1][:, :3] - expected) <= 1).all()

    assert (
        client.get(
            f"/tiles/{key}/{tile[0]}/{tile[1]}/{tile[2]}.png", params={"cmap": "{bad"}
        ).status_code
        == 400
    )
    bad = json.dumps({"kind": "continuous", "stops": [[0, "#000000"]]})
    r = client.get(f"/tiles/{key}/{tile[0]}/{tile[1]}/{tile[2]}.png", params={"cmap": bad})
    assert r.status_code == 400 and "2 stops" in r.json()["detail"]


def test_named_colormap_draws_as_today(imd: tuple[TestClient, str, Path]) -> None:
    """Done when: a named ramp without customisation renders the same bytes as by name."""
    client, viewer, _ = imd
    layer = _layers(client, viewer)["n17.map"]
    key, (z, x, y) = layer["key"], _centre_tile(layer)
    for name in ("viridis", "terrain"):
        today = client.get(f"/tiles/{key}/{z}/{x}/{y}.png?colormap={name}&min=5&max=80").content
        cmap = json.dumps({"kind": "continuous", "name": name, "min": None, "max": None})
        r = client.get(f"/tiles/{key}/{z}/{x}/{y}.png?min=5&max=80", params={"cmap": cmap})
        assert r.content == today
        fixed = json.dumps({"kind": "continuous", "name": name, "min": 5, "max": 80})
        assert client.get(f"/tiles/{key}/{z}/{x}/{y}.png", params={"cmap": fixed}).content == today
    # no min/max anywhere: the 2-98 % stretch, as by name
    today = client.get(f"/tiles/{key}/{z}/{x}/{y}.png?colormap=magma").content
    cmap = json.dumps({"kind": "continuous", "name": "magma"})
    assert client.get(f"/tiles/{key}/{z}/{x}/{y}.png", params={"cmap": cmap}).content == today
    # reversed: rio-tiler's table backwards
    lut = tiles.colormap_lut(tiles.types.Colormap.named("magma", reverse=True))
    assert (lut == tiles._lut("magma")[::-1]).all()


def test_colormap_objects_are_saved_as_styles(imd: tuple[TestClient, str, Path]) -> None:
    client, viewer, _ = imd
    cmap = {"kind": "classes", "classes": [[1, "#ff0000", "Built"]], "other": None}
    r = client.patch(
        f"/api/nodes/{viewer}", json={"map": {"styles": {"n4.classes": {"colormap": cmap}}}}
    )
    assert r.status_code == 200, r.text
    saved = {"kind": "classes", "classes": [[1, "#FF0000", "Built"]], "other": None}
    assert r.json()["map"]["styles"]["n4.classes"]["colormap"] == saved
    assert client.get("/api/graph").json()["out_of_date"] == 0
    # the legend data: GET /api/map gives the Colormap in the layer's style
    assert _layers(client, viewer)["n4.classes"]["style"]["colormap"] == saved

    bad = {"kind": "classes", "classes": []}
    r = client.patch(
        f"/api/nodes/{viewer}", json={"map": {"styles": {"n4.classes": {"colormap": bad}}}}
    )
    assert r.status_code == 400 and "at least one class" in r.json()["detail"]
    client.patch(f"/api/nodes/{viewer}", json={"map": {"styles": {"n4.classes": None}}})


def test_band_statistics(imd: tuple[TestClient, str, Path]) -> None:
    client, viewer, _ = imd
    key = _layers(client, viewer)["n12.raster"]["key"]
    one = client.get(f"/api/raster/{key}/stats?bands=5").json()
    assert one["min"] < one["max"] and one["classes"] is None
    assert client.get(f"/api/raster/{key}/stats?bands=12").status_code == 400


def test_clicked_value_equals_rasterio(imd: tuple[TestClient, str, Path]) -> None:
    """Done when: the clicked pixel value equals the value read with rasterio there."""
    client, viewer, _ = imd
    layers = _layers(client, viewer)
    cache = _cache(client)
    pred_file = tiles.raster_path(cache, layers["n17.map"]["key"])
    predictors_file = tiles.raster_path(cache, layers["n12.raster"]["key"])
    with rasterio.open(pred_file) as ds:
        to_wgs84 = Transformer.from_crs(ds.crs, "EPSG:4326", always_xy=True)
        x, y = (float(v) for v in ds.xy(57, 131))  # a pixel centre, nudged below
        lon, lat = to_wgs84.transform(x + 2.0, y - 3.0)
        expected = next(ds.sample([(x + 2.0, y - 3.0)]))[0]
    with rasterio.open(predictors_file) as ds:
        expected_bands = next(ds.sample([(x + 2.0, y - 3.0)]))

    r = client.get(f"/api/map/{viewer}/inspect", params={"lon": lon, "lat": lat})
    assert r.status_code == 200, r.text
    found = {layer["id"]: layer for layer in r.json()["layers"]}
    assert set(found) == {"n17.map", "n4.classes", "n12.raster"}  # rasters only
    assert found["n17.map"]["values"][0]["value"] == pytest.approx(float(expected), rel=1e-6)
    assert [v["band"] for v in found["n12.raster"]["values"]][:2] == ["A00", "A01"]
    assert [v["value"] for v in found["n12.raster"]["values"]] == pytest.approx(
        [float(v) for v in expected_bands], rel=1e-6
    )

    outside = client.get(f"/api/map/{viewer}/inspect", params={"lon": 0.0, "lat": 0.0}).json()
    assert all(layer["outside"] for layer in outside["layers"])
    assert all(v["value"] is None for v in outside["layers"][0]["values"])


def test_vector_geojson(imd: tuple[TestClient, str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    client, viewer, _ = imd
    layers = _layers(client, viewer)
    key = layers["n10.test"]["key"]
    r = client.get(f"/api/vector/{key}.geojson")
    assert r.status_code == 200 and r.headers["x-geoknit-features"] == "42"
    data = r.json()
    assert len(data["features"]) == 42
    lon, lat = data["features"][0]["geometry"]["coordinates"]
    west, south, east, north = layers["n17.map"]["raster"]["bounds"]
    assert west <= lon <= east and south <= lat <= north
    assert set(data["features"][0]["properties"]) == {"IMD", "cls"}

    monkeypatch.setattr(tiles, "MAX_FEATURES", 5)
    r = client.get(f"/api/vector/{key}.geojson")
    assert len(r.json()["features"]) == 5 and r.headers["x-geoknit-features"] == "42"
    raster_key = layers["n17.map"]["key"]
    assert client.get(f"/api/vector/{raster_key}.geojson").status_code == 404


def test_styles_are_saved_and_never_make_anything_out_of_date(
    imd: tuple[TestClient, str, Path],
) -> None:
    client, viewer, project = imd
    r = client.patch(
        f"/api/nodes/{viewer}",
        json={
            "map": {
                "basemap": "none",
                "styles": {"n17.map": {"colormap": "magma", "min": 10, "opacity": 0.5}},
            }
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["map"]["styles"]["n17.map"]["colormap"] == "magma"
    assert client.get("/api/graph").json()["out_of_date"] == 0
    view = client.get(f"/api/map/{viewer}").json()
    pred = next(layer for layer in view["layers"] if layer["id"] == "n17.map")
    assert view["basemap"] == "none"
    assert (pred["style"]["colormap"], pred["style"]["min"], pred["style"]["opacity"]) == (
        "magma",
        10,
        0.5,
    )
    assert pred["style"]["max"] == pred["raster"]["default_style"]["max"]

    bad = client.patch(
        f"/api/nodes/{viewer}", json={"map": {"styles": {"n17.map": {"opacity": 3}}}}
    )
    assert bad.status_code == 400 and "opacity" in bad.json()["detail"]
    assert client.patch("/api/nodes/n17", json={"map": {"basemap": "none"}}).status_code == 400

    # saved with the workflow, and one undo step
    client.post("/api/workflow/save", json={"path": "with_map.geoknit"})
    saved = json.loads((project / "with_map.geoknit").read_text(encoding="utf-8"))
    node = next(n for n in saved["nodes"] if n["id"] == viewer)
    assert node["component"] == "param/map" and node["map"]["basemap"] == "none"
    client.patch(f"/api/nodes/{viewer}", json={"map": {"styles": {"n17.map": None}}})
    assert "styles" not in client.get("/api/graph").json()["nodes"][viewer]["map"]
    client.post("/api/undo")
    assert "n17.map" in client.get("/api/graph").json()["nodes"][viewer]["map"]["styles"]


def test_basemap_values(imd: tuple[TestClient, str, Path]) -> None:
    client, viewer, _ = imd
    # no saved key means "auto" (follows the theme); see test_layers_describe_each_wire
    assert client.get(f"/api/map/{viewer}").json()["basemaps"] == ["auto", "light", "dark", "none"]
    for basemap in ("light", "dark", "none", "auto"):
        r = client.patch(f"/api/nodes/{viewer}", json={"map": {"basemap": basemap}})
        assert r.status_code == 200, r.text
        assert r.json()["map"]["basemap"] == basemap
        assert client.get(f"/api/map/{viewer}").json()["basemap"] == basemap
    # a saved "light" stays "light"
    client.patch(f"/api/nodes/{viewer}", json={"map": {"basemap": "light"}})
    assert client.get(f"/api/map/{viewer}").json()["basemap"] == "light"
    bad = client.patch(f"/api/nodes/{viewer}", json={"map": {"basemap": "satellite"}})
    assert bad.status_code == 400 and "basemap is one of" in bad.json()["detail"]
    assert client.get(f"/api/map/{viewer}").json()["basemap"] == "light"


def test_large_source_raster_gets_overviews_in_the_cache(tmp_path: Path, trust_file: Path) -> None:
    """Done when (proxy): tiles of a big raster come from overviews, not full reads."""
    project = tmp_path / "project"
    (project / "data").mkdir(parents=True)
    src = project / "data" / "big.tif"
    n = 3000
    with rasterio.open(
        src, "w", driver="GTiff", width=n, height=n, count=2, dtype="float32",
        crs="EPSG:32632", transform=from_origin(500_000, 5_040_000, 10, 10),
        tiled=True, blockxsize=256, blockysize=256,
    ) as ds:  # fmt: skip
        ramp = np.tile(np.linspace(0, 1, n, dtype="float32"), (n, 1))
        ds.write(np.stack([ramp, ramp.T]))
    with make_client(project, trust_file) as client:
        text = _add(client, "param/text")
        client.patch(f"/api/nodes/{text}", json={"value": "data/big.tif"})
        read = _add(client, "builtin/raster/read_raster")
        client.post("/api/wires", json={"from": [text, "value"], "to": [read, "path"]})
        viewer = _add(client, "param/map")
        _wire(client, read, "raster", viewer)
        _run(client)

        layer = _layers(client, viewer)[f"{read}.raster"]
        assert layer["status"] == "ready", layer
        path = tiles.raster_path(_cache(client), layer["key"])
        assert path.suffix == ".vrt" and path.with_name(path.name + ".ovr").is_file()
        with rasterio.open(path) as ds:
            assert ds.overviews(1)[:3] == [2, 4, 8]
        assert sorted(p.name for p in src.parent.iterdir()) == ["big.tif"]  # untouched

        west, south, east, north = layer["raster"]["bounds"]
        z, x, y = _tile_at((west + east) / 2, (south + north) / 2, 9)
        img = _png(client.get(f"/tiles/{layer['key']}/{z}/{x}/{y}.png").content)
        assert (img[..., 3] == 255).any()


def test_no_disk_cache_means_nothing_to_show(client: TestClient) -> None:
    viewer = _add(client, "param/map")
    _session(client).executor.cache_dir = None
    assert client.get(f"/api/map/{viewer}").json()["layers"] == []
    r = client.get(f"/api/raster/{'0' * 64}.map/stats")
    assert r.status_code == 400 and "disk cache is off" in r.json()["detail"]


def test_many_band_rasters_are_drawn_through_a_band_vrt(imd: tuple[TestClient, str, Path]) -> None:
    """GDAL warps every band it reads: 8 predictor bands → a one-band VRT per shown band."""
    client, viewer, _ = imd
    layer = _layers(client, viewer)["n12.raster"]
    west, south, east, north = layer["raster"]["bounds"]
    z, x, y = _tile_at((west + east) / 2, (south + north) / 2, 14)
    five = _png(client.get(f"/tiles/{layer['key']}/{z}/{x}/{y}.png?bands=5&min=0&max=1").content)
    six = _png(client.get(f"/tiles/{layer['key']}/{z}/{x}/{y}.png?bands=6&min=0&max=1").content)
    assert (five[..., 3] == 255).any() and not np.array_equal(five, six)
    entry = tiles.raster_path(_cache(client), layer["key"])
    names = {p.name for p in tiles._raster_file(_cache(client), layer["key"])[0].iterdir()}
    assert {f"{entry.name}.bands-5.vrt", f"{entry.name}.bands-6.vrt"} <= names
    assert (
        client.get(f"/tiles/{layer['key']}/{z}/{x}/{y}.png?bands=9&min=0&max=1").status_code == 400
    )


def test_a_run_closes_the_files_the_map_keeps_open(imd: tuple[TestClient, str, Path]) -> None:
    """On Windows an open file cannot be replaced or deleted, so tiles must not hold them."""
    client, viewer, _ = imd
    layer = _layers(client, viewer)["n17.map"]
    west, south, east, north = layer["raster"]["bounds"]
    z, x, y = _tile_at((west + east) / 2, (south + north) / 2, 14)
    assert client.get(f"/tiles/{layer['key']}/{z}/{x}/{y}.png").status_code == 200
    assert tiles._pool.open_files >= 1  # kept for the next tile
    _run(client)
    assert tiles._pool.open_files == 0
