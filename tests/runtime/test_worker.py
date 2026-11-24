"""Worker process, cache hits and Stop (PLAN Phase 2 "Done when", SPEC 6)."""

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from geoknit.core.executor import Event
from geoknit.core.graph import INLINE, PARAM_PANEL, PARAM_TEXT, Graph
from geoknit.core.solver import DONE, ERROR, OUT_OF_DATE, RUN_TEST
from geoknit.runtime.client import STOPPED, WorkerExecutor
from tests.core.sources import LENGTH, REPEAT

COUNTED = """\
# geoknit: component
# name: Counted
# category: Text
# inputs:
#   text: Text
# outputs:
#   upper: Text

# --- code ---
with open("runs.log", "a") as f:
    f.write("x")
print("running")
upper = text.upper()
"""

SLEEPY = """\
# geoknit: component
# name: Sleepy
# category: Script
# outputs:
#   y: Number

# --- code ---
import time
print("going to sleep")
time.sleep(60)
y = 1
"""

CRASH = """\
# geoknit: component
# name: Crash
# category: Script
# outputs:
#   y: Number

# --- code ---
import os
os._exit(3)
"""


MakeExecutor = Callable[..., WorkerExecutor]


def _graph() -> tuple[Graph, dict[str, str]]:
    """Text → Counted → Repeat → Panel."""
    g = Graph()
    ids = {
        "text": g.add_component(PARAM_TEXT).id,
        "counted": g.add_component(INLINE, source=COUNTED).id,
        "repeat": g.add_component(INLINE, source=REPEAT).id,
        "panel": g.add_component(PARAM_PANEL).id,
    }
    g.set_value(ids["text"], "ab")
    g.add_wire(ids["text"], "value", ids["counted"], "text")
    g.add_wire(ids["counted"], "upper", ids["repeat"], "text")
    g.add_wire(ids["repeat"], "repeated", ids["panel"], "data")
    return g, ids


@pytest.fixture
def make_executor(tmp_path: Path) -> Iterator[MakeExecutor]:
    made: list[WorkerExecutor] = []

    def make(graph: Graph, **kw: object) -> WorkerExecutor:
        ex = WorkerExecutor(graph, base_dir=tmp_path, **kw)  # type: ignore[arg-type]
        made.append(ex)
        return ex

    yield make
    for ex in made:
        ex.close()


def _runs(tmp_path: Path) -> int:
    f = tmp_path / "runs.log"
    return len(f.read_text()) if f.exists() else 0


def test_run_gives_results_logs_and_panel_contents(
    make_executor: MakeExecutor, tmp_path: Path
) -> None:
    g, ids = _graph()
    events: list[Event] = []
    ex = make_executor(g, on_event=events.append)
    report = ex.run()
    assert report.ok, ex.errors
    assert ex.summaries[ids["panel"]]["data"] == "AB-AB"
    assert ex.logs[ids["counted"]] == ["running"]
    kinds = [(e.kind, e.node_id) for e in events if e.node_id == ids["counted"]]
    assert kinds == [("started", ids["counted"]), ("log", ids["counted"]), ("done", ids["counted"])]
    assert _runs(tmp_path) == 1


def test_second_run_executes_nothing(make_executor: MakeExecutor, tmp_path: Path) -> None:
    g, ids = _graph()
    ex = make_executor(g)
    ex.run()
    report = ex.run()
    assert report.ran == [] and report.cached == []
    assert all(ex.solver.states[n] == DONE for n in g.nodes)
    assert _runs(tmp_path) == 1


def test_changed_node_reruns_only_downstream(make_executor: MakeExecutor, tmp_path: Path) -> None:
    g, ids = _graph()
    ex = make_executor(g)
    ex.run()
    g.set_setting(ids["repeat"], "sep", "+")
    report = ex.run()
    assert report.ran == [ids["repeat"], ids["panel"]]
    assert ex.summaries[ids["panel"]]["data"] == "AB+AB"
    assert _runs(tmp_path) == 1


def test_edit_and_undo_comes_back_from_worker_memory(
    make_executor: MakeExecutor, tmp_path: Path
) -> None:
    g, ids = _graph()
    ex = make_executor(g, use_disk_cache=False)
    ex.run()
    g.set_value(ids["text"], "cd")
    ex.run()
    g.set_value(ids["text"], "ab")
    report = ex.run()
    assert report.cached == [ids["counted"], ids["repeat"]]
    assert _runs(tmp_path) == 2


