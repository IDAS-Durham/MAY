import ast
import inspect

import pytest

from may.preflight import report as report_module
from may.preflight.report import Finding, PreflightError, PreflightReport


def make_report(problems=(), warnings=()):
    report = PreflightReport()
    for key, message in problems:
        report.problem(key, message)
    for key, message in warnings:
        report.warning(key, message)
    return report


class StageError(Exception):
    pass


def test_problem_and_warning_add_findings_in_order():
    report = make_report(
        problems=[("b", "second"), ("a", "first")], warnings=[("c", "third")]
    )
    assert report.problems == [Finding("b", "second"), Finding("a", "first")]
    assert report.warnings == [Finding("c", "third")]


def test_finding_is_frozen():
    with pytest.raises(AttributeError):
        Finding("key", "message").key = "other"


def test_has_problems():
    assert not PreflightReport().has_problems
    assert not make_report(warnings=[("key", "message")]).has_problems
    assert make_report(problems=[("key", "message")]).has_problems


def test_merge_keeps_order_and_drops_exact_duplicates():
    first = make_report(problems=[("a", "one"), ("b", "two")], warnings=[("w", "x")])
    second = make_report(problems=[("a", "one"), ("a", "other")], warnings=[("w", "x")])
    merged = PreflightReport.merge(first, second)
    assert merged.problems == [
        Finding("a", "one"),
        Finding("b", "two"),
        Finding("a", "other"),
    ]
    assert merged.warnings == [Finding("w", "x")]


def test_merge_returns_new_report_and_leaves_inputs_unchanged():
    first = make_report(problems=[("a", "one")])
    second = make_report(problems=[("b", "two")])
    merged = PreflightReport.merge(first, second)
    assert merged is not first and merged is not second
    assert first.problems == [Finding("a", "one")]
    assert second.problems == [Finding("b", "two")]


def test_under_default_separator():
    report = make_report(problems=[("venue_types.school", "unknown venue type")])
    prefixed = report.under("timeline.steps[3] (school.yaml)")
    assert prefixed.problems == [
        Finding("timeline.steps[3] (school.yaml): venue_types.school", "unknown venue type")
    ]


def test_under_custom_separator_and_nesting_and_warnings():
    report = make_report(warnings=[("rules_file", "not set")])
    prefixed = report.under("inner", sep=".").under("outer", sep=".")
    assert prefixed.warnings == [Finding("outer.inner.rules_file", "not set")]


def test_under_leaves_input_unchanged():
    report = make_report(problems=[("key", "message")])
    report.under("prefix")
    assert report.problems == [Finding("key", "message")]


def test_format_full_report():
    report = make_report(
        problems=[
            ("venues.config_file", "not found; tried a, b"),
            ("timeline.steps[3] (school.yaml): venue_types.school", "unknown venue type"),
        ],
        warnings=[("households.rules_file", "not set; relationship rules disabled")],
    )
    assert report.format() == (
        "Preflight found 2 problems, 1 warning.\n"
        "\n"
        "Problems:\n"
        "  venues.config_file: not found; tried a, b\n"
        "  timeline.steps[3] (school.yaml): venue_types.school: unknown venue type\n"
        "\n"
        "Warnings:\n"
        "  households.rules_file: not set; relationship rules disabled"
    )


def test_format_singular_counts_and_omits_empty_section():
    assert make_report(problems=[("key", "message")]).format() == (
        "Preflight found 1 problem, 0 warnings.\n\nProblems:\n  key: message"
    )
    assert make_report(warnings=[("a", "x"), ("b", "y")]).format() == (
        "Preflight found 0 problems, 2 warnings.\n\nWarnings:\n  a: x\n  b: y"
    )


def test_format_clean_report():
    assert PreflightReport().format() == "Preflight passed."


@pytest.mark.parametrize("report", [PreflightReport(), make_report(warnings=[("a", "x")])])
def test_raise_if_problems_noop_without_problems(report):
    report.raise_if_problems(StageError, "Venue config has problems:")


def test_raise_if_problems_raises_given_class_with_header_and_body():
    report = make_report(problems=[("config_file", "not found")], warnings=[("a", "x")])
    with pytest.raises(StageError) as caught:
        report.raise_if_problems(StageError, "Venue config has 1 problem:")
    assert str(caught.value) == (
        "Venue config has 1 problem:\n"
        "\n"
        "Problems:\n"
        "  config_file: not found\n"
        "\n"
        "Warnings:\n"
        "  a: x"
    )
    assert caught.value.report is report


def test_preflight_error_carries_report_and_formats():
    report = make_report(problems=[("key", "message")])
    error = PreflightError(report)
    assert error.report is report
    assert str(error) == report.format()


def test_report_module_imports_nothing_from_project():
    tree = ast.parse(inspect.getsource(report_module))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append("." if node.level else node.module)
    assert not [
        name for name in imported if name in ("may", ".") or name.startswith("may.")
    ]
