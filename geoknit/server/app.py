"""FastAPI app: REST routes and the ``/ws`` event stream (SPEC 9).

Every UI action goes through these routes, so an agent can drive GeoKnit the
same way the canvas does. The server binds to 127.0.0.1 only (see
``geoknit.cli``) and never imports the geo stack; components run in the worker.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from geoknit import __version__
from geoknit.components.registry import Registry
from geoknit.core.graph import GraphError
from geoknit.core.trust import TrustStore
from geoknit.core.workflow import WorkflowError
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
    component: str = Field(description="library reference, `inline`, or `param/text|slider|panel`")
    position: list[float] = Field(default_factory=lambda: [0.0, 0.0])
    source: str | None = Field(default=None, description="full component file, for `inline`")


class NodePatch(BaseModel):
    """Only the fields that are sent are changed."""

    settings: dict[str, Any] | None = None
    source: str | None = None
    position: list[float] | None = None
    display: Literal["default", "text", "icon"] | None = None
    value: Any = None
    min: float | None = None
    max: float | None = None
    step: float | None = None


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

    # ── library and graph ──
    @app.get("/api/components", tags=["library"])
    def components() -> list[dict[str, Any]]:
        """Header metadata of every component, for the ribbon."""
        return session.components()

    @app.get("/api/graph", tags=["graph"])
    def graph() -> dict[str, Any]:
        """The current workflow, with per-node state, ports and settings."""
        return session.graph_view()

    @app.post("/api/nodes", status_code=201, tags=["graph"])
    def add_node(body: NodeCreate) -> dict[str, Any]:
        return session.add_node(body.component, body.position, body.source)

    @app.patch("/api/nodes/{node_id}", tags=["graph"])
    def patch_node(node_id: str, body: NodePatch) -> dict[str, Any]:
        """Change settings, source, position, display, value or slider limits."""
        changes = {k: getattr(body, k) for k in body.model_fields_set}
        return session.patch_node(node_id, changes)

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

    @app.post("/api/export/py", status_code=501, tags=["files"])
    def export_py() -> dict[str, Any]:
        """Export to a Python script (SPEC 10): arrives in a later version."""
        return {"detail": "export to Python arrives in a later version"}

    # ── events ──
    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        """Events: ``states``, ``started``, ``log``, ``done``, ``error``, ``skipped``,
        ``run_finished``, ``workflow_opened``."""
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
