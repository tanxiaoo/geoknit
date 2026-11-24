"""A FastAPI TestClient on a temporary project folder."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geoknit.components.registry import default_registry
from geoknit.server.app import create_app


def make_client(project: Path, trust_file: Path) -> TestClient:
    app = create_app(
        project,
        registry=default_registry(project / "no-user-components", packs=False),
        trust_file=trust_file,
    )
    return TestClient(app)


@pytest.fixture
def trust_file(tmp_path: Path) -> Path:
    return tmp_path / "home" / "trusted.json"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "project"
    folder.mkdir()
    return folder


@pytest.fixture
def client(project: Path, trust_file: Path) -> Iterator[TestClient]:
    with make_client(project, trust_file) as c:
        yield c


def collect_until_finished(ws: object) -> list[dict]:
    """Every event up to and including ``run_finished``."""
    events = []
    while True:
        msg = ws.receive_json()  # type: ignore[attr-defined]
        events.append(msg)
        if msg["type"] == "run_finished":
            return events
