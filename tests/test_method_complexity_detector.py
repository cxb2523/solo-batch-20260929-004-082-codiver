"""Tests for the method-level cyclomatic complexity detector."""

import javalang
import pytest

from detectors.method_complexity import (
    MethodComplexitySmells,
    cyclomatic_complexity,
    severity_for_complexity,
    build_signature,
)
from java_fixtures import (
    CLEAN_CLASS,
    EMPTY_BODY_CLASS,
    EMPTY_INTERFACE,
    EXACTLY_TEN,
    EXACTLY_TWENTY,
    EXACTLY_FORTY,
)


def _issues(source):
    tree = javalang.parse.parse(source)
    return MethodComplexitySmells().detect(tree, source.split("\n"))


@pytest.mark.parametrize(
    "complexity, severity",
    [
        (9, None),
        (10, "Medium"),
        (19, "Medium"),
        (20, "High"),
        (39, "High"),
        (40, "Critical"),
        (99, "Critical"),
    ],
)
def test_severity_thresholds_are_inclusive(complexity, severity):
    assert severity_for_complexity(complexity) == severity


def test_complexity_starts_at_one_and_counts_branches():
    source = """
public class C {
  public int m(int v) {
    int x = 0;
    if (v > 0) { x += 1; }
    if (v > 1) { x += 1; }
    return x;
  }
}
"""
    tree = javalang.parse.parse(source)
    method = next(tree.filter(javalang.tree.MethodDeclaration))[1]
    assert cyclomatic_complexity(method) == 3


def test_threshold_equality_enters_higher_band():
    ten = _issues(EXACTLY_TEN)
    twenty = _issues(EXACTLY_TWENTY)
    forty = _issues(EXACTLY_FORTY)

    assert [(i["Complexity"], i["Severity"]) for i in ten] == [(10, "Medium")]
    assert [(i["Complexity"], i["Severity"]) for i in twenty] == [(20, "High")]
    assert [(i["Complexity"], i["Severity"]) for i in forty] == [(40, "Critical")]


def test_empty_and_abstract_method_bodies_are_not_defects():
    issues = _issues(EMPTY_BODY_CLASS)
    assert issues == []

    interface_issues = _issues(EMPTY_INTERFACE)
    assert interface_issues == []


def test_clean_file_produces_no_defects():
    assert _issues(CLEAN_CLASS) == []


def test_issue_carries_structured_identity_fields():
    issues = _issues(EXACTLY_TEN)
    assert len(issues) == 1
    issue = issues[0]
    assert issue["Type"] == "Method Complexity"
    assert issue["Category"] == "Implementation"
    assert issue["ClassName"] == "Sample"
    assert issue["MethodName"] == "exactlyTen"
    assert issue["Signature"] == "exactlyTen(int)"
    assert issue["StartLine"] == 2
    assert issue["Complexity"] == 10
    assert issue["Target"] == "Sample.exactlyTen"


def test_start_line_points_at_method_declaration():
    source = "\n\npublic class A {\n  public int later(int v) {\n    int x = 0;\n"
    source += "".join(
        f"    if (v > {i}) {{ x += {i}; }}\n" for i in range(9)
    )
    source += "    return x;\n  }\n}\n"
    issues = _issues(source)
    assert issues[0]["StartLine"] == 4


def test_signature_distinguishs_overloads():
    source = """
public class Over {
  public int m(int v) { return run(v); }
  public int m(int v, int w) { return run(v) + run(w); }
  private int run(int v) {
    int x = 0;
"""
    source += "".join(f"    if (v > {i}) x++;\n" for i in range(9))
    source += "    return x;\n  }\n}\n"
    issues = _issues(source)
    signatures = {issue["Signature"] for issue in issues}
    assert signatures == {"run(int)"}
    assert build_signature(
        next(
            node
            for _, node in javalang.parse.parse(source).filter(
                javalang.tree.MethodDeclaration
            )
            if node.name == "m" and len(node.parameters) == 2
        )
    ) == "m(int, int)"
