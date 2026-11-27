"""Every built-in component file parses and sits in the folder of its category."""

from pathlib import Path

import pytest

from geoknit.components.registry import BUILTIN_DIR
from geoknit.core.component import parse_component

FILES = sorted(p for p in BUILTIN_DIR.glob("*/*.py") if not p.name.startswith("_"))

EXPECTED = {
    "raster": {"read_raster", "write_raster", "reclassify", "clip", "align_raster", "band_select"},
    "vector": {"read_vector", "write_vector", "reproject"},
    "sampling": {"stratified_sample", "random_sample", "split_points", "extract_values"},
    "model": {"random_forest", "svm", "predict_raster"},
    "validation": {"regression_accuracy", "confusion_matrix"},
    "script": {"python"},
}


def test_all_spec_components_exist() -> None:
    found: dict[str, set[str]] = {}
    for p in FILES:
        found.setdefault(p.parent.name, set()).add(p.stem)
    assert found == EXPECTED


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_builtin_parses(path: Path) -> None:
    spec = parse_component(path.read_text(encoding="utf-8"))
    assert spec.category.lower() == path.parent.name
    assert spec.description
    assert spec.icon
    assert spec.outputs


def test_every_builtin_has_a_test() -> None:
    tests = "\n".join(
        p.read_text(encoding="utf-8") for p in Path(__file__).parent.glob("test_*.py")
    )
    untested = [
        f"{p.parent.name}/{p.stem}" for p in FILES if f'"{p.parent.name}/{p.stem}"' not in tests
    ]
    assert not untested
