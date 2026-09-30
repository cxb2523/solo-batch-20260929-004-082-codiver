"""Tests for engine registration and complexity de-duplication."""

from analyzer_engine import StaticAnalyzerEngine


def test_method_complexity_detector_is_registered_by_default():
    engine = StaticAnalyzerEngine("public class A { int x() { return 1; } }")
    detector_names = [type(detector).__name__ for detector in engine.detectors]
    assert "MethodComplexitySmells" in detector_names


def test_detector_can_be_disabled_via_config():
    engine = StaticAnalyzerEngine(
        "public class A { int x() { return 1; } }",
        {"method_complexity": False},
    )
    detector_names = [type(detector).__name__ for detector in engine.detectors]
    assert "MethodComplexitySmells" not in detector_names


def test_high_complexity_method_counted_once_not_doubled():
    branches = "\n".join(f"    if (v > {i}) x++;" for i in range(19))
    source = f"""
public class A {{
  public int m(int v) {{
    int x = 0;
{branches}
    return x;
  }}
}}
"""
    engine = StaticAnalyzerEngine(source)
    issues, _tree = engine.run()

    complexity_issues = [
        issue for issue in issues if issue["Type"] == "Method Complexity"
    ]
    legacy_issues = [
        issue for issue in issues if issue["Type"] == "High Complexity"
    ]
    assert len(complexity_issues) == 1
    assert complexity_issues[0]["Complexity"] == 20
    assert complexity_issues[0]["Severity"] == "High"
    assert legacy_issues == []


def test_duplicate_method_identities_are_collapsed():
    reconciler = StaticAnalyzerEngine._reconcile_complexity_issues
    base = {
        "Type": "Method Complexity",
        "Target": "A.m",
        "Severity": "Medium",
        "Reason": "Cyclomatic complexity: 10",
        "Category": "Implementation",
        "ClassName": "A",
        "MethodName": "m",
        "Signature": "m(int)",
        "StartLine": 3,
        "Complexity": 10,
        "MethodLines": 12,
    }
    result = reconciler([dict(base), dict(base)])
    assert len(result) == 1


def test_clean_file_returns_empty_issue_list():
    source = """
public class Clean {
  public int add(int a, int b) {
    return a + b;
  }
}
"""
    issues, tree = StaticAnalyzerEngine(source).run()
    complexity_types = {
        issue["Type"]
        for issue in issues
        if "Complexity" in issue["Type"]
    }
    assert complexity_types == set()
    assert tree is not None
