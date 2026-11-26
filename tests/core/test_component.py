"""Component file parsing and running (SPEC 4)."""

import pytest

from geoknit.core.component import (
    ComponentParseError,
    parse_component,
    run_component,
)
from tests.core.sources import BOOM, LENGTH, REPEAT

HEADER = "# geoknit: component\n# name: T\n# outputs:\n#   y: Number\n\n"


def test_parse_header_ports_and_settings() -> None:
    spec = parse_component(REPEAT)
    assert spec.name == "Repeat"
    assert spec.category == "Text"
    assert list(spec.inputs) == ["text", "times"]
    assert spec.inputs["text"].type == "Text"
    assert spec.outputs["repeated"].type == "Text"
    assert spec.required_inputs == ["text"]  # `times` has a default setting
    times = spec.settings["times"]
    assert (times.value, times.widget, times.range, times.line) == (2, "number", (1, 10), 12)
    sep = spec.settings["sep"]
    assert (sep.widget, sep.options) == ("dropdown", ("-", "_", "+"))


def test_file_write_input() -> None:
    from tests.core.sources import WRITE_FILE

    spec = parse_component(WRITE_FILE)
    assert spec.inputs["path"].file == "write"
    assert spec.inputs["text"].file is None


def test_list_access_and_multiline_hint() -> None:
    src = (
        "# geoknit: component\n# name: Viewer\n# inputs:\n"
        "#   layers: {type: Any, access: list}\n\n"
        "# --- settings ---\nnote = '''a\nb'''  # multiline\nflag = True\n"
        "# --- code ---\npass\n"
    )
    spec = parse_component(src)
    assert spec.inputs["layers"].access == "list"
    assert spec.settings["note"].widget == "multiline"
    assert spec.settings["flag"].widget == "text"


@pytest.mark.parametrize(
    ("source", "message", "line"),
    [
        ("print('hi')\n", "must start with", 1),
        ("# geoknit: component\n# name: T\n", "missing the line", None),
        (HEADER + "# --- settings ---\nn = len('x')\n# --- code ---\n", "must be a literal", 7),
        (HEADER + "# --- settings ---\nimport os\n# --- code ---\n", "simple assignments", 7),
        (HEADER + "# --- settings ---\nn = 1\nn = 2\n# --- code ---\n", "set twice", 8),
        (HEADER + "# --- settings ---\nn = {'a': 1}\n# --- code ---\n", "must be a number", 7),
        (
            "# geoknit: component\n# name: T\n# inputs:\n#   x: Image\n\n# --- code ---\n",
            'unknown type "Image"',
            None,
        ),
        ("# geoknit: component\n# outputs: [\n\n# --- code ---\n", "not valid YAML", None),
        (
            "# geoknit: component\n# name: T\n# inputs:\n#   x: {type: Raster, file: write}\n"
            "\n# --- code ---\n",
            "only allowed on a Text input",
            None,
        ),
        (
            "# geoknit: component\n# name: T\n# inputs:\n#   x: {type: Text, file: read}\n"
            "\n# --- code ---\n",
            "only allowed on a Text input",
            None,
        ),
    ],
)
def test_parse_errors(source: str, message: str, line: int | None) -> None:
    with pytest.raises(ComponentParseError) as exc:
        parse_component(source)
    assert message in exc.value.message
    if line is not None:
        assert exc.value.line == line


def test_run_uses_settings_then_wired_inputs() -> None:
    spec = parse_component(REPEAT)
    assert run_component(spec, {"text": "ab"}).outputs == {"repeated": "ab-ab"}
    assert run_component(spec, {"text": "ab", "times": 3}).outputs == {"repeated": "ab-ab-ab"}


def test_required_input_not_connected() -> None:
    result = run_component(parse_component(LENGTH), {})
    assert result.error == 'input "text" is not connected'


def test_missing_and_wrong_type_outputs() -> None:
    missing = HEADER + "# --- code ---\nz = 1\n"
    assert run_component(parse_component(missing), {}).error == 'output "y" was not set by the code'
    wrong = HEADER + "# --- code ---\ny = 'one'\n"
    assert (
        run_component(parse_component(wrong), {}).error == 'output "y": expected Number, got Text'
    )
    wrong_input = run_component(parse_component(LENGTH), {"text": 3.5})
    assert wrong_input.error == 'input "text": expected Text, got Number'


def test_captures_print_warnings_and_logging() -> None:
    src = HEADER + (
        "# --- code ---\nimport logging, sys, warnings\n"
        "print('hello')\nprint('a', end='')\nprint('b')\n"
        "warnings.warn('careful')\nlogging.getLogger('x').info('note')\n"
        "print('to stderr', file=sys.stderr)\ny = 1\n"
    )
    lines: list[str] = []
    result = run_component(parse_component(src), {}, log=lines.append, filename="w.py")
    assert result.ok, result.error
    assert result.log == lines
    assert lines[:2] == ["hello", "ab"]
    assert "UserWarning: careful (line 11)" in lines
    assert "INFO: note" in lines
    assert "to stderr" in lines


def test_traceback_has_component_line_numbers() -> None:
    result = run_component(parse_component(BOOM), {}, filename="boom.py")
    assert result.error is not None
    assert 'File "boom.py", line 11' in result.error  # y = divide(1)
    assert 'File "boom.py", line 9' in result.error  # return a / 0
    assert "return a / 0" in result.error
    assert result.error.rstrip().endswith("ZeroDivisionError: division by zero")
    assert "component.py" not in result.error  # runner frames hidden


def test_syntax_error_in_code_reports_file_line() -> None:
    src = HEADER + "# --- code ---\ny = (1 +\n"
    result = run_component(parse_component(src), {}, filename="bad.py")
    assert result.error is not None and "SyntaxError" in result.error
    assert 'File "bad.py", line 7' in result.error


def test_print_port_receives_printed_text() -> None:
    src = (
        "# geoknit: component\n# name: Py\n# outputs:\n#   out: Text\n\n"
        "# --- code ---\nprint('x')\n"
    )
    result = run_component(parse_component(src), {}, print_port="out")
    assert result.outputs == {"out": "x\n"}


BOOLEAN_PORTS = """\
# geoknit: component
# name: Compare
# inputs:
#   n: Number
#   flag: Boolean
# outputs:
#   bigger: Boolean
#   label: Text

# --- code ---
import numpy as np

bigger = np.float64(2) > n
label = f"{flag}"
"""


def test_boolean_and_number_are_kept_apart() -> None:
    spec = parse_component(BOOLEAN_PORTS)
    assert spec.inputs["flag"].type == "Boolean"
    assert run_component(spec, {"n": True, "flag": True}).error == (
        'input "n": expected Number, got Boolean'
    )
    assert run_component(spec, {"n": 1, "flag": 1}).error == (
        'input "flag": expected Boolean, got Number'
    )
    result = run_component(spec, {"n": 1, "flag": False})
    assert result.error is None
    assert result.outputs == {"bigger": True, "label": "False"}
    assert type(result.outputs["bigger"]) is bool  # numpy.bool_ is converted


def test_new_types_in_headers() -> None:
    src = (
        "# geoknit: component\n# name: T\n# inputs:\n#   c: Color\n#   m: Colormap\n"
        "#   layer: Layer\n# outputs:\n#   y: Boolean\n\n# --- code ---\ny = True\n"
    )
    spec = parse_component(src)
    assert [p.type for p in spec.inputs.values()] == ["Color", "Colormap", "Layer"]
