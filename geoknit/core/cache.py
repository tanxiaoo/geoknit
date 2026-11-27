"""Cache keys and the disk cache (SPEC 6 "Cache").

Keys depend only on the graph and on the files it refers to, so every node can
be keyed in topological order without running anything:

- component node: ``sha256`` of the cache format, the component source (which
  already holds its settings), the upstream port keys of each input (ports
  sorted by name, wires in wire order), and a fingerprint of every file named
  by a text setting;
- ``param/text``: its value plus the fingerprint of the file it names, if any;
- ``param/slider``: its value;
- ``param/panel``: no key of its own; its ``data`` output reuses the key of the
  wire feeding it;
- ``param/map``: no key and no outputs (the Map Viewer reads its inputs' entries).

A port key is ``<node key>.<port>``. A file fingerprint is the absolute path
(``/`` separators), size and modification time of a text value that resolves
to an existing file relative to the project folder.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geoknit.core import types
from geoknit.core.graph import PARAM_MAP, PARAM_PANEL, PARAM_SLIDER, PARAM_TEXT, Graph, Node
from geoknit.core.types import RASTER_CHUNKS

CACHE_FORMAT = 1
"""Bump when the key recipe or the disk layout changes; old entries then miss."""

EMPTY_KEY = hashlib.sha256(b"geoknit:empty").hexdigest()
"""Port key of an unconnected Panel's output (value ``None``)."""


