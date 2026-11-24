"""Command-line entry point: ``geoknit`` and ``geoknit run file.geoknit``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geoknit import __version__


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the ``geoknit`` command."""
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return run_workflow(
            args.workflow,
            quiet=args.quiet,
            clear_cache=args.clear_cache,
            use_cache=not args.no_cache,
            cache_limit_gb=args.cache_limit,
        )
    parser.print_help()
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
