"""Messages between the server (or CLI) and the worker process (SPEC 6 "Worker protocol").

Plain frozen dataclasses, pickled over a ``multiprocessing`` Pipe created with
the spawn start method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── server → worker ──


@dataclass(frozen=True)
class RunNode:
    """Run one component, or answer from memory / the disk cache if ``cache_key`` is known.

    ``inputs`` maps each wired input to the port key feeding it, or to a list of
    port keys (wire order) for a ``list`` input. Settings are part of ``source``.
    ``output_types`` holds the types the graph resolved for ``like:`` outputs
    (the worker does not know the graph); the outputs are checked against them.
    """

    node_id: str
    source: str
    inputs: dict[str, str | list[str]]
    cache_key: str
    output_types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PutValue:
    """Make a Text / Slider value (or an empty Panel's ``None``) available under a key."""

    cache_key: str
    value: Any


@dataclass(frozen=True)
class ClearCache:
    """Delete the disk cache ("Clear cache")."""


@dataclass(frozen=True)
class Shutdown:
    """Exit the worker loop."""


# ── worker → server ──


@dataclass(frozen=True)
class Ready:
    pid: int


@dataclass(frozen=True)
class Started:
    node_id: str


@dataclass(frozen=True)
class Log:
    node_id: str
    line: str


@dataclass(frozen=True)
class Done:
    """``outputs`` maps each port to ``{"cache_key": ..., "summary": ...}``."""

    node_id: str
    outputs: dict[str, dict[str, str]] = field(default_factory=dict)
    cached: bool = False


@dataclass(frozen=True)
class Error:
    node_id: str
    traceback: str


@dataclass(frozen=True)
class Cleared:
    """Reply to ``ClearCache``; ``complete`` is false if some files were locked."""

    complete: bool


ToWorker = RunNode | PutValue | ClearCache | Shutdown
FromWorker = Ready | Started | Log | Done | Error | Cleared