def test_results_come_back_from_disk_after_worker_restart(
    make_executor: MakeExecutor, tmp_path: Path
) -> None:
    g, ids = _graph()
    first = make_executor(g)
    first.run()
    first.close()

    g2, ids2 = _graph()  # a fresh session on the same project
    second = make_executor(g2)
    report = second.run()
    assert report.cached == [ids2["counted"], ids2["repeat"]]
    assert not set(report.ran) & {ids2["counted"], ids2["repeat"]}
    assert second.summaries[ids2["panel"]]["data"] == "AB-AB"
    assert _runs(tmp_path) == 1
    assert (tmp_path / ".geoknit" / "cache").is_dir()

    second.restart()  # same session, new worker: memory gone, disk stays
    g2.set_setting(ids2["repeat"], "sep", "_")
    report = second.run()
    assert report.ran == [ids2["repeat"], ids2["panel"]]  # its input came from disk
    assert _runs(tmp_path) == 1


def test_stop_ends_a_long_run_within_two_seconds(make_executor: MakeExecutor) -> None:
    g = Graph()
    sleepy = g.add_component(INLINE, source=SLEEPY).id
    started = threading.Event()

    def on_event(e: Event) -> None:
        if e.kind == "log" and e.node_id == sleepy:
            started.set()  # the component code is really running

    ex = make_executor(g, on_event=on_event)
    result: dict[str, object] = {}
    thread = threading.Thread(target=lambda: result.update(report=ex.run()))
    thread.start()
    assert started.wait(60), "the component never started"
    t0 = time.monotonic()
    ex.stop()
    thread.join(10)
    elapsed = time.monotonic() - t0
    assert not thread.is_alive()
    assert elapsed < 2, f"stop took {elapsed:.2f} s"
    assert ex.solver.states[sleepy] == ERROR
    assert ex.errors[sleepy] == STOPPED

    # The next run works on the fresh worker.
    g.set_source(sleepy, LENGTH)
    text = g.add_component(PARAM_TEXT).id
    g.set_value(text, "abcd")
    g.add_wire(text, "value", sleepy, "text")
    report = ex.run()
    assert report.ok, ex.errors
    assert ex.summaries[sleepy]["n"] == "4"


def test_stop_when_idle_restarts_the_worker(make_executor: MakeExecutor) -> None:
    g, _ = _graph()
    ex = make_executor(g)
    ex.run()
    pid = ex.pid
    ex.stop()
    assert ex.pid != pid
    g2, _ = _graph()
    assert make_executor(g2).run().ok


def test_crashed_worker_is_reported_and_replaced(make_executor: MakeExecutor) -> None:
    g, ids = _graph()
    crash = g.add_component(INLINE, source=CRASH).id
    ex = make_executor(g)
    report = ex.run()
    assert report.failed == [crash]
    assert "stopped unexpectedly" in ex.errors[crash]
    assert ex.summaries[ids["panel"]]["data"] == "AB-AB"  # nodes before it are fine
    g.set_value(ids["text"], "xy")
    assert ex.run().failed == [crash]  # and the next run still works
    assert ex.summaries[ids["panel"]]["data"] == "XY-XY"


def test_test_mode_uses_cached_inputs_or_says_what_is_missing(make_executor: MakeExecutor) -> None:
    g, ids = _graph()
    ex = make_executor(g)
    report = ex.run(RUN_TEST, ids["repeat"])
    assert report.failed == [ids["repeat"]]
    assert ex.errors[ids["repeat"]] == 'input "text": no result yet; run it first'

    ex.run()
    g.set_setting(ids["repeat"], "sep", "+")
    assert ex.solver.states[ids["repeat"]] == OUT_OF_DATE
    report = ex.run(RUN_TEST, ids["repeat"])
    assert report.ran == [ids["repeat"]]
    assert ex.summaries[ids["repeat"]]["repeated"] == "AB+AB"


def test_component_error_and_skipped_downstream(make_executor: MakeExecutor) -> None:
    g, ids = _graph()
    g.set_source(ids["counted"], COUNTED.replace("upper = text.upper()", "upper = 1 / 0"))
    ex = make_executor(g)
    report = ex.run()
    assert report.failed == [ids["counted"]]
    assert "ZeroDivisionError" in ex.errors[ids["counted"]]
    assert "line 13" in ex.errors[ids["counted"]]
    assert report.skipped == [ids["repeat"], ids["panel"]]


def test_changed_input_file_is_rerun(make_executor: MakeExecutor, tmp_path: Path) -> None:
    from tests.core.sources import READ_FILE

    (tmp_path / "input.txt").write_text("one")
    g = Graph()
    reader = g.add_component(INLINE, source=READ_FILE).id
    ex = make_executor(g)
    ex.run()
    assert ex.summaries[reader]["text"] == "one"
    import os

    (tmp_path / "input.txt").write_text("three")
    st = (tmp_path / "input.txt").stat()
    os.utime(tmp_path / "input.txt", ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    report = ex.run()
    assert report.ran == [reader]
    assert ex.summaries[reader]["text"] == "three"
