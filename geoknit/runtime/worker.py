"""The worker process: runs components and holds their results (SPEC 2, 6).

Started with the spawn start method by ``geoknit.runtime.client``. Results are
kept in memory by port key; lookups go memory → disk cache → run.
"""

from __future__ import annotations

import os
import traceback
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from geoknit.core import types
from geoknit.core.cache import (
    DEFAULT_LIMIT,
    CacheMiss,
    DiskCache,
    port_key,
    release_file_handles,
    split_port_key,
)
from geoknit.core.component import (
    PRINT_PORT,
    ComponentParseError,
    parse_component,
    run_component,
)
from geoknit.runtime import protocol as p
from geoknit.runtime.geoenv import use_bundled_geo_data


class _MissingInput(Exception):
    pass


class Worker:
    """Message handling, separate from the process loop so it can be tested in-process."""

    def __init__(
        self,
        send: Any,
        project_dir: Path | None = None,
        cache_dir: Path | None = None,
        limit_bytes: int = DEFAULT_LIMIT,
    ) -> None:
        self.send = send
        self.project_dir = project_dir
        self.disk = DiskCache(cache_dir, limit_bytes) if cache_dir is not None else None
        self.memory: dict[str, Any] = {}
        self.summaries: dict[str, str] = {}

    def handle(self, msg: p.ToWorker) -> None:
        if isinstance(msg, p.RunNode):
            self.run_node(msg)
        elif isinstance(msg, p.PutValue):
            self.memory[msg.cache_key] = msg.value
            self.summaries[msg.cache_key] = types.describe(msg.value)
        elif isinstance(msg, p.ClearCache):
            # Results in memory may be lazy views of cache files: drop them first.
            self.memory.clear()
            self.summaries.clear()
            complete = self.disk.clear() if self.disk is not None else True
            self.send(p.Cleared(complete))

    # ── lookups ──
    def _from_disk(self, node_key: str) -> bool:
        """Load a node's outputs from disk into memory; ``False`` on a miss."""
        if self.disk is None or not self.disk.has(node_key):
            return False
        try:
            outputs, summaries = self.disk.read(node_key)
        except CacheMiss:
            return False
        for port, value in outputs.items():
            key = port_key(node_key, port)
            self.memory[key] = value
            self.summaries[key] = summaries.get(port) or types.describe(value)
        return True

    def _lookup(self, key: str, input_name: str) -> Any:
        if key not in self.memory:
            try:
                node_key, _ = split_port_key(key)
            except ValueError:
                node_key = ""
            if not (node_key and self._from_disk(node_key)) or key not in self.memory:
                raise _MissingInput(f'input "{input_name}": no result yet; run it first')
        return self.memory[key]

    def held_node_keys(self) -> set[str]:
        """Node keys whose results are in memory (their cache entries must stay)."""
        held: set[str] = set()
        for key in self.memory:
            node_key, sep, _ = key.rpartition(".")
            if sep:
                held.add(node_key)
        return held

    # ── run_node ──
    def run_node(self, msg: p.RunNode) -> None:
        try:
            self._run_node(msg)
        finally:
            # Lazy rasters reopen on their next read. Closing now means Windows does
            # not keep source files (or cache files) locked between nodes and runs.
            release_file_handles()

    def _run_node(self, msg: p.RunNode) -> None:
        nid = msg.node_id
        try:
            spec = parse_component(msg.source)
        except ComponentParseError as exc:
            self.send(p.Error(nid, str(exc)))
            return
        self.send(p.Started(nid))
        keys = {port: port_key(msg.cache_key, port) for port in spec.outputs}

        if all(k in self.memory for k in keys.values()) or (
            self._from_disk(msg.cache_key) and all(k in self.memory for k in keys.values())
        ):
            self.send(p.Done(nid, self._described(keys), cached=True))
            return

        try:
            inputs: dict[str, Any] = {}
            for name, wired in msg.inputs.items():
                port = spec.inputs.get(name)
                if port is None:
                    raise _MissingInput(f'unknown input "{name}"')
                values = [
                    types.convert_for_input(self._lookup(k, name), port.type)
                    for k in ([wired] if isinstance(wired, str) else wired)
                ]
                inputs[name] = values if port.access == "list" else values[0]
        except _MissingInput as exc:
            self.send(p.Error(nid, str(exc)))
            return

        result = run_component(
            spec,
            inputs,
            filename=f"<{nid} {spec.name}>",
            log=lambda line: self.send(p.Log(nid, line)),
            cwd=self.project_dir,
            print_port=PRINT_PORT,
        )
        if not result.ok:
            assert result.error is not None
            self.send(p.Error(nid, result.error))
            return

        summaries: dict[str, str] = {}
        for port, value in result.outputs.items():
            self.memory[keys[port]] = value
            summaries[port] = self.summaries[keys[port]] = types.describe(value)
        if self.disk is not None:
            try:
                self.disk.write(
                    msg.cache_key, result.outputs, summaries, protect=self.held_node_keys()
                )
            except Exception as exc:  # noqa: BLE001  (a failed cache write must not fail the run)
                self.send(p.Log(nid, f"cache: could not save the result ({exc})"))
            else:
                # A computed raster is now a COG on disk: read that from now on
                # instead of computing it again for every downstream node.
                try:
                    for port, value in self.disk.written_rasters(msg.cache_key).items():
                        self.memory[keys[port]] = value
                except Exception as exc:  # noqa: BLE001  (keep the computed value)
                    self.send(p.Log(nid, f"cache: could not reopen the result ({exc})"))
        self.send(p.Done(nid, self._described(keys), cached=False))

    def _described(self, keys: dict[str, str]) -> dict[str, dict[str, str]]:
        return {
            port: {"cache_key": key, "summary": self.summaries.get(key, "")}
            for port, key in keys.items()
        }


def worker_main(
    conn: Connection,
    project_dir: str | None,
    cache_dir: str | None,
    limit_bytes: int = DEFAULT_LIMIT,
) -> None:
    """Entry point of the worker process."""
    # First, before any component can import rasterio: ignore a system PROJ/GDAL.
    use_bundled_geo_data()
    # Stay in the project folder for the worker's whole life, not only while a
    # component's code runs: lazy rasters opened with a relative path ("data/x.tif")
    # reopen their file later (cache writes, the next node, after their handle was
    # released), and must find it again.
    if project_dir:
        os.chdir(project_dir)
    worker = Worker(
        conn.send,
        Path(project_dir) if project_dir else None,
        Path(cache_dir) if cache_dir else None,
        limit_bytes,
    )
    conn.send(p.Ready(os.getpid()))
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if isinstance(msg, p.Shutdown):
            return
        try:
            worker.handle(msg)
        except Exception:  # noqa: BLE001  (a bug here must not kill the worker)
            if isinstance(msg, p.RunNode):
                conn.send(p.Error(msg.node_id, traceback.format_exc().rstrip()))
