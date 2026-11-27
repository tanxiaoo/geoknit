"""Ribbon tabs, groups and order (change 01, section 7).

The built-in components and the Params nodes are placed by
``builtin/_layout.yaml`` (tab → group → references). Pack and user
components follow their ``category:`` and ``group:`` headers: their groups
come after the built-in groups of the same tab in alphabetical order,
components alphabetical inside a group, and components without ``group:``
go to "Other", shown last. Tabs follow ``TABS``, then pack and user
categories alphabetically.

``library()`` builds the answer of ``GET /api/components``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from geoknit.components.registry import BUILTIN_DIR, Registry, input_view, output_view
from geoknit.core.graph import PARAM_MAP, PARAM_TITLES, PARAMS, param_ports

LAYOUT_FILE = BUILTIN_DIR / "_layout.yaml"

TABS: dict[str, str] = {
    "Params": "#475569",
    "Maths": "#475569",
    "Sets": "#475569",
    "Table": "#7C3AED",
    "Vector": "#C2410C",
    "Raster": "#0B7A7C",
    "Sampling": "#B45309",
    "Model": "#BE185D",
    "Validation": "#15803D",
    "Display": "#A21CAF",
    "Script": "#475569",
}
"""Built-in tabs in ribbon order, with their category colour (centre strip)."""

PACK_COLOUR = "#475569"
"""Colour of pack and user categories."""

OTHER = "Other"
"""Group of a pack or user component without ``group:``; shown last."""

PARAMS_TAB = "Params"

PARAM_ICONS: dict[str, str | None] = {PARAM_MAP: "map-viewer"}
"""Icons of the Params nodes (they have no header)."""

Layout = dict[str, dict[str, list[str]]]


class LayoutError(ValueError):
    """``_layout.yaml`` does not have the shape tab → group → list of references."""


def load_layout(path: Path = LAYOUT_FILE) -> Layout:
    """Read and shape-check a layout file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise LayoutError(f"{path.name}: expected tabs at the top level")
    layout: Layout = {}
    for tab, groups in raw.items():
        if not isinstance(groups, dict):
            raise LayoutError(f'{path.name}: tab "{tab}" must map group names to lists')
        layout[str(tab)] = {}
        for group, refs in groups.items():
            if not isinstance(refs, list) or not all(isinstance(r, str) for r in refs):
                raise LayoutError(f'{path.name}: group "{tab} › {group}" must be a list')
            layout[str(tab)][str(group)] = list(refs)
    return layout


def check_layout(layout: Layout, registry: Registry) -> list[str]:
    """Every problem with the layout: missing, twice, unknown, out of order, disagreeing headers."""
    problems: list[str] = []
    order = list(TABS)
    known = [t for t in layout if t in TABS]
    for tab in layout:
        if tab not in TABS:
            problems.append(f'unknown tab "{tab}" (tabs: {", ".join(order)})')
    if known != sorted(known, key=order.index):
        problems.append(f"tabs out of order: {', '.join(known)} (order: {', '.join(order)})")

    builtins = {ref for ref in registry.refs() if registry.item(ref).origin == "builtin"}
    seen: dict[str, str] = {}
    for tab, groups in layout.items():
        for group, refs in groups.items():
            for ref in refs:
                where = f"{tab} › {group}"
                if ref in seen:
                    problems.append(f"{ref} is listed twice ({seen[ref]} and {where})")
                    continue
                seen[ref] = where
                if ref in PARAMS:
                    if tab != PARAMS_TAB and ref != PARAM_MAP:
                        problems.append(f"{ref} is a Params node but is listed in {where}")
                    continue
                if ref not in builtins:
                    problems.append(f"{ref} is not a built-in component or Params node")
                    continue
                spec = registry.spec(ref)
                if spec.category != tab:
                    problems.append(f'{ref} has "category: {spec.category}" but is in {where}')
                if spec.group != group:
                    problems.append(f'{ref} has "group: {spec.group}" but is in {where}')
    for ref in sorted(builtins | set(PARAMS)):
        if ref not in seen:
            problems.append(f"{ref} is missing from the layout")
    return problems


def param_entry(kind: str) -> dict[str, Any]:
    """A Params node as ``GET /api/components`` lists it (category and group set by ``library``)."""
    inputs, outputs = param_ports(kind)
    return {
        "ref": kind,
        "version": "",
        "origin": "param",
        "name": PARAM_TITLES[kind],
        "category": PARAMS_TAB,
        "group": None,
        "icon": PARAM_ICONS.get(kind),
        "description": "",
        "inputs": [input_view(p) for p in inputs.values()],
        "outputs": [output_view(p) for p in outputs.values()],
        "requires": [],
        "settings": [],
        "editable_ports": None,
    }


def library(entries: list[dict[str, Any]], layout: Layout | None = None) -> dict[str, Any]:
    """``{components, tabs}`` in ribbon order, from registry ``entries`` plus the Params nodes.

    References listed in the layout take its tab and group (the layout test
    keeps their headers in agreement); every other entry keeps its
    ``category`` and gets its ``group`` or "Other".
    """
    layout = load_layout() if layout is None else layout
    places: dict[str, tuple[str, str, int]] = {}
    for tab, groups in layout.items():
        for group, refs in groups.items():
            for i, ref in enumerate(refs):
                places.setdefault(ref, (tab, group, i))

    items = [param_entry(kind) for kind in PARAMS] + [dict(e) for e in entries]
    for entry in items:
        place = places.get(entry["ref"])
        if place is not None:
            entry["category"], entry["group"] = place[0], place[1]
        else:
            entry["group"] = entry.get("group") or OTHER

    order = list(TABS)
    tab_names = {e["category"] for e in items}
    tabs = [t for t in order if t in tab_names] + sorted(tab_names - set(order), key=str.casefold)

    tab_groups: dict[str, list[str]] = {}
    for tab in tabs:
        found = {e["group"] for e in items if e["category"] == tab}
        fixed = [g for g in layout.get(tab, {}) if g in found]
        extra = found - set(fixed)
        rest = sorted(extra - {OTHER}, key=str.casefold)
        tab_groups[tab] = fixed + rest + ([OTHER] if OTHER in extra else [])

    def key(entry: dict[str, Any]) -> tuple[int, int, int, str, str]:
        tab = entry["category"]
        groups = tab_groups[tab]
        place = places.get(entry["ref"])
        position = place[2] if place is not None else len(places)
        return (
            tabs.index(tab),
            groups.index(entry["group"]),
            position,
            entry["name"].casefold(),
            entry["ref"],
        )

    items.sort(key=key)
    return {
        "components": items,
        "tabs": [
            {"name": t, "colour": TABS.get(t, PACK_COLOUR), "groups": tab_groups[t]} for t in tabs
        ],
    }
