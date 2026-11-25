"""FastAPI app: REST routes and the ``/ws`` event stream (SPEC 9).

Every UI action goes through these routes, so an agent can drive GeoKnit the
same way the canvas does. The server binds to 127.0.0.1 only (see
``geoknit.cli``). Components run in the worker; the server imports the geo
stack only to serve the Map Viewer (``tiles.py``).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from geoknit import __version__
from geoknit.components.registry import Registry
from geoknit.core.cache import CacheMiss
from geoknit.core.graph import GraphError
from geoknit.core.trust import TrustStore
from geoknit.core.workflow import WorkflowError
from geoknit.server import tiles
from geoknit.server.files import file_tree
from geoknit.server.session import Session, SessionError

STATIC_DIR = Path(__file__).parent / "static"

PLACEHOLDER = """<!doctype html>
<html><head><meta charset="utf-8"><title>GeoKnit</title></head>
<body style="font-family: system-ui, sans-serif; margin: 3rem">
<h1>GeoKnit</h1>
<p>The server is running, but the canvas has not been built yet
(<code>cd frontend &amp;&amp; npm run build</code>).</p>
<p>The API is at <a href="/docs">/docs</a>.</p>
</body></html>
"""


# ── request bodies ──


class NodeCreate(BaseModel):
    component: str = Field(
        description="library reference, `inline`, or `param/text|slider|panel|map`"
    )
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    source: str | None = Field(default=None, description="full component file, for `inline`")


class PortBody(BaseModel):
    name: str
    type: str = Field(description="Number, Text, Raster, Vector, Table, Model or Any")
    access: Literal["item", "list"] = "item"
    file: Literal["write"] | None = None
    was: str | None = Field(default=None, description="old name, when renaming (wires follow)")


class PortsBody(BaseModel):
    inputs: list[PortBody] = Field(default_factory=list)
    outputs: list[PortBody] = Field(default_factory=list)


class NodePatch(BaseModel):
    """Only the fields that are sent are changed."""

    settings: dict[str, Any] | None = None
    source: str | None = None
    ports: PortsBody | None = Field(
        default=None, description="rewrite the header's inputs and outputs (Python component)"
    )
    position: list[float] | None = None
    display: Literal["default", "text", "icon"] | None = None
    value: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    size: list[float] | None = Field(default=None, description="Panel [width, height]")
    map: dict[str, Any] | None = Field(
        default=None,
        description="Map Viewer: `{basemap?, styles?: {layer id: style | null}}`, merged",
    )


class ViewBody(BaseModel):
    """Only the fields that are sent are changed."""

    display: Literal["text", "icon"] | None = None
    zoom: float | None = None
    offset: list[float] | None = None


class WireBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    src: tuple[str, str] = Field(alias="from", description="[node id, output port]")
    dst: tuple[str, str] = Field(alias="to", description="[node id, input port]")


class RunBody(BaseModel):
    mode: Literal["all", "to_node", "test"] = "all"
    node_id: str | None = None


class SaveBody(BaseModel):
    path: str | None = Field(default=None, description="relative to the project folder")


class OpenBody(BaseModel):
    path: str = Field(description="relative to the project folder")


class DeleteBody(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    wires: list[WireBody] = Field(default_factory=list)


class MoveBody(BaseModel):
    positions: dict[str, list[float]] = Field(description="node id → [x, y]")


class PasteBody(BaseModel):
    nodes: list[dict[str, Any]] = Field(description="nodes in workflow format (SPEC 5)")
    wires: list[dict[str, Any]] = Field(
        default_factory=list, description="wires among the pasted nodes, by their old ids"
    )
    offset: list[float] = Field(default_factory=lambda: [20.0, 20.0])


class GroupCreate(BaseModel):
    title: str = "Group"
    nodes: list[str]


class GroupPatch(BaseModel):
    title: str | None = None
    nodes: list[str] | None = None


class SaveComponentBody(BaseModel):
    overwrite: bool = False


class ExportBody(BaseModel):
    path: str | None = Field(
        default=None, description="write the script here, relative to the project folder"
    )
    overwrite: bool = False


class RecoverBody(BaseModel):
    restore: bool = Field(description="true restores the autosave, false discards it")


# ── app ──


def create_app(
    project: Path,
    *,
    registry: Registry | None = None,
    trust_file: Path | None = None,
    workflow: Path | None = None,
    on_ready: Callable[[], None] | None = None,
) -> FastAPI:
    """The GeoKnit app for one project folder; the worker starts with the app."""
    session = Session(
        project,
        registry=registry,
        trust=TrustStore(trust_file) if trust_file is not None else None,
        workflow=workflow,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(session.start)
        if on_ready is not None:
            on_ready()
        try:
            yield
        finally:
            await asyncio.to_thread(session.close)

    app = FastAPI(title="GeoKnit", version=__version__, lifespan=lifespan)
    app.state.session = session

    @app.exception_handler(SessionError)
    async def _session_error(request: Request, exc: SessionError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(GraphError)
    async def _graph_error(request: Request, exc: GraphError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(WorkflowError)
    async def _workflow_error(request: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(tiles.MapError)
    async def _map_error(request: Request, exc: tiles.MapError) -> JSONResponse:
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(CacheMiss)
    async def _cache_miss(request: Request, exc: CacheMiss) -> JSONResponse:
        return JSONResponse({"detail": "not in the cache; run first"}, status_code=404)

    # ── library and graph ──
    @app.get("/api/components", tags=["library"])
    def components() -> list[dict[str, Any]]:
        """Header metadata of every component, for the ribbon."""
        return session.components()

    @app.get("/api/graph", tags=["graph"])
    def graph() -> dict[str, Any]:
        """The current workflow, with per-node state, ports and settings."""
        return session.graph_view()

    @app.get("/api/status", tags=["run"])
    def status() -> dict[str, Any]:
        """Python version and worker state (idle | running)."""
        return session.status()

    @app.patch("/api/view", tags=["graph"])
    def view(body: ViewBody) -> dict[str, Any]:
        """Canvas view saved with the workflow: Show as Text | Icon, zoom, offset."""
        return session.set_view({k: getattr(body, k) for k in body.model_fields_set})

    @app.post("/api/nodes", status_code=201, tags=["graph"])
    def add_node(body: NodeCreate) -> dict[str, Any]:
        return session.add_node(body.component, body.position, body.source)

    @app.patch("/api/nodes/{node_id}", tags=["graph"])
    def patch_node(node_id: str, body: NodePatch) -> dict[str, Any]:
        """Change settings, source, position, display, value or slider limits."""
        changes = {k: getattr(body, k) for k in body.model_fields_set}
        if body.ports is not None:
            changes["ports"] = body.ports.model_dump(exclude_none=True)
        return session.patch_node(node_id, changes)

    @app.post("/api/nodes/{node_id}/save_component", tags=["graph"])
    def save_component(node_id: str, body: SaveComponentBody) -> dict[str, Any]:
        """Save as component…: write the node's file to the user component folder.

        The file is ``<category>/<name>.py`` from its header; it appears in the
        ribbon as ``user/<category>/<name>``. An existing file answers 409
        unless ``overwrite`` is true.
        """
        return session.save_component(node_id, body.overwrite)

    @app.post("/api/nodes/{node_id}/vscode", tags=["graph"])
    def open_in_vscode(node_id: str) -> dict[str, Any]:
        """Open in VS Code: write a temp file, start the editor, apply its saves."""
        return session.open_in_editor(node_id)

    @app.delete("/api/nodes/{node_id}", status_code=204, tags=["graph"])
    def remove_node(node_id: str) -> None:
        session.remove_node(node_id)

    @app.post("/api/wires", status_code=201, tags=["graph"])
    def add_wire(body: WireBody) -> dict[str, Any]:
        """Connect an output to an input (type, access and cycle checks)."""
        session.add_wire(*body.src, *body.dst)
        return {"from": list(body.src), "to": list(body.dst)}

    @app.delete("/api/wires", status_code=204, tags=["graph"])
    def remove_wire(body: WireBody) -> None:
        session.remove_wire(*body.src, *body.dst)

    @app.post("/api/delete", status_code=204, tags=["graph"])
    def delete(body: DeleteBody) -> None:
        """Remove several nodes and wires as one undo step."""
        session.delete(body.nodes, [(*w.src, *w.dst) for w in body.wires])

    @app.patch("/api/positions", tags=["graph"])
    def move(body: MoveBody) -> dict[str, Any]:
        """Move several nodes as one undo step (allowed during a run)."""
        session.move(body.positions)
        return {"moved": len(body.positions)}

    @app.post("/api/paste", status_code=201, tags=["graph"])
    def paste(body: PasteBody) -> dict[str, Any]:
        """Add copies of nodes (from `GET /api/graph`) under new ids, with their wires."""
        return {"ids": session.paste(body.nodes, body.wires, body.offset)}

    @app.post("/api/undo", tags=["graph"])
    def undo() -> dict[str, Any]:
        """Undo the last workflow edit (Ctrl+Z)."""
        session.undo()
        return session.graph_view()

    @app.post("/api/redo", tags=["graph"])
    def redo() -> dict[str, Any]:
        """Redo the last undone edit (Ctrl+Y)."""
        session.redo()
        return session.graph_view()

    @app.post("/api/groups", status_code=201, tags=["graph"])
    def add_group(body: GroupCreate) -> dict[str, Any]:
        """Put nodes in a labelled box (Ctrl+G)."""
        return {"index": session.add_group(body.title, body.nodes)}

    @app.patch("/api/groups/{index}", tags=["graph"])
    def patch_group(index: int, body: GroupPatch) -> dict[str, Any]:
        """Rename a group or change its nodes."""
        return session.patch_group(index, body.title, body.nodes)

    @app.delete("/api/groups/{index}", status_code=204, tags=["graph"])
    def remove_group(index: int) -> None:
        """Ungroup; the nodes stay."""
        session.remove_group(index)

    # ── running ──
    @app.post("/api/run", status_code=202, tags=["run"])
    def run(body: RunBody) -> dict[str, Any]:
        """Start a run in the background; progress arrives on ``/ws``."""
        return {"plan": session.run(body.mode, body.node_id)}

    @app.post("/api/stop", tags=["run"])
    def stop() -> dict[str, Any]:
        session.stop()
        return {"stopped": True}

    @app.post("/api/cache/clear", tags=["run"])
    def clear_cache() -> dict[str, Any]:
        """Empty worker memory and the disk cache; every node becomes out of date."""
        return {"complete": session.clear_cache()}

    @app.get("/api/nodes/{node_id}/output", tags=["run"])
    def output(node_id: str) -> dict[str, Any]:
        """Output log, error and per-port summaries of one node."""
        return session.output(node_id)

    # ── files ──
    @app.get("/api/files", tags=["files"])
    def files() -> dict[str, Any]:
        """The project folder tree (``.geoknit/`` hidden)."""
        return file_tree(session.project)

    @app.post("/api/workflow/save", tags=["files"])
    def save(body: SaveBody) -> dict[str, Any]:
        return {"path": session.save(body.path)}

    @app.post("/api/workflow/open", tags=["files"])
    def open_workflow(body: OpenBody) -> dict[str, Any]:
        """Open a workflow; one not saved on this machine opens read-only (SPEC 11)."""
        return session.open(body.path)

    @app.post("/api/workflow/trust", tags=["files"])
    def trust() -> dict[str, Any]:
        """Answer "Trust and allow running?" with yes for the open workflow."""
        session.trust_current()
        return {"trusted": True}

    @app.post("/api/workflow/recover", tags=["files"])
    def recover(body: RecoverBody) -> dict[str, Any]:
        """Restore (one undo step) or discard the autosave offered after opening."""
        session.recover(body.restore)
        return session.graph_view()

    @app.post("/api/export/py", tags=["files"])
    def export_py(body: ExportBody | None = None) -> dict[str, Any]:
        """Export to a Python script that runs without GeoKnit (SPEC 10).

        Returns ``{script, path, warnings}``. With ``path`` the script is also
        written into the project; an existing file answers 409 unless
        ``overwrite`` is true.
        """
        body = body or ExportBody()
        return session.export_py(body.path, body.overwrite)

    # ── Map Viewer (SPEC 8) ──
    def _bands(text: str | None) -> tuple[int, ...] | None:
        if text is None or text == "":
            return None
        try:
            return tuple(int(b) for b in text.split(","))
        except ValueError:
            raise tiles.MapError("bands is a comma-separated list of band numbers") from None

    @app.get("/api/map/{node_id}", tags=["map"])
    def map_view(node_id: str) -> dict[str, Any]:
        """Layers of a Map Viewer (one per wire): status, bounds, bands, stats, style."""
        return session.map_view(node_id)

    @app.get("/api/map/{node_id}/inspect", tags=["map"])
    def map_inspect(node_id: str, lon: float, lat: float) -> dict[str, Any]:
        """Band values of every raster layer at a clicked point (EPSG:4326)."""
        return session.map_inspect(node_id, lon, lat)

    @app.get("/api/raster/{key}/stats", tags=["map"])
    def raster_stats(key: str, bands: str = "1") -> dict[str, Any]:
        """2–98 % stretch of the given bands, and classes for a small-integer band."""
        return tiles.raster_stats(session.map_cache(), key, _bands(bands) or (1,))

    @app.get("/tiles/{key}/{z}/{x}/{y}.png", tags=["map"])
    def tile(
        key: str,
        z: int,
        x: int,
        y: int,
        bands: str | None = None,
        colormap: str = "viridis",
        min: float | None = Query(default=None),  # noqa: A002  (query names of the API)
        max: float | None = Query(default=None),  # noqa: A002
    ) -> Response:
        """A 256 px Web Mercator tile of a cached raster (rio-tiler, from overviews)."""
        png = tiles.render_tile(
            session.map_cache(),
            key,
            z,
            x,
            y,
            bands=_bands(bands) or (1,),
            colormap=colormap,
            vmin=min,
            vmax=max,
        )
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get("/api/vector/{key}.geojson", tags=["map"])
    def vector(key: str) -> Response:
        """A cached vector in EPSG:4326, at most 50 000 features.

        ``X-GeoKnit-Features`` gives the total, so the viewer can say when
        it shows only part of the layer.
        """
        text, total = tiles.vector_geojson(session.map_cache(), key)
        return Response(
            text,
            media_type="application/geo+json",
            headers={"X-GeoKnit-Features": str(total)},
        )

    # ── events ──
    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        """Events: ``states``, ``started``, ``log``, ``done``, ``error``, ``skipped``,
        ``run_finished``, ``workflow_opened``, ``worker``, ``node_changed``."""
        await websocket.accept()
        sub = session.events.subscribe()
        await websocket.send_json(session.states_message())

        async def pump() -> None:
            while True:
                await websocket.send_json(await sub.queue.get())

        async def listen() -> None:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    return

        tasks = {asyncio.create_task(pump()), asyncio.create_task(listen())}
        try:
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
        except WebSocketDisconnect:
            pass
        finally:
            for t in tasks:
                t.cancel()
            session.events.unsubscribe(sub)

    # ── frontend ──
    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:

        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(PLACEHOLDER)

    return app
