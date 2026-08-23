"""The compiler as a judge — parsing its answer, and asking it real questions."""

import pytest

from paRY import config
from paRY.verify.oracle import check, parse_diagnostics

needs_compiler = pytest.mark.skipif(
    config.etamil_bin() is None, reason="the eTamil compiler is not built"
)


def test_position_comes_out_of_the_english_half():
    line = (
        "✗ வரி 1, நெடுவரிசை 6: '=' எதிர்பார்க்கப்பட்டது, 'x' கிடைத்தது  "
        "(line 1, column 6: expected '=', found 'x')"
    )
    (diagnostic,) = parse_diagnostics(line)
    assert (diagnostic.line, diagnostic.column) == (1, 6)
    assert diagnostic.message == "expected '=', found 'x'"


def test_a_diagnostic_without_a_position_is_still_a_diagnostic():
    (diagnostic,) = parse_diagnostics("✗ something went wrong")
    assert diagnostic.line is None
    assert diagnostic.message == "✗ something went wrong"


def test_ordinary_output_is_not_a_diagnostic():
    assert parse_diagnostics("compiled 3 modules\n\n") == []


@needs_compiler
def test_a_correct_program_compiles():
    assert check('அச்சு "hi";\n').ok


@needs_compiler
def test_a_parse_error_is_reported_with_its_position():
    result = check("மாறி x = 5;\n")
    assert not result.ok
    assert result.diagnostics[0].line == 1


@needs_compiler
def test_the_standard_library_is_reachable_from_stdin():
    """An import resolves even though the source never was a file on disk."""
    assert check('இறக்கு "nUlakam/paNam.qmz";\n').ok


@needs_compiler
def test_checking_stops_short_of_running():
    """`--check` does not resolve names, and this is the documented limit.

    If the compiler ever starts catching this, the oracle became stricter and
    the corpus pipeline should be told to expect it.
    """
    assert check("அச்சு y;\n").ok
