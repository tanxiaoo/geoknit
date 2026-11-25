"""Hatch build hook: a wheel must contain the built frontend (SPEC 12).

Users never need Node, so ``geoknit/server/static/`` (made by
``cd frontend && npm run build``) has to be inside every wheel. Without it the
server only shows a placeholder page, so building a regular wheel without it
fails here instead of producing a package that looks fine but has no canvas.
Editable installs (``pip install -e .``) are not checked: developers run the
Vite dev server or build the frontend themselves.

Set ``GEOKNIT_ALLOW_NO_FRONTEND=1`` to build a backend-only wheel anyway.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

STATIC = Path("geoknit") / "server" / "static"


class FrontendCheck(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        if os.environ.get("GEOKNIT_ALLOW_NO_FRONTEND") == "1":
            return
        index = Path(self.root) / STATIC / "index.html"
        if not index.is_file():
            raise RuntimeError(
                f"{index} is missing: build the frontend first "
                "(cd frontend && npm ci && npm run build), "
                "or set GEOKNIT_ALLOW_NO_FRONTEND=1 for a wheel without the canvas"
            )
