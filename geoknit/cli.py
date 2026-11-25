"""Command-line entry point: ``geoknit [folder]`` and ``geoknit run file.geoknit``."""

from __future__ import annotations

import argparse
import socket
import sys
from collections.abc import Sequence
from pathlib import Path

from geoknit import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the parser for ``geoknit run``-style commands."""
    parser = argparse.ArgumentParser(
        prog="geoknit",
        description="Local visual programming for geospatial analysis.",
    )
    parser.add_argument("--version", action="version", version=f"geoknit {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="run a workflow headless and print its Panels")
    run.add_argument("workflow", type=Path, help="a .geoknit file")
    run.add_argument("-q", "--quiet", action="store_true", help="do not print component output")
    run.add_argument(
        "--clear-cache", action="store_true", help="delete the disk cache before running"
    )
    run.add_argument("--no-cache", action="store_true", help="do not read or write the disk cache")
    run.add_argument(
        "--cache-limit",
        type=float,
        default=10.0,
        metavar="GB",
        help="disk cache size limit (default: 10)",
    )

    export = sub.add_parser("export", help="export a workflow to a standalone Python script")
    export.add_argument("workflow", type=Path, help="a .geoknit file")
    export.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="script to write (default: next to the workflow, with a .py suffix)",
    )
    return parser


def build_serve_parser() -> argparse.ArgumentParser:
    """Create the parser for ``geoknit [folder]``."""
    parser = argparse.ArgumentParser(
        prog="geoknit",
        description="Local visual programming for geospatial analysis. "
        "Starts GeoKnit on 127.0.0.1 and opens it in the browser.",
        epilog="geoknit run FILE.geoknit runs a workflow headless (see geoknit run --help); "
        "geoknit export FILE.geoknit writes it as a Python script.",
    )
    parser.add_argument("--version", action="version", version=f"geoknit {__version__}")
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=Path("."),
        help="project folder, or a .geoknit file to open (default: current folder)",
    )
    parser.add_argument("--port", type=int, default=None, help="port (default: a free one)")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] == "run":
        args = build_parser().parse_args(args_list)
        return run_workflow(
            args.workflow,
            quiet=args.quiet,
            clear_cache=args.clear_cache,
            use_cache=not args.no_cache,
            cache_limit_gb=args.cache_limit,
        )
    if args_list and args_list[0] == "export":
        args = build_parser().parse_args(args_list)
        return export_workflow(args.workflow, args.output)
    args = build_serve_parser().parse_args(args_list)
    return serve(args.folder, port=args.port, open_browser=not args.no_browser)


def find_free_port(host: str = "127.0.0.1") -> int:
    """A port that is free on ``host`` right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


HOST = "127.0.0.1"


def serve(target: Path, *, port: int | None = None, open_browser: bool = True) -> int:
    """``geoknit [folder]``: start the server on 127.0.0.1 and open the browser."""
    target = Path(target)
    workflow: Path | None = None
    if target.is_file():
        if target.suffix.lower() != ".geoknit":
            print(f"geoknit: {target} is not a folder or a .geoknit file", file=sys.stderr)
            return 2
        project, workflow = target.resolve().parent, target.resolve()
    elif target.is_dir():
        project = target.resolve()
    else:
        print(f"geoknit: {target} does not exist", file=sys.stderr)
        return 2

    import webbrowser

    import uvicorn

    from geoknit.server.app import create_app

    port = port or find_free_port(HOST)
    url = f"http://{HOST}:{port}/"

    def on_ready() -> None:
        print(f"GeoKnit {__version__} at {url} (Ctrl+C to quit)", file=sys.stderr)
        if open_browser:
            webbrowser.open(url)

    app = create_app(project, workflow=workflow, on_ready=on_ready)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0


def _safe_stream(stream: object) -> None:
    """Never crash on characters the console cannot show (Windows code pages)."""
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(errors="replace")


def run_workflow(
    path: Path,
    *,
    quiet: bool = False,
    clear_cache: bool = False,
    use_cache: bool = True,
    cache_limit_gb: float = 10.0,
) -> int:
    """``geoknit run``: 0 when every node succeeded, 1 otherwise, 130 on Ctrl+C."""
    from geoknit.components.registry import default_registry
    from geoknit.core.cache import DiskCache
    from geoknit.core.executor import Event
    from geoknit.core.graph import PARAM_PANEL
    from geoknit.core.workflow import WorkflowError, load_workflow
    from geoknit.runtime.client import WorkerExecutor

    out, err = sys.stdout, sys.stderr
    _safe_stream(out)
    _safe_stream(err)
    path = Path(path)
    try:
        graph = load_workflow(path, default_registry())
    except (OSError, WorkflowError) as exc:
        print(f"geoknit: cannot open {path}: {exc}", file=err)
        return 1
    project = path.resolve().parent
    cache_dir = project / ".geoknit" / "cache"
    if clear_cache:
        DiskCache(cache_dir).clear()

    def on_event(e: Event) -> None:
        title = graph.nodes[e.node_id].title if e.node_id in graph.nodes else e.node_id
        if e.kind == "log" and not quiet:
            print(f"[{e.node_id} {title}] {e.data['line']}", file=err)
        elif e.kind == "error":
            print(f"[{e.node_id} {title}] error:\n{e.data['traceback']}", file=err)

    ex = WorkerExecutor(
        graph,
        base_dir=project,
        cache_dir=cache_dir,
        cache_limit=int(cache_limit_gb * 1024**3),
        use_disk_cache=use_cache,
        on_event=on_event,
    )
    try:
        report = ex.run()
    except KeyboardInterrupt:
        print("geoknit: stopped", file=err)
        return 130
    finally:
        ex.close()

    for nid, node in graph.nodes.items():
        if node.component != PARAM_PANEL:
            continue
        print(f"--- Panel {nid} ---", file=out)
        if nid in ex.errors:
            print(f"({ex.errors[nid]})", file=out)
        elif not graph.wires_into(nid):
            print("(empty)", file=out)
        else:
            print(ex.summaries.get(nid, {}).get("data", ""), file=out)

    ran = [n for n in report.ran if not graph.nodes[n].is_param]  # components only
    print(
        f"geoknit: {len(ran)} ran · {len(report.cached)} from cache · "
        f"{len(report.failed)} failed · {len(report.skipped)} skipped",
        file=err,
    )
    return 0 if report.ok else 1


def export_workflow(path: Path, output: Path | None = None) -> int:
    """``geoknit export``: write the workflow as a script (SPEC 10). 0 on success, 1 otherwise."""
    from geoknit.components.registry import default_registry
    from geoknit.core.export import ExportError, export_script
    from geoknit.core.workflow import WorkflowError, load_workflow

    _safe_stream(sys.stderr)
    path = Path(path)
    try:
        graph = load_workflow(path, default_registry())
    except (OSError, WorkflowError) as exc:
        print(f"geoknit: cannot open {path}: {exc}", file=sys.stderr)
        return 1
    try:
        result = export_script(graph, workflow_name=path.name, base_dir=path.resolve().parent)
    except ExportError as exc:
        print(f"geoknit: cannot export {path.name}: {exc}", file=sys.stderr)
        return 1
    target = Path(output) if output is not None else path.with_suffix(".py")
    try:
        target.write_text(result.script, encoding="utf-8", newline="\n")
    except OSError as exc:
        print(f"geoknit: cannot write {target}: {exc.strerror or exc}", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"geoknit: warning: {warning}", file=sys.stderr)
    print(f"geoknit: wrote {target}", file=sys.stderr)
    return 0