def _sha(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def port_key(node_key: str, port: str) -> str:
    return f"{node_key}.{port}"


def file_fingerprint(value: str, base_dir: Path | None) -> list[Any] | None:
    """``[path, size, mtime_ns]`` if ``value`` names an existing file, else ``None``."""
    if not value or "\n" in value or len(value) > 1024:
        return None
    try:
        p = Path(value)
        if not p.is_absolute():
            if base_dir is None:
                return None
            p = base_dir / p
        if not p.is_file():
            return None
        st = p.stat()
        return [p.resolve().as_posix(), st.st_size, st.st_mtime_ns]
    except (OSError, ValueError):
        return None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [v for v in value if isinstance(v, str)]
    return []


def _feeds_only_written_files(graph: Graph, node_id: str) -> bool:
    """True when every wire out of ``node_id`` goes to a ``file: write`` input."""
    out = [w for w in graph.wires if w.src == node_id]
    return bool(out) and all(
        getattr(graph.nodes[w.dst].inputs.get(w.dst_port), "file", None) == "write" for w in out
    )


def node_files(node: Node, base_dir: Path | None, graph: Graph | None = None) -> list[list[Any]]:
    """Fingerprints of the files named by a node's text value or text settings.

    Paths of files a component writes (``file: write`` inputs) are left out:
    the write itself would otherwise change the key on every Run.
    """
    texts: list[str] = []
    if node.component == PARAM_TEXT:
        if graph is None or not _feeds_only_written_files(graph, node.id):
            texts = _strings(node.value)
    elif node.spec is not None and not node.is_param:
        for s in node.spec.settings.values():
            port = node.spec.inputs.get(s.name)
            if port is not None and port.file == "write":
                continue
            texts.extend(_strings(s.value))
    found = (file_fingerprint(t, base_dir) for t in texts)
    return [f for f in found if f is not None]


@dataclass
class GraphKeys:
    """Cache keys for every node and output port of a graph."""

    nodes: dict[str, str | None] = field(default_factory=dict)
    """Node key, or ``None`` for a Panel (it has no work of its own)."""
    ports: dict[str, dict[str, str]] = field(default_factory=dict)
    inputs: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    """Upstream port keys feeding each input, in wire order."""
    values: dict[str, Any] = field(default_factory=dict)
    """Port key → value for Text, Slider and empty Panel outputs."""


def compute_keys(graph: Graph, base_dir: Path | None = None) -> GraphKeys:
    """Key every node of ``graph`` in topological order."""
    keys = GraphKeys()
    for nid in graph.topological_order():
        node = graph.nodes[nid]
        inputs: dict[str, list[str]] = {}
        for name in sorted(node.inputs):
            wires = graph.wires_into(nid, name)
            if wires:
                inputs[name] = [keys.ports[w.src][w.src_port] for w in wires]
        keys.inputs[nid] = inputs

        if node.component == PARAM_PANEL:
            keys.nodes[nid] = None
            upstream = inputs.get("data")
            data_key = upstream[0] if upstream else EMPTY_KEY
            if not upstream:
                keys.values[EMPTY_KEY] = None
            keys.ports[nid] = {"data": data_key}
            continue

        if node.component == PARAM_MAP:  # shows its inputs; nothing to key or store
            keys.nodes[nid] = None
            keys.ports[nid] = {}
            continue

        if node.component in (PARAM_TEXT, PARAM_SLIDER):
            kind = "text" if node.component == PARAM_TEXT else "number"
            nkey = _sha(
                {
                    "format": CACHE_FORMAT,
                    kind: node.value,
                    "files": node_files(node, base_dir, graph),
                }
            )
            pkey = port_key(nkey, "value")
            keys.values[pkey] = node.value
        else:
            nkey = _sha(
                {
                    "format": CACHE_FORMAT,
                    "source": node.source,
                    "inputs": inputs,
                    "files": node_files(node, base_dir, graph),
                }
            )
        keys.nodes[nid] = nkey
        keys.ports[nid] = {p: port_key(nkey, p) for p in node.outputs}
    return keys


# ── Disk cache ───────────────────────────────────────────────────────────────

DEFAULT_LIMIT = 10 * 1024**3
"""10 GB (SPEC 6)."""

META = "meta.json"


class CacheMiss(LookupError):
    """No usable disk cache entry for a key."""


def split_port_key(key: str) -> tuple[str, str]:
    """``"<node key>.<port>"`` → ``(node key, port)``."""
    node_key, sep, port = key.rpartition(".")
    if not sep:
        raise ValueError(f'"{key}" is not a port key')
    return node_key, port


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class DiskCache:
    """``<project>/.geoknit/cache/<node key>/``: one file per output port plus ``meta.json``.

    Raster → COG (``.tif``), or ``.ref.json`` for a raster that is still a lazy
    view of a source file; Vector → GeoParquet; Table → Parquet; Model → joblib;
    Number / Text → JSON. A Vector or Table that Parquet cannot store (e.g.
    mixed-type object columns) falls back to pickle. The modification time of
    ``meta.json`` is the entry's last use, for least-recently-used eviction.
    """

    def __init__(self, root: Path, limit_bytes: int = DEFAULT_LIMIT) -> None:
        self.root = Path(root)
        self.limit_bytes = limit_bytes

    def _entry(self, node_key: str) -> Path:
        return self.root / node_key

    def has(self, node_key: str) -> bool:
        return (self._entry(node_key) / META).is_file()

    def meta(self, node_key: str) -> dict[str, Any]:
        try:
            return json.loads((self._entry(node_key) / META).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise CacheMiss(node_key) from None

    # ── read ──
    def read(self, node_key: str) -> tuple[dict[str, Any], dict[str, str]]:
        """``(outputs, summaries)`` for ``node_key``; raises ``CacheMiss``."""
        entry = self._entry(node_key)
        meta = self.meta(node_key)
        if meta.get("format") != CACHE_FORMAT:
            self.remove(node_key)
            raise CacheMiss(node_key)
        outputs: dict[str, Any] = {}
        try:
            for port, info in meta["ports"].items():
                outputs[port] = _read_value(entry, info)
        except Exception:  # noqa: BLE001  (a stale or damaged entry is just a miss)
            self.remove(node_key)
            raise CacheMiss(node_key) from None
        self._touch(node_key)
        return outputs, dict(meta.get("summaries", {}))

    def port_info(self, key: str) -> tuple[Path, dict[str, Any]]:
        """``(entry folder, port info from meta.json)`` for a port key; raises ``CacheMiss``."""
        node_key, port = split_port_key(key)
        meta = self.meta(node_key)
        info = meta.get("ports", {}).get(port)
        if meta.get("format") != CACHE_FORMAT or info is None:
            raise CacheMiss(key)
        return self._entry(node_key), info

    def read_port(self, key: str) -> Any:
        """One output, read like ``read`` does (rasters lazily); raises ``CacheMiss``.

        Unlike ``read`` it never removes the entry: the Map Viewer only looks.
        """
        entry, info = self.port_info(key)
        try:
            return _read_value(entry, info)
        except CacheMiss:
            raise
        except Exception:  # noqa: BLE001  (damaged entry: just a miss here)
            raise CacheMiss(key) from None

    def written_rasters(self, node_key: str) -> dict[str, Any]:
        """Rasters of ``node_key`` stored as COGs, opened lazily from the cache.

        After writing a computed raster (e.g. a lazy prediction), the worker
        swaps its in-memory value for this file view, so downstream nodes read
        the COG instead of computing the raster again. A list port with a COG
        element is read back whole (its other elements are cheap: lazy views or
        small values).
        """
        entry = self._entry(node_key)
        out: dict[str, Any] = {}
        for port, info in self.meta(node_key).get("ports", {}).items():
            if _has_cog(entry, info):
                out[port] = _read_value(entry, info)
        return out

    def _touch(self, node_key: str) -> None:
        try:
            os.utime(self._entry(node_key) / META)
        except OSError:
            pass

    # ── write ──
    def write(
        self,
        node_key: str,
        outputs: dict[str, Any],
        summaries: dict[str, str] | None = None,
        *,
        protect: Iterable[str] = (),
    ) -> None:
        """Store ``outputs`` for ``node_key`` atomically, then evict old entries.

        ``protect`` names entries that must not be evicted (the worker still
        holds lazy views of their files).
        """
        if self.has(node_key):
            self._touch(node_key)
            return
        if self._entry(node_key).exists():  # leftover of a removal that hit a locked file
            self.remove(node_key)
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{node_key}.tmp-{os.getpid()}"
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir()
        try:
            ports = {port: _write_value(tmp, port, value) for port, value in outputs.items()}
            meta: dict[str, Any] = {
                "format": CACHE_FORMAT,
                "ports": ports,
                "summaries": summaries or {},
            }
            meta["size"] = _dir_size(tmp)
            (tmp / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
            try:
                tmp.rename(self._entry(node_key))
            except OSError:
                if not self.has(node_key):  # pragma: no cover  (failed for another reason)
                    raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.evict(protect={node_key, *protect})

    # ── housekeeping ──
    def entries(self) -> list[tuple[str, int, float]]:
        """``(node key, size, last used)`` for every complete entry."""
        out: list[tuple[str, int, float]] = []
        if not self.root.is_dir():
            return out
        for d in self.root.iterdir():
            meta_file = d / META
            if d.is_dir() and meta_file.is_file():
                try:
                    size = int(json.loads(meta_file.read_text(encoding="utf-8")).get("size", 0))
                    out.append((d.name, size, meta_file.stat().st_mtime))
                except (OSError, ValueError):
                    continue
        return out

    def size(self) -> int:
        return sum(size for _, size, _ in self.entries())

    def evict(self, protect: Iterable[str] = ()) -> list[str]:
        """Remove least-recently-used entries until under the limit; return their keys.

        Entries in ``protect`` are never removed, so the cache may stay above
        the limit while the worker holds them.
        """
        self.sweep()
        keep = set(protect)
        entries = sorted(self.entries(), key=lambda e: e[2])
        total = sum(size for _, size, _ in entries)
        removed: list[str] = []
        for key, size, _ in entries:
            if total <= self.limit_bytes:
                break
            if key in keep:
                continue
            self.remove(key)
            total -= size
            removed.append(key)
        return removed

    def remove(self, node_key: str) -> None:
        """Delete one entry.

        ``meta.json`` goes first, so even if a file is still open (Windows
        refuses to delete open files) the entry is no longer valid; what is left
        is deleted by a later ``sweep``.
        """
        entry = self._entry(node_key)
        try:
            (entry / META).unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(entry, ignore_errors=True)

    def sweep(self) -> None:
        """Delete folders without ``meta.json``: removals that hit a locked file and
        temporary folders of crashed writes (not this process's own)."""
        if not self.root.is_dir():
            return
        own_tmp = f".tmp-{os.getpid()}"
        for d in self.root.iterdir():
            if d.is_dir() and not d.name.endswith(own_tmp) and not (d / META).is_file():
                shutil.rmtree(d, ignore_errors=True)

    def clear(self) -> bool:
        """Delete every entry ("Clear cache"); ``False`` if some files were locked."""
        release_file_handles()
        shutil.rmtree(self.root, ignore_errors=True)
        if not self.root.exists():
            return True
        for d in self.root.iterdir():  # what could not be deleted is at least invalid
            if d.is_dir():
                self.remove(d.name)
        return not self.entries() and not any(self.root.iterdir())


# ── per-type formats ──


JSON_TYPES = (types.NUMBER, types.TEXT, types.BOOLEAN, types.COLOR, types.COLORMAP)
"""Types stored as JSON (one ``{"value": …}`` file, also for a whole list of them)."""

LIST_INDEX = "index.json"


def _write_list(entry: Path, port: str, items: list[Any]) -> dict[str, Any]:
    """A list output (SPEC 6): one JSON file when every element is the same simple
    type, else a folder ``<port>/`` with one file per element plus ``index.json``."""
    kinds = {types.type_of(v) for v in items}
    kind = next(iter(kinds)) if len(kinds) == 1 else None
    info: dict[str, Any] = {"type": kind, "access": "list", "count": len(items)}
    if not items or kind in JSON_TYPES:
        name = f"{port}.json"
        data = [types.to_json_value(types.as_output(v)) for v in items]
        (entry / name).write_text(json.dumps({"value": data}), encoding="utf-8")
        return {**info, "file": name, "format": "json"}
    folder = entry / port
    folder.mkdir()
    elements = [_write_value(folder, str(i), v) for i, v in enumerate(items)]
    (folder / LIST_INDEX).write_text(json.dumps({"items": elements}), encoding="utf-8")
    return {**info, "file": f"{port}/{LIST_INDEX}", "format": "list"}


def _read_list(entry: Path, info: dict[str, Any]) -> list[Any]:
    path = entry / info["file"]
    if info["format"] == "json":
        data = json.loads(path.read_text(encoding="utf-8"))["value"]
        return [types.from_json_value(info.get("type") or "", d) for d in data]
    if info["format"] != "list":
        raise CacheMiss(f"unknown list format {info['format']}")
    index = json.loads(path.read_text(encoding="utf-8"))
    return [_read_value(path.parent, item) for item in index["items"]]


def _has_cog(entry: Path, info: dict[str, Any]) -> bool:
    """Whether a port (or an element of a list port) is a raster stored as a COG."""
    if info.get("access") == "list":
        if info.get("format") != "list":
            return False
        path = entry / info["file"]
        index = json.loads(path.read_text(encoding="utf-8"))
        return any(_has_cog(path.parent, item) for item in index["items"])
    return info.get("type") == types.RASTER and info.get("format") == "cog"


def _write_value(entry: Path, port: str, value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        return _write_list(entry, port, value)
    kind = types.type_of(value)
    if kind in JSON_TYPES:
        name = f"{port}.json"
        data = types.to_json_value(types.as_output(value))
        (entry / name).write_text(json.dumps({"value": data}), encoding="utf-8")
        return {"type": kind, "file": name, "format": "json"}
    if kind == types.RASTER:
        return _write_raster(entry, port, value)
    if kind in (types.VECTOR, types.TABLE):
        name = f"{port}.parquet"
        try:
            value.to_parquet(entry / name)
            fmt = "geoparquet" if kind == types.VECTOR else "parquet"
        except Exception:  # noqa: BLE001  (Parquet refuses some dtypes)
            (entry / name).unlink(missing_ok=True)
            name = f"{port}.pkl"
            value.to_pickle(entry / name)
            fmt = "pickle"
        return {"type": kind, "file": name, "format": fmt}
    if kind == types.MODEL:
        import joblib

        name = f"{port}.joblib"
        joblib.dump(value, entry / name)
        return {"type": kind, "file": name, "format": "joblib"}
    raise TypeError(f'output "{port}": cannot cache {types.python_type_name(value)}')


def _read_value(entry: Path, info: dict[str, Any]) -> Any:
    if info.get("access") == "list":
        return _read_list(entry, info)
    path = entry / info["file"]
    fmt = info["format"]
    if fmt == "json":
        data = json.loads(path.read_text(encoding="utf-8"))["value"]
        return types.from_json_value(info.get("type", ""), data)
    if fmt in ("cog", "ref"):
        return _read_raster(path, info)
    if fmt == "geoparquet":
        import geopandas

        return geopandas.read_parquet(path)
    if fmt == "parquet":
        import pandas

        return pandas.read_parquet(path)
    if fmt == "pickle":
        import pandas

        return pandas.read_pickle(path)
    if fmt == "joblib":
        import joblib

        return joblib.load(path)
    raise CacheMiss(f"unknown cache format {fmt}")


def release_file_handles() -> int:
    """Close the raster files xarray keeps open; return how many were closed.

    Lazy rasters reopen their file on the next read, so this is safe at any
    point between computations. On Windows an open file cannot be replaced or
    deleted, so the worker calls this after every node: users can overwrite a
    source raster between runs and the cache can delete its own files.
    """
    import sys

    file_manager = sys.modules.get("xarray.backends.file_manager")
    if file_manager is None:  # xarray never opened a file here; don't pay for importing it
        return 0
    file_cache = getattr(file_manager, "FILE_CACHE", None)
    if file_cache is None:  # pragma: no cover  (xarray moved it)
        return 0
    closed = 0
    for key in list(file_cache.keys()):
        try:
            file_cache.pop(key).close()
            closed += 1
        except Exception:  # noqa: BLE001, S112  (best effort)
            continue
    return closed


def file_view_source(da: Any) -> Path | None:
    """The source file if ``da`` is still an unchanged lazy view of it, else ``None``.

    True for a raster straight from ``rioxarray.open_rasterio`` (with or
    without dask chunks); false once it has been computed, sliced or modified.
    """
    import numpy as np

    src = da.encoding.get("source")
    if not src or not Path(src).is_file():
        return None
    data = da.data
    if hasattr(data, "dask"):
        prefixes = ("open_rasterio", "original-open_rasterio")
        if not all(str(name).startswith(prefixes) for name in data.dask.layers):
            return None
    elif isinstance(da.variable._data, np.ndarray):
        return None
    import rasterio

    with rasterio.open(src) as ds:
        if tuple(da.shape) != (ds.count, ds.height, ds.width):
            return None
        if tuple(da.rio.transform())[:6] != tuple(ds.transform)[:6]:
            return None
    return Path(src)


def _write_raster(entry: Path, port: str, da: Any) -> dict[str, Any]:
    import rioxarray  # noqa: F401  (registers .rio)

    masked = da.rio.encoded_nodata is not None
    chunked = hasattr(da.data, "dask")
    source = file_view_source(da)
    if source is not None:
        st = source.stat()
        name = f"{port}.ref.json"
        ref = {
            "path": source.resolve().as_posix(),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "long_name": types.raster_band_names(da),
        }
        (entry / name).write_text(json.dumps(ref), encoding="utf-8")
        return {
            "type": types.RASTER,
            "file": name,
            "format": "ref",
            "masked": masked,
            "chunked": chunked,
        }

    import threading

    import numpy as np
    import rasterio.shutil

    name = f"{port}.tif"
    tmp = entry / f"{port}.tmp.tif"
    out = da.copy()
    out.attrs["long_name"] = tuple(types.raster_band_names(da))
    # A tiled GTiff written window by window, then copied to a COG with overviews.
    out.rio.to_raster(
        tmp,
        driver="GTiff",
        tiled=True,
        blockxsize=512,
        blockysize=512,
        compress="DEFLATE",
        lock=threading.Lock() if chunked else None,
    )
    # Overviews serve the Map Viewer's tiles (SPEC 8): nearest keeps class values intact.
    resampling = "NEAREST" if np.issubdtype(np.dtype(da.dtype), np.integer) else "AVERAGE"
    rasterio.shutil.copy(
        tmp, entry / name, driver="COG", COMPRESS="DEFLATE", OVERVIEW_RESAMPLING=resampling
    )
    tmp.unlink()
    return {"type": types.RASTER, "file": name, "format": "cog", "masked": masked}


def _read_raster(path: Path, info: dict[str, Any]) -> Any:
    import rioxarray

    masked = bool(info.get("masked", False))
    if info["format"] == "ref":
        ref = json.loads(path.read_text(encoding="utf-8"))
        src = Path(ref["path"])
        try:
            st = src.stat()
        except OSError:
            raise CacheMiss(f"{src} is gone") from None
        if (st.st_size, st.st_mtime_ns) != (ref["size"], ref["mtime_ns"]):
            raise CacheMiss(f"{src} has changed")
        chunks: Any = dict(RASTER_CHUNKS) if info.get("chunked", True) else None
        da = rioxarray.open_rasterio(src, chunks=chunks, masked=masked)
        da.attrs["long_name"] = tuple(ref["long_name"])
        return da
    return rioxarray.open_rasterio(path, chunks=dict(RASTER_CHUNKS), masked=masked)
