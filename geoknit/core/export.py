"""Export a workflow to one Python script that runs without GeoKnit (SPEC 10).

- Text and Number Slider values become constants at the top.
- Each component becomes a function ``n07_reclassify(raster, breaks)`` whose
  body is the component's settings block and code, returning its outputs.
- ``main()`` calls the functions in topological order and prints each Panel
  the way ``geoknit run`` does.
- ``geoknit.helpers`` (and ``geoknit.core.types``, which the helpers and
  ``ModelBundle`` need) is vendored into the script when it is used.
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from geoknit import __version__
from geoknit.core import types
from geoknit.core.component import INPUTS_NAME, PRINT_PORT, ComponentSpec
from geoknit.core.graph import (
    LAYER_STYLE_INPUTS,
    PARAM_COLOR,
    PARAM_COLORMAP,
    PARAM_LAYER,
    PARAM_MAP,
    PARAM_NUMBER,
    PARAM_PANEL,
    PARAM_SLIDER,
    PARAM_TEXT,
    PARAM_TOGGLE,
    PARAM_VALUE_LIST,
    VALUE_PARAMS,
    Graph,
    GraphError,
    Node,
    param_output,
)
from geoknit.core.layers import layer_name
from geoknit.core.workflow import relativize

INDENT = "    "
LINE_LENGTH = 99

VENDOR_FILES: dict[str, str] = {
    "geoknit.core.types": "core/types.py",
    "geoknit.helpers.breaks": "helpers/breaks.py",
    "geoknit.helpers.raster": "helpers/raster.py",
    "geoknit.helpers.sampling": "helpers/sampling.py",
    "geoknit.helpers.model": "helpers/model.py",
}
"""Modules copied into the script, in dependency order."""

HELPER_MODULES = ("geoknit.helpers", *[m for m in VENDOR_FILES if m.startswith("geoknit.helpers")])
TYPES_MODULE = "geoknit.core.types"

PACKAGE_DIR = Path(__file__).resolve().parents[1]


class ExportError(ValueError):
    """The workflow cannot be exported; the message names the node."""


@dataclass
class ExportResult:
    script: str
    warnings: list[str] = field(default_factory=list)


# ── names ──


def slug(text: str) -> str:
    """``Read Raster`` → ``read_raster``."""
    s = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return s or "node"


def _id_names(ids: list[str]) -> dict[str, str]:
    """``n7`` → ``n07``: ids padded to the widest one (at least 2 digits)."""
    numbered = [re.fullmatch(r"n(\d+)", i) for i in ids]
    width = max([2] + [len(m.group(1)) for m in numbered if m])
    out: dict[str, str] = {}
    for i, m in zip(ids, numbered, strict=True):
        out[i] = f"n{int(m.group(1)):0{width}d}" if m else f"n_{slug(i)}"
    return out


# ── source rewriting ──


def _lines(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _string_continuations(text: str) -> set[int]:
    """1-based lines that continue a multi-line string (they must not be indented)."""
    inside: set[int] = set()
    kinds = {tokenize.STRING}
    if hasattr(tokenize, "FSTRING_MIDDLE"):  # Python 3.12+
        kinds.add(tokenize.FSTRING_MIDDLE)
    with contextlib.suppress(tokenize.TokenError, SyntaxError):
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in kinds and tok.end[0] > tok.start[0]:
                inside.update(range(tok.start[0] + 1, tok.end[0] + 1))
    return inside


def indent(text: str, prefix: str = INDENT) -> str:
    """Indent ``text`` without changing the value of any string literal."""
    keep = _string_continuations(text)
    out = []
    for n, line in enumerate(_lines(text), start=1):
        out.append(line if n in keep or not line.strip() else prefix + line)
    return "".join(out)


def _comment_out_settings(settings: list[str], wired: set[str], node_label: str) -> list[str]:
    """Comment out the assignments of settings whose input is wired."""
    lines = list(settings)
    try:
        tree = ast.parse("".join(lines))
    except SyntaxError:  # pragma: no cover  (parse_component already checked it)
        return lines
    for stmt in tree.body:
        if not (isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name)):
            continue
        if stmt.targets[0].id not in wired:
            continue
        first, last = stmt.lineno - 1, (stmt.end_lineno or stmt.lineno) - 1
        for i in range(first, last + 1):
            lines[i] = "# " + lines[i]
        lines[first] = lines[first].rstrip("\n") + f"  # ← wired input ({node_label})\n"
    return lines


@dataclass
class _Imports:
    vendored: set[str] = field(default_factory=set)
    """Vendored modules the code imports from."""
    other: list[str] = field(default_factory=list)
    """Other ``geoknit`` modules it imports (the script then still needs GeoKnit)."""


def _is_geoknit(module: str | None) -> bool:
    return module is not None and (module == "geoknit" or module.startswith("geoknit."))


def _rewrite_imports(code: str, where: str) -> tuple[str, _Imports]:
    """Replace ``from geoknit.helpers import …`` with the vendored names."""
    found = _Imports()
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ExportError(f"{where}: the code has a syntax error: {exc.msg}") from None
    lines = _lines(code)
    edits: list[tuple[int, int, list[str]]] = []
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if _is_geoknit(alias.name):
                    found.other.append(alias.name)
            continue
        if not isinstance(stmt, ast.ImportFrom) or not _is_geoknit(stmt.module):
            continue
        module = stmt.module or ""
        first, last = stmt.lineno - 1, (stmt.end_lineno or stmt.lineno) - 1
        head = lines[first][: stmt.col_offset]
        tail = lines[last][stmt.end_col_offset or 0 :].strip()
        alone = not head.strip() and (not tail or tail.startswith("#"))
        if stmt.level or (module not in HELPER_MODULES and module != TYPES_MODULE) or not alone:
            found.other.append(module)
            continue
        found.vendored.add(module)
        original = ast.get_source_segment(code, stmt) or f"from {module} import …"
        original = " ".join(original.split())
        new = [f"{head}# {original}  (vendored above)\n"]
        renames = [a for a in stmt.names if a.asname and a.asname != a.name]
        new += [f"{head}{a.asname} = {a.name}\n" for a in renames]
        if not renames and stmt.col_offset > 0:
            new.append(f"{head}pass\n")  # keep an indented block non-empty
        edits.append((first, last, new))
    for first, last, new in sorted(edits, reverse=True):
        lines[first : last + 1] = new
    return "".join(lines), found


def _uses_name(code: str, name: str) -> bool:
    """Whether the code reads the variable ``name``."""
    with contextlib.suppress(SyntaxError):
        return any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(ast.parse(code)))
    return False


def _vendor_source(module: str) -> tuple[str, set[str]]:
    """A vendored module without its docstring, ``__all__`` and geoknit imports."""
    path = PACKAGE_DIR / VENDOR_FILES[module]
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = _lines(source)
    drop: set[int] = set()
    names: set[str] = set()
    for i, stmt in enumerate(tree.body):
        first, last = stmt.lineno - 1, (stmt.end_lineno or stmt.lineno) - 1
        is_doc = i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        is_future = isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
        is_internal = isinstance(stmt, ast.ImportFrom) and _is_geoknit(stmt.module)
        is_all = isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets
        )
        if is_doc or is_future or is_internal or is_all:
            drop.update(range(first, last + 1))
            continue
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            names.update(t.id for t in stmt.targets if isinstance(t, ast.Name))
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    kept = "".join(line for n, line in enumerate(lines) if n not in drop)
    return re.sub(r"\n{3,}", "\n\n\n", kept).strip("\n") + "\n", names


def vendored_section(modules: list[str]) -> str:
    """Flattened source of ``modules``; refuses clashing top-level names."""
    seen: dict[str, str] = {}
    parts: list[str] = []
    for module in modules:
        text, names = _vendor_source(module)
        for name in names:
            if name in seen:
                raise RuntimeError(f"{name} is defined in both {seen[name]} and {module}")
            seen[name] = module
        parts.append(f"# ── {module} (geoknit/{VENDOR_FILES[module]}) ──\n\n{text}")
    return "\n\n".join(parts)


# ── the export ──


@dataclass
class _Function:
    node: Node
    name: str
    params: list[str]
    outputs: list[str]
    source: str
    imports: _Imports


class _Exporter:
    def __init__(self, graph: Graph, base_dir: Path | None) -> None:
        self.graph = graph
        self.base_dir = base_dir
        self.order = graph.topological_order()
        self.names = _id_names(list(graph.nodes))
        self.exprs: dict[tuple[str, str], str] = {}
        self.out_types: dict[tuple[str, str], tuple[str, ...]] = {}
        """Resolved output types (``like:`` outputs follow the graph, SPEC 4)."""
        self.warnings: list[str] = []
        self.needs_as_text = False
        self.needs_capture = False
        self.needs_types = False
        """A constant is a Color or Colormap: the script needs the vendored types."""

    def label(self, node: Node) -> str:
        return f"{node.id} {node.title}"

    # ── inputs ──
    def wired_value(self, node: Node, port: str) -> str:
        """The argument for an input; a list input gets ``[*a, b, *c]`` in wire order
        (a list wire adds its elements, any other wire one element, SPEC 3)."""
        wires = self.graph.wires_into(node.id, port)
        in_types = node.inputs[port].types
        if node.inputs[port].access != "list":
            return self._convert(self.exprs[(wires[0].src, wires[0].src_port)], wires[0], in_types)
        values: list[str] = []
        for w in wires:
            expr = self.exprs[(w.src, w.src_port)]
            if self.graph.output_is_list(w.src, w.src_port):
                each = self._convert("_v", w, in_types)
                values.append(f"*{expr}" if each == "_v" else f"*[{each} for _v in {expr}]")
            else:
                values.append(self._convert(expr, w, in_types))
        return "[" + ", ".join(values) + "]"

    def _convert(self, expr: str, wire: Any, in_types: tuple[str, ...]) -> str:
        """Number/Boolean → Text wires get ``str()`` (SPEC 3), like ``convert_for_input``."""
        if types.TEXT not in in_types:
            return expr
        out_types = self.out_types[(wire.src, wire.src_port)]
        if types.ANY in out_types:  # an unwired Panel, or an unresolved ``like:`` output
            self.needs_as_text = True
            return f"_as_text({expr})"
        if len(out_types) == 1 and out_types[0] in types.TO_TEXT and out_types[0] not in in_types:
            return f"str({expr})"
        if any(t in types.TO_TEXT and t not in in_types for t in out_types):
            self.needs_as_text = True
            return f"_as_text({expr})"
        return expr

    # ── nodes ──
    def constant(self, node: Node) -> str:
        wires = [w for w in self.graph.wires if w.src == node.id]
        suffix = slug(wires[0].dst_port).upper() if wires else "VALUE"
        name = f"{self.names[node.id].upper()}_{suffix}"
        value = param_output(node)
        if node.component == PARAM_TEXT and isinstance(value, str):
            value = relativize(value, self.base_dir)
        note = self.constant_note(node)
        targets = ", ".join(f"{w.dst} {self.graph.nodes[w.dst].title}.{w.dst_port}" for w in wires)
        comment = f"# {node.id} {note}" + (f" → {targets}" if targets else "")
        self.exprs[(node.id, "value")] = name
        self.out_types[(node.id, "value")] = self.graph.output_types(node.id, "value")
        return f"{comment}\n{name} = {self.literal(value)}\n"

    @staticmethod
    def constant_note(node: Node) -> str:
        """What the constant comes from, for its comment."""
        integer = ", integer" if node.integer else ""
        if node.component == PARAM_SLIDER:
            limits = f"{_num(node.min)}..{_num(node.max)}, step {_num(node.step)}"
            return f"Number Slider ({limits}{integer})"
        if node.component == PARAM_NUMBER:
            return f"Number{' (integer)' if node.integer else ''}"
        if node.component == PARAM_VALUE_LIST:
            options = ", ".join(f"{o['label']}={o['value']}" for o in node.options or [])
            return f"Value List ({options})"
        if node.component == PARAM_TOGGLE:
            return "Boolean Toggle"
        if node.component == PARAM_COLOR:
            return "Color Swatch"
        if node.component == PARAM_COLORMAP:
            return "Colormap"
        return "Text"

    def literal(self, value: Any) -> str:
        """Source for a constant; a Color or Colormap needs the vendored types."""
        if isinstance(value, types.Color | types.Colormap):
            self.needs_types = True
        return python_literal(value)

    def function(self, node: Node) -> _Function:
        where = self.label(node)
        if node.parse_error is not None or node.spec is None or node.source is None:
            raise ExportError(f"{where}: fix the component first: {node.parse_error}")
        spec: ComponentSpec = node.spec
        wired = [p for p in spec.inputs if self.graph.wires_into(node.id, p)]
        for name in spec.inputs:
            if name not in wired and name not in spec.settings:
                raise ExportError(f'{where}: input "{name}" is not connected')

        lines = _lines(spec.source)
        settings: list[str] = []
        if spec.blocks.settings_start is not None:
            settings = lines[spec.blocks.settings_start : spec.blocks.code_start - 1]
            settings = _comment_out_settings(settings, set(wired), "see main()")
        code, imports = _rewrite_imports("".join(lines[spec.blocks.code_start :]), where)
        for module in imports.other:
            self.warnings.append(
                f"{where} imports {module}: the script still needs GeoKnit installed"
            )

        if _uses_name(code, INPUTS_NAME):
            # GeoKnit sets INPUTS before the code: every input, wired or from its setting.
            pairs = ", ".join(f'"{n}": {n}' for n in spec.inputs)
            settings.append(f"{INPUTS_NAME} = {{{pairs}}}\n")
        body = "# --- settings ---\n" + "".join(settings) + "# --- code ---\n" + code
        outputs = list(spec.outputs)
        prints = PRINT_PORT in spec.outputs and spec.outputs[PRINT_PORT].type == types.TEXT
        fname = f"{self.names[node.id]}_{slug(spec.name)}"
        head = f"def {fname}({', '.join(wired)}):\n"
        if prints:
            self.needs_capture = True
            text = (
                head
                + f"{INDENT}with _capture_print() as _printed:\n"
                + indent(body, INDENT * 2)
                + f'{INDENT}if "{PRINT_PORT}" not in locals():\n'
                + f"{INDENT * 2}{PRINT_PORT} = _printed.getvalue()\n"
            )
        else:
            text = head + indent(body)
        if outputs:
            # List outputs are plain lists, as in GeoKnit (a tuple is converted).
            returned = [self._returned(node, p) for p in outputs]
            text += f"{INDENT}return {', '.join(returned)}\n"
        for port in outputs:
            var = f"{self.names[node.id]}_{port}"
            # An output named like its component (Half → half) must not hide the function.
            self.exprs[(node.id, port)] = f"{var}_value" if var == fname else var
            self.out_types[(node.id, port)] = self.graph.output_types(node.id, port)
        return _Function(node, fname, wired, outputs, text, imports)

    def _returned(self, node: Node, port: str) -> str:
        """How a function returns an output, as GeoKnit keeps it (SPEC 10): a list
        output as ``list(x)``; a Boolean output through ``bool`` (so ``numpy.bool_``
        becomes ``bool``, as ``as_output`` does), per element for a list of them."""
        is_list = self.graph.output_is_list(node.id, port)  # also a like: output of a list
        if self.graph.output_types(node.id, port) == (types.BOOLEAN,):
            return f"[bool(_v) for _v in {port}]" if is_list else f"bool({port})"
        return f"list({port})" if is_list else port

    # ── view nodes (comments only) ──
    def _ref(self, src: str, port: str) -> str:
        return f"{self.names[src]}.{port}"

    def layer_comment(self, node: Node) -> str:
        """``# n24 Map Layer "IMD classes": n04.classes, colormap n23`` (change 03):
        the data's output, then each wired style input and the node it comes from."""
        data = self.graph.wires_into(node.id, "data")
        try:
            name = layer_name(self.graph, node.id)
        except (GraphError, ValueError):  # a saved style that no longer loads
            name = node.title
        parts = [self._ref(data[0].src, data[0].src_port) if data else "no data"]
        for port in LAYER_STYLE_INPUTS:
            for w in self.graph.wires_into(node.id, port):
                parts.append(f"{port} {self.names[w.src]}")
        return f'# {node.id} Map Layer "{name}": {", ".join(parts)}'

    def viewer_comment(self, node: Node) -> str:
        """``# n25 Map Viewer: n24.layer, n10.test``: its layers in wire order."""
        wires = self.graph.wires_into(node.id, "layers")
        shown = ", ".join(self._ref(w.src, w.src_port) for w in wires) or "no layers"
        return f"# {node.id} Map Viewer: {shown}"

    def header_comment(self, node: Node) -> str:
        if node.component == "inline":
            where = f"inline, based on {node.based_on}" if node.based_on else "inline"
            return f"# {node.id} · {node.title} ({where}, modified)\n"
        version = f" {node.version}" if node.version else ""
        return f"# {node.id} · {node.title} ({node.component}{version})\n"

    # ── assembling ──
    def run(self, workflow_name: str) -> ExportResult:
        constants: list[str] = []
        functions: list[_Function] = []
        steps: list[str] = []
        panels: list[str] = []
        panel_values: dict[str, str | None] = {}

        for nid in self.order:
            node = self.graph.nodes[nid]
            if node.component in VALUE_PARAMS:
                constants.append(self.constant(node))
            elif node.component == PARAM_PANEL:
                wires = self.graph.wires_into(nid, "data")
                value = self.exprs[(wires[0].src, wires[0].src_port)] if wires else "None"
                self.exprs[(nid, "data")] = value
                self.out_types[(nid, "data")] = self.graph.output_types(nid, "data")
                panel_values[nid] = value if wires else None
            elif node.component == PARAM_LAYER:
                steps.append(self.layer_comment(node))
                # A Panel on a Map Layer prints this (the layer is not exported).
                self.exprs[(nid, "layer")] = '"(Map Layer, not exported)"'
                self.out_types[(nid, "layer")] = (types.TEXT,)
            elif node.component == PARAM_MAP:
                steps.append(self.viewer_comment(node))
            else:
                fn = self.function(node)
                functions.append(fn)
                args = [f"{p}={self.wired_value(node, p)}" for p in fn.params]
                targets = ", ".join(self.exprs[(nid, p)] for p in fn.outputs)
                lhs = f"{targets} = " if targets else ""
                call = f"{lhs}{fn.name}({', '.join(args)})"
                if len(INDENT + call) > LINE_LENGTH:
                    inner = "".join(f"{INDENT * 2}{a},\n" for a in args)
                    call = f"{lhs}{fn.name}(\n{inner}{INDENT})"
                steps.append(call)

        # Panels print after the run, in node order, like ``geoknit run``.
        for nid, node in self.graph.nodes.items():
            if node.component != PARAM_PANEL:
                continue
            value = panel_values[nid]
            panels.append(f'_panel("{nid}", {value})' if value else f'_panel("{nid}")')

        vendor: list[str] = []
        used = set().union(*(f.imports.vendored for f in functions)) if functions else set()
        if any(m in HELPER_MODULES for m in used):
            vendor = list(VENDOR_FILES)
        elif used or panels or self.needs_as_text or self.needs_types:
            vendor = [TYPES_MODULE]

        requires = sorted(
            {r for f in functions for r in (f.node.spec.requires if f.node.spec else [])}
        )
        return ExportResult(
            script=self.assemble(
                workflow_name, constants, functions, steps, panels, panel_values, vendor, requires
            ),
            warnings=self.warnings,
        )

    def assemble(
        self,
        workflow_name: str,
        constants: list[str],
        functions: list[_Function],
        steps: list[str],
        panels: list[str],
        panel_values: dict[str, str | None],
        vendor: list[str],
        requires: list[str],
    ) -> str:
        doc = [f"{workflow_name}, exported from GeoKnit {__version__}.", ""]
        if self.warnings:
            doc.append("Runs with plain Python, but still needs GeoKnit (see the warnings).")
        else:
            doc.append("Runs with plain Python: GeoKnit itself is not needed.")
        if requires:
            doc.append(f"Needs these packages: {', '.join(requires)}.")
        doc.append("Relative paths resolve against the folder of this file.")
        if self.warnings:
            doc += ["", "Warnings:"] + [f"- {w}" for w in self.warnings]
        out = ['"""' + "\n".join(doc).replace('"""', "'''") + '\n"""\n', "\n"]
        out.append("from __future__ import annotations\n\n")
        if self.needs_capture:
            out.append("import contextlib\nimport io\n")
        out.append("import os\nimport sys\nfrom pathlib import Path\n\n")
        out.append("BASE_DIR = Path(__file__).resolve().parent\n\n")

        vendored = ""
        if vendor:
            vendored = "\n\n# ── Vendored from GeoKnit (geoknit.helpers and its types) ──\n\n"
            vendored += vendored_section(vendor)
        if self.needs_types:  # Color(...) / Colormap(...) constants need the classes first
            out.append(vendored)
        if constants:
            out.append("\n# ── Values (Params nodes): change them here ──\n\n")
            out.append("\n".join(constants))
        if not self.needs_types:
            out.append(vendored)
        out.append("\n\n# ── Script helpers ──\n\n")
        out.append(_PANEL_FN if panels else "")
        out.append(_AS_TEXT_FN if self.needs_as_text else "")
        out.append(_CAPTURE_FN if self.needs_capture else "")
        out.append("\n# ── Components ──\n")
        for fn in functions:
            out.append("\n\n" + self.header_comment(fn.node) + fn.source)

        out.append("\n\ndef main() -> dict[str, object]:\n")
        out.append(f'{INDENT}"""Run the workflow; returns the value shown in each Panel."""\n')
        out.append(f"{INDENT}os.chdir(BASE_DIR)\n")
        for step in steps:
            out.append(f"{INDENT}{step}\n")
        for line in panels:
            out.append(f"{INDENT}{line}\n")
        shown = ", ".join(f'"{n}": {v}' for n, v in panel_values.items() if v is not None)
        out.append(f"{INDENT}return {{{shown}}}\n")
        out.append(_MAIN_BLOCK)
        return re.sub(r"\n{4,}", "\n\n\n", "".join(out))


