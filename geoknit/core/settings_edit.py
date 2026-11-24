"""Edit settings literals in place (SPEC 4 "Settings ↔ Code sync").

Only the source span of the changed literal is replaced; comments, blank lines,
spacing and every other line stay byte-for-byte the same.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any

from geoknit.core.component import (
    ComponentParseError,
    find_blocks,
    is_allowed_literal,
    parse_component,
)


def format_literal(value: Any, *, quote: str = '"', triple: bool = False) -> str:
    """Python source for an allowed settings literal."""
    if not is_allowed_literal(value):
        raise ValueError(
            f"{value!r} is not allowed in settings (number, text, True/False, None, or a list)"
        )
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return _quote(value, quote, triple)
    items = [format_literal(v, quote=quote) for v in value]
    if isinstance(value, tuple):
        return "(" + items[0] + ",)" if len(items) == 1 else "(" + ", ".join(items) + ")"
    return "[" + ", ".join(items) + "]"


def _quote(s: str, quote: str, triple: bool) -> str:
    s = s.replace("\\", "\\\\")
    if triple:
        q3 = quote * 3
        s = s.replace(q3, "\\" + quote * 3)
        if s.endswith(quote):
            s = s[:-1] + "\\" + quote
        return q3 + s + q3
    s = s.replace(quote, "\\" + quote).replace("\n", "\\n").replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return quote + s + quote


def _char_col(line: str, byte_col: int) -> int:
    return len(line.encode("utf-8")[:byte_col].decode("utf-8"))


def set_setting(source: str, name: str, value: Any) -> str:
    """Return ``source`` with setting ``name`` changed to ``value``."""
    return set_settings(source, {name: value})


def set_settings(source: str, values: Mapping[str, Any]) -> str:
    """Return ``source`` with several settings changed at once."""
    blocks = find_blocks(source)
    if blocks.settings_start is None:
        if values:
            raise KeyError(f'no setting named "{next(iter(values))}" (no settings block)')
        return source

    lines = source.splitlines(keepends=True)
    start, end = blocks.settings_start, blocks.code_start - 1
    block_lines = lines[start:end]
    tree = ast.parse("".join(block_lines))

    nodes: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                nodes[target.id] = stmt.value
    for key in values:
        if key not in nodes:
            raise KeyError(f'no setting named "{key}"')

    # Replace from the bottom of the block up so earlier offsets stay valid.
    edits = sorted(((nodes[k], v) for k, v in values.items()), key=_position, reverse=True)
    for node, new_value in edits:
        assert node.end_lineno is not None and node.end_col_offset is not None
        first, last = node.lineno - 1, node.end_lineno - 1
        col0 = _char_col(block_lines[first], node.col_offset)
        col1 = _char_col(block_lines[last], node.end_col_offset)
        old_text = _segment(block_lines, first, col0, last, col1)
        quote, triple = _quote_style(old_text)
        new_text = format_literal(
            new_value, quote=quote, triple=triple and isinstance(new_value, str)
        )
        merged = block_lines[first][:col0] + new_text + block_lines[last][col1:]
        block_lines[first : last + 1] = [merged]

    result = "".join(lines[:start] + block_lines + lines[end:])
    _check(result, values)
    return result


def _position(item: tuple[ast.expr, Any]) -> tuple[int, int]:
    return (item[0].lineno, item[0].col_offset)


def _segment(lines: list[str], first: int, col0: int, last: int, col1: int) -> str:
    if first == last:
        return lines[first][col0:col1]
    return lines[first][col0:] + "".join(lines[first + 1 : last]) + lines[last][:col1]


def _quote_style(old_text: str) -> tuple[str, bool]:
    """Keep the quote character (and triple quoting) of the literal being replaced."""
    s = old_text.lstrip("([ ")
    s = s.lstrip("rRbBuU")
    if s.startswith(('"""', "'''")):
        return s[0], True
    if s.startswith("'"):
        return "'", False
    return '"', False


def _check(source: str, values: Mapping[str, Any]) -> None:
    try:
        spec = parse_component(source)
    except ComponentParseError as exc:  # pragma: no cover  (defensive)
        raise RuntimeError(f"settings edit produced an invalid file: {exc}") from exc
    for key, value in values.items():
        got = spec.settings[key].value
        if got != value or type(got) is not type(value):
            raise RuntimeError(f'settings edit of "{key}" did not round-trip')  # pragma: no cover
