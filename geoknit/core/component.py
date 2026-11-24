"""The component file format (SPEC section 4): parse a component and run it.

A component file has three parts:

- a header: the first comment block, starting with ``# geoknit: component``,
  YAML once the leading ``# `` is stripped;
- a settings block between ``# --- settings ---`` and ``# --- code ---``:
  top-level assignments of literals, each optionally followed by a hint comment
  (``# options: a | b``, ``# range: 0..10``, ``# multiline``);
- a code block: plain Python after ``# --- code ---``.

This file format is a public contract; see SPEC section 4 before changing it.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import linecache
import logging
import tokenize
import traceback
import warnings
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from geoknit.core import types

HEADER_MARK = "geoknit: component"
SETTINGS_MARK = "# --- settings ---"
CODE_MARK = "# --- code ---"

PRINT_PORT = "out"
"""A Text output with this name that the code does not set receives everything printed."""

LogFn = Callable[[str], None]


class ComponentParseError(ValueError):
    """The header or settings block of a component file is invalid."""

    def __init__(self, message: str, line: int | None = None) -> None:
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line is not None else message)


# ── Parsed component ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Port:
    """One input or output of a component."""

    name: str
    type: str
    access: str = "item"
    file: str | None = None
    """``"write"`` for a Text input naming a file the component writes (not fingerprinted)."""


FILE_ROLES = ("write",)


@dataclass(frozen=True)
class Setting:
    """One assignment in the settings block, with its form hint."""

    name: str
    value: Any
    line: int
    """1-based line number in the component file."""
    widget: str = "text"
    """``text``, ``dropdown`` (options), ``number`` (range) or ``multiline``."""
    options: tuple[Any, ...] | None = None
    range: tuple[float, float] | None = None


@dataclass(frozen=True)
class Blocks:
    """0-based line indices splitting a component file into its parts."""

    header_end: int
    """First line after the header comment block."""
    settings_start: int | None
    """First line after the settings marker, or ``None`` without a settings block."""
    code_start: int
    """First line after the code marker."""


@dataclass
class ComponentSpec:
    """A parsed component file."""

    source: str
    name: str
    category: str
    description: str
    icon: str | None
    inputs: dict[str, Port]
    outputs: dict[str, Port]
    requires: list[str]
    header: dict[str, Any]
    settings: dict[str, Setting]
    blocks: Blocks

    @property
    def settings_values(self) -> dict[str, Any]:
        return {name: s.value for name, s in self.settings.items()}

    @property
    def required_inputs(self) -> list[str]:
        """Inputs with no same-named setting: they must be wired."""
        return [name for name in self.inputs if name not in self.settings]

    def settings_source(self) -> str:
        lines = self.source.splitlines(keepends=True)
        if self.blocks.settings_start is None:
            return ""
        return "".join(lines[self.blocks.settings_start : self.blocks.code_start - 1])

    def code_source(self) -> str:
        return "".join(self.source.splitlines(keepends=True)[self.blocks.code_start :])


# ── Parsing ──────────────────────────────────────────────────────────────────


def find_blocks(source: str) -> Blocks:
    """Locate the header, settings and code blocks."""
    lines = source.splitlines()
    first = next((i for i, ln in enumerate(lines) if ln.strip()), None)
    if first is None or _strip_comment(lines[first]).strip() != HEADER_MARK:
        raise ComponentParseError(f'the file must start with "# {HEADER_MARK}"', 1)
    header_end = first
    while header_end < len(lines) and lines[header_end].lstrip().startswith("#"):
        if lines[header_end].strip() in (SETTINGS_MARK, CODE_MARK):
            break
        header_end += 1

    settings_mark = _find_line(lines, SETTINGS_MARK, header_end)
    code_mark = _find_line(lines, CODE_MARK, header_end)
    if code_mark is None:
        raise ComponentParseError(f'missing the line "{CODE_MARK}"')
    if settings_mark is not None and settings_mark > code_mark:
        raise ComponentParseError(
            f'"{SETTINGS_MARK}" must come before "{CODE_MARK}"', settings_mark + 1
        )
    return Blocks(
        header_end=header_end,
        settings_start=None if settings_mark is None else settings_mark + 1,
        code_start=code_mark + 1,
    )


def _find_line(lines: list[str], mark: str, start: int) -> int | None:
    found = [i for i in range(start, len(lines)) if lines[i].strip() == mark]
    if len(found) > 1:
        raise ComponentParseError(f'"{mark}" appears more than once', found[1] + 1)
    return found[0] if found else None


def _strip_comment(line: str) -> str:
    s = line.lstrip()
    if s.startswith("# "):
        return s[2:]
    return s[1:] if s.startswith("#") else s


def parse_component(source: str) -> ComponentSpec:
    """Parse a component file. Raises ``ComponentParseError`` with a line number."""
    blocks = find_blocks(source)
    lines = source.splitlines()
    header = _parse_header(lines, blocks.header_end)
    settings = _parse_settings(lines, blocks)

    inputs = _parse_ports(header.get("inputs"), "inputs", allow_list=True)
    outputs = _parse_ports(header.get("outputs"), "outputs", allow_list=False)
    clash = set(inputs) & set(outputs)
    if clash:
        raise ComponentParseError(
            f"ports used as both input and output: {', '.join(sorted(clash))}"
        )

    requires = header.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
        raise ComponentParseError("requires must be a list of package names")

    name = header.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ComponentParseError("the header needs a name")
    icon = header.get("icon")
    return ComponentSpec(
        source=source,
        name=name,
        category=str(header.get("category") or "Script"),
        description=str(header.get("description") or ""),
        icon=None if icon is None else str(icon),
        inputs=inputs,
        outputs=outputs,
        requires=list(requires),
        header=header,
        settings=settings,
        blocks=blocks,
    )


def _parse_header(lines: list[str], header_end: int) -> dict[str, Any]:
    text = "\n".join(_strip_comment(ln) for ln in lines[:header_end])
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        problem = getattr(exc, "problem", None) or str(exc)
        raise ComponentParseError(f"header is not valid YAML: {problem}", line) from None
    if not isinstance(data, dict) or data.get("geoknit") != "component":
        raise ComponentParseError("the header is not a mapping of keys", 1)
    return data


def _parse_ports(raw: object, key: str, *, allow_list: bool) -> dict[str, Port]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ComponentParseError(f"{key} must map port names to types")
    ports: dict[str, Port] = {}
    for name, spec in raw.items():
        name = str(name)
        if not name.isidentifier():
            raise ComponentParseError(f'port name "{name}" is not a valid Python name')
        file_role: object = None
        if isinstance(spec, str):
            type_name, access = spec, "item"
        elif isinstance(spec, dict):
            type_name, access = spec.get("type"), spec.get("access", "item")
            file_role = spec.get("file")
        else:
            raise ComponentParseError(f'{key}: "{name}" needs a type such as Raster')
        if type_name not in types.PORT_TYPES:
            raise ComponentParseError(
                f'{key}: "{name}" has unknown type "{type_name}" '
                f"(use one of {', '.join(types.PORT_TYPES)})"
            )
        if access not in ("item", "list") or (access == "list" and not allow_list):
            raise ComponentParseError(f'{key}: "{name}" has invalid access "{access}"')
        if file_role is not None:
            if not allow_list or file_role not in FILE_ROLES or type_name != types.TEXT:
                raise ComponentParseError(
                    f'{key}: "{name}": "file: write" is only allowed on a Text input'
                )
        ports[name] = Port(
            name=name,
            type=str(type_name),
            access=str(access),
            file=None if file_role is None else str(file_role),
        )
    return ports


def is_allowed_literal(value: object) -> bool:
    """int, float, str, bool, None, or a list/tuple of those."""
    if value is None or isinstance(value, bool | int | float | str):
        return not (isinstance(value, float) and value != value)  # no NaN
    if isinstance(value, list | tuple):
        return all(v is None or isinstance(v, bool | int | float | str) for v in value)
    return False


def _parse_settings(lines: list[str], blocks: Blocks) -> dict[str, Setting]:
    if blocks.settings_start is None:
        return {}
    start = blocks.settings_start
    text = "\n".join(lines[start : blocks.code_start - 1]) + "\n"
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        line = (exc.lineno or 1) + start
        raise ComponentParseError(f"settings block: {exc.msg}", line) from None

    comments = _comments_by_line(text)
    settings: dict[str, Setting] = {}
    for stmt in tree.body:
        line = stmt.lineno + start
        if not (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            raise ComponentParseError(
                "settings block: only simple assignments like `n = 10` are allowed", line
            )
        name = stmt.targets[0].id
        try:
            value = ast.literal_eval(stmt.value)
        except ValueError:
            raise ComponentParseError(
                f'settings block: "{name}" must be a literal (number, text, True/False, None, '
                "or a list of those)",
                line,
            ) from None
        if not is_allowed_literal(value):
            raise ComponentParseError(
                f'settings block: "{name}" must be a number, text, True/False, None, '
                "or a list of those",
                line,
            )
        if name in settings:
            raise ComponentParseError(f'settings block: "{name}" is set twice', line)
        hint = comments.get(stmt.end_lineno or stmt.lineno, "")
        settings[name] = _make_setting(name, value, line, hint)
    return settings


def _comments_by_line(text: str) -> dict[int, str]:
    out: dict[int, str] = {}
    with contextlib.suppress(tokenize.TokenError):
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string.lstrip("#").strip()
    return out


def _make_setting(name: str, value: Any, line: int, hint: str) -> Setting:
    key, _, rest = hint.partition(":")
    key = key.strip().lower()
    if key == "options" and rest.strip():
        options = tuple(_coerce_option(o.strip()) for o in rest.split("|") if o.strip())
        return Setting(name, value, line, widget="dropdown", options=options)
    if key == "range" and ".." in rest:
        lo, _, hi = rest.partition("..")
        try:
            limits = (_number(lo), _number(hi))
        except ValueError:
            raise ComponentParseError(f'"{name}": range must look like "0..100"', line) from None
        return Setting(name, value, line, widget="number", range=limits)
    if key == "multiline" and not rest.strip():
        return Setting(name, value, line, widget="multiline")
    return Setting(name, value, line)


def _number(text: str) -> float:
    value = float(text.strip())
    return int(value) if value.is_integer() and "." not in text and "e" not in text else value


def _coerce_option(text: str) -> Any:
    with contextlib.suppress(ValueError, SyntaxError):
        value = ast.literal_eval(text)
        if isinstance(value, bool | int | float) or value is None:
            return value
    return text


# ── Running ──────────────────────────────────────────────────────────────────


@dataclass
class RunResult:
    """Outcome of running one component."""

    outputs: dict[str, Any] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class _LineWriter(io.TextIOBase):
    """A text stream that emits complete lines to a callback."""

    def __init__(self, emit: LogFn) -> None:
        self._emit = emit
        self._buf = ""
        self.text = io.StringIO()

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self.text.write(s)
        self._buf += s
        *done, self._buf = self._buf.split("\n")
        for line in done:
            self._emit(line)
        return len(s)

    def flush_partial(self) -> None:
        if self._buf:
            self._emit(self._buf)
            self._buf = ""


class _LogHandler(logging.Handler):
    def __init__(self, emit: LogFn) -> None:
        super().__init__(logging.INFO)
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        self._emit(f"{record.levelname}: {record.getMessage()}")


@contextlib.contextmanager
def _capture(emit: LogFn, filename: str) -> Iterator[_LineWriter]:
    """Route print, warnings and logging into ``emit``."""
    out = _LineWriter(emit)

    def show(
        message: Warning | str,
        category: type[Warning],
        file_name: str,
        lineno: int,
        file: object = None,
        line: str | None = None,
    ) -> None:
        where = f" (line {lineno})" if file_name == filename else ""
        emit(f"{category.__name__}: {message}{where}")

    root = logging.getLogger()
    handler = _LogHandler(emit)
    old_level = root.level
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    try:
        with (
            warnings.catch_warnings(),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(out),
        ):
            warnings.simplefilter("always")
            warnings.showwarning = show
            yield out
    finally:
        out.flush_partial()
        root.removeHandler(handler)
        root.setLevel(old_level)


def _format_traceback(exc: BaseException) -> str:
    te = traceback.TracebackException.from_exception(exc)
    kept = [f for f in te.stack if f.filename != __file__]
    te.stack = traceback.StackSummary.from_list(kept)
    return "".join(te.format()).rstrip()


def _compile_block(spec: ComponentSpec, which: str, filename: str) -> Any:
    lines = spec.source.splitlines(keepends=True)
    if which == "settings":
        start = spec.blocks.settings_start
        if start is None:
            return None
        body = "".join(lines[start : spec.blocks.code_start - 1])
    else:
        start = spec.blocks.code_start
        body = "".join(lines[start:])
    # Pad with blank lines so tracebacks show line numbers of the component file.
    return compile("\n" * start + body, filename, "exec", dont_inherit=True)


def run_component(
    spec: ComponentSpec,
    inputs: Mapping[str, Any],
    *,
    filename: str | None = None,
    log: LogFn | None = None,
    cwd: Path | None = None,
    print_port: str | None = None,
) -> RunResult:
    """Run one component, following SPEC 4 "Running one component".

    ``inputs`` holds the wired inputs only. ``print_port`` names a Text output
    that receives everything printed (the Python component's ``out``).
    """
    result = RunResult()
    filename = filename or f"<component {spec.name}>"
    linecache.cache[filename] = (
        len(spec.source),
        None,
        spec.source.splitlines(keepends=True),
        filename,
    )

    def emit(line: str) -> None:
        result.log.append(line)
        if log is not None:
            log(line)

    unknown = [k for k in inputs if k not in spec.inputs]
    if unknown:
        result.error = f'unknown input "{unknown[0]}"'
        return result
    for name, value in inputs.items():
        port = spec.inputs[name]
        if port.access == "list":
            if not isinstance(value, list):
                result.error = f'input "{name}" expects a list'
                return result
            continue
        problem = types.check_value(port.type, value)
        if problem:
            result.error = f'input "{name}": {problem}'
            return result

    namespace: dict[str, Any] = {"__name__": "__geoknit_component__", "__builtins__": builtins}
    chdir = contextlib.chdir(cwd) if cwd is not None else contextlib.nullcontext()
    with chdir, _capture(emit, filename) as out:
        try:
            settings_code = _compile_block(spec, "settings", filename)
            if settings_code is not None:
                exec(settings_code, namespace)
            namespace.update(inputs)
            missing = [n for n in spec.inputs if n not in namespace]
            if missing:
                result.error = f'input "{missing[0]}" is not connected'
                return result
            exec(_compile_block(spec, "code", filename), namespace)
        except BaseException as exc:  # noqa: BLE001  (user code: report everything)
            if isinstance(exc, KeyboardInterrupt):
                raise
            result.error = _format_traceback(exc)
            return result
        printed = out.text.getvalue()

    for name, port in spec.outputs.items():
        if name == print_port and name not in namespace:
            namespace[name] = printed
        if name not in namespace:
            result.error = f'output "{name}" was not set by the code'
            return result
        value = namespace[name]
        problem = types.check_value(port.type, value)
        if problem:
            result.error = f'output "{name}": {problem}'
            return result
        result.outputs[name] = value
    return result


# ── Component libraries ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LibraryEntry:
    """A component available by reference, e.g. ``builtin/raster/reclassify``."""

    ref: str
    source: str
    version: str


class ComponentLibrary(Protocol):
    """Anything that resolves component references (the registry, or a dict in tests)."""

    def get(self, ref: str) -> LibraryEntry: ...


class DictLibrary:
    """A component library backed by a dict, for tests and simple embedding."""

    def __init__(self, entries: Mapping[str, LibraryEntry] | None = None) -> None:
        self._entries: dict[str, LibraryEntry] = dict(entries or {})

    def add(self, ref: str, source: str, version: str = "0.1.0") -> LibraryEntry:
        entry = LibraryEntry(ref=ref, source=source, version=version)
        self._entries[ref] = entry
        return entry

    def get(self, ref: str) -> LibraryEntry:
        try:
            return self._entries[ref]
        except KeyError:
            raise KeyError(f'unknown component "{ref}"') from None