def python_literal(value: Any) -> str:
    """Source that rebuilds ``value``: ``Color("#0B7A7C")``, ``Colormap.named("viridis")``,
    the full ``Colormap(...)`` constructor for any other colormap, else ``repr``."""
    if isinstance(value, types.Color):
        return f'Color("{value.hex}")'
    if isinstance(value, types.Colormap):
        if value.is_named and value.min is None and value.max is None:
            reverse = ", reverse=True" if value.reverse else ""
            return f'Colormap.named("{value.name}"{reverse})'
        return repr(value)  # the dataclass repr is the constructor call
    return repr(value)


def _num(value: float | None) -> str:
    if value is None:
        return "?"
    return f"{value:g}"


_MAIN_BLOCK = """

if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        # Never crash on characters the console cannot show (Windows code pages).
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    main()
"""

_PANEL_FN = '''def _panel(node_id: str, *value: object) -> None:
    """Print a Panel like ``geoknit run`` does."""
    print(f"--- Panel {node_id} ---")
    print(describe(value[0]) if value else "(empty)")

'''

_AS_TEXT_FN = '''def _as_text(value: object) -> object:
    """A Number reaching a Text input becomes text (GeoKnit's one conversion)."""
    return convert_for_input(value, TEXT)

'''

_CAPTURE_FN = '''class _Tee(io.TextIOBase):
    """Write to several streams at once."""

    def __init__(self, *streams: io.TextIOBase) -> None:
        self.streams = streams

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        for stream in self.streams:
            stream.write(s)
        return len(s)


@contextlib.contextmanager
def _capture_print():
    """Collect what the code prints (for its ``out`` output) and still show it."""
    printed = io.StringIO()
    with (
        contextlib.redirect_stdout(_Tee(sys.stdout, printed)),
        contextlib.redirect_stderr(_Tee(sys.stderr, printed)),
    ):
        yield printed

'''


def export_script(
    graph: Graph,
    *,
    workflow_name: str = "workflow.geoknit",
    base_dir: Path | None = None,
) -> ExportResult:
    """The workflow as one standalone script. Raises ``ExportError`` naming the node."""
    return _Exporter(graph, base_dir).run(workflow_name)
