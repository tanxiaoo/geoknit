"""Run one built-in component, as the worker would."""

from pathlib import Path
from typing import Any

from geoknit.components.registry import BUILTIN_DIR
from geoknit.core.component import (
    PRINT_PORT,
    ComponentSpec,
    RunResult,
    parse_component,
    run_component,
)
from geoknit.core.settings_edit import set_setting


def builtin_source(ref: str) -> str:
    """``"raster/reclassify"`` → the built-in component file text."""
    category, name = ref.split("/")
    return (BUILTIN_DIR / category / f"{name}.py").read_text(encoding="utf-8")


def builtin_spec(ref: str, **settings: Any) -> ComponentSpec:
    source = builtin_source(ref)
    for name, value in settings.items():
        source = set_setting(source, name, value)
    return parse_component(source)


def run_builtin(ref: str, cwd: Path | None = None, **values: Any) -> RunResult:
    """Run ``ref``; keyword arguments are wired inputs, or settings if not an input."""
    spec = builtin_spec(ref)
    settings = {k: v for k, v in values.items() if k not in spec.inputs}
    inputs = {k: v for k, v in values.items() if k in spec.inputs}
    if settings:
        spec = builtin_spec(ref, **settings)
    return run_component(spec, inputs, filename=f"<{ref}>", cwd=cwd, print_port=PRINT_PORT)


def ok(ref: str, cwd: Path | None = None, **values: Any) -> dict[str, Any]:
    """Outputs of a run that must succeed."""
    result = run_builtin(ref, cwd, **values)
    assert result.ok, result.error
    return result.outputs
