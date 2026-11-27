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


# ── ports in the header (Python component, SPEC 4) ──

PortList = list[Mapping[str, Any]]
"""Ports as ``[{"name": "raster", "type": "Raster", "access": "item", "file": None}, ...]``."""


def set_ports(source: str, inputs: PortList, outputs: PortList) -> str:
    """Return ``source`` with the header's ``inputs`` and ``outputs`` replaced.

    Every other header line, the settings block and the code stay byte-for-byte
    the same. Raises ``ValueError`` with a message for the user when a port is
    invalid (bad name, unknown type, duplicate).
    """
    blocks = find_blocks(source)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)
    head = lines[: blocks.header_end]

    keys = _header_keys(head)
    spans = {k: _key_span(head, keys, k) for k in ("inputs", "outputs") if k in keys}
    if spans:
        insert_at = min(start for start, _ in spans.values())
    elif "requires" in keys:
        insert_at = keys["requires"]
    else:
        insert_at = _last_content_line(head) + 1
    removed = {i for start, end in spans.values() for i in range(start, end)}

    new_block: list[str] = []
    for key, ports in (("inputs", inputs), ("outputs", outputs)):
        if ports:
            new_block.append(f"# {key}:{newline}")
            new_block.extend(f"#   {_port_line(p, key)}{newline}" for p in ports)

    out: list[str] = []
    for i, line in enumerate(head):
        if i == insert_at:
            out.extend(new_block)
        if i not in removed:
            out.append(line)
    if insert_at >= len(head):
        out.extend(new_block)
    result = "".join(out + lines[blocks.header_end :])

    try:
        spec = parse_component(result)
    except ComponentParseError as exc:
        raise ValueError(exc.message) from None
    names = [str(p.get("name")) for p in [*inputs, *outputs]]
    if len(set(names)) != len(names):
        dup = next(n for n in names if names.count(n) > 1)
        raise ValueError(f'the port name "{dup}" is used twice')
    if list(spec.inputs) != [p["name"] for p in inputs] or list(spec.outputs) != [
        p["name"] for p in outputs
    ]:
        raise ValueError("port names must be distinct")  # pragma: no cover  (defensive)
    return result


def _header_keys(head: list[str]) -> dict[str, int]:
    """Top-level header keys and the line each starts on."""
    keys: dict[str, int] = {}
    for i, line in enumerate(head):
        text = line.rstrip("\r\n").lstrip()
        if not text.startswith("#"):
            continue
        body = text[2:] if text.startswith("# ") else text[1:]
        if body and not body[0].isspace() and ":" in body:
            key = body.split(":", 1)[0]
            if key.isidentifier():
                keys.setdefault(key, i)
    return keys


def _key_span(head: list[str], keys: dict[str, int], key: str) -> tuple[int, int]:
    """Lines ``[start, end)`` holding ``key`` and its indented children."""
    start = keys[key]
    later = [i for i in keys.values() if i > start]
    end = min(later) if later else _last_content_line(head) + 1
    while end - 1 > start and head[end - 1].strip() in ("", "#"):
        end -= 1  # a blank comment line before the next key stays
    return start, end


def _last_content_line(head: list[str]) -> int:
    for i in range(len(head) - 1, -1, -1):
        if head[i].strip() not in ("", "#"):
            return i
    return 0


def _port_line(port: Mapping[str, Any], key: str) -> str:
    name = str(port.get("name", "")).strip()
    if not name.isidentifier():
        raise ValueError(f'"{name}" is not a valid port name (letters, digits and _)')
    type_name = str(port.get("type", ""))
    listed = [str(t) for t in port.get("types") or []]
    if len(listed) > 1 and listed[0] == type_name:
        type_name = f"[{', '.join(listed)}]"  # a union input (SPEC 3)
    access = port.get("access") or "item"
    file_role = port.get("file")
    like = port.get("like")
    if like:
        if access != "item" or file_role:
            raise ValueError(f'output "{name}" cannot combine like: with other keys yet')
        return f"{name}: {{like: {like}}}"
    extra: list[str] = []
    if access != "item":
        if key != "inputs":
            raise ValueError(f'output "{name}" cannot take a list')
        extra.append(f"access: {access}")
    if file_role:
        extra.append(f"file: {file_role}")
    if not extra:
        return f"{name}: {type_name}"
    return f"{name}: {{type: {type_name}, {', '.join(extra)}}}"
