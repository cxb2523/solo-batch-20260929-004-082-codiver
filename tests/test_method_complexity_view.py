"""Tests for chart/view aggregation and page-number consistency."""

import pandas as pd

from utils.method_complexity_view import (
    method_complexity_records,
    filter_by_min_complexity,
    severity_distribution,
    top_methods,
    summary_counts,
)


def _snapshot_row(complexity, severity=None, signature="m(int)",
                  start_line=1, class_name="A"):
    if severity is None:
        if complexity >= 40:
            severity = "critical"
        elif complexity >= 20:
            severity = "high"
        else:
            severity = "medium"
    return {
        "module": class_name,
        "file": f"{class_name}.java",
        "defect_count": 1,
        "lines_of_code": 20,
        "severity": severity,
        "resolution_time": 0,
        "type": "Method Complexity",
        "method_name": signature.split("(", 1)[0],
        "class_name": class_name,
        "signature": signature,
        "start_line": start_line,
        "complexity": complexity,
        "recorded_at": "2026-09-30T10:00:00",
    }


def test_only_method_complexity_rows_are_selected():
    snapshot = [
        {"module": "legacy", "file": "x.py", "defect_count": 2},
        _snapshot_row(10),
    ]
    rows = method_complexity_records(snapshot)
    assert len(rows) == 1
    assert rows[0]["severity"] == "Medium"


def test_filter_switch_applies_minimum_complexity():
    rows = method_complexity_records(
        [_snapshot_row(10), _snapshot_row(20), _snapshot_row(40)]
    )
    filtered = filter_by_min_complexity(rows, 20)
    assert [row["complexity"] for row in filtered] == [20, 40]


def test_severity_distribution_matches_row_counts():
    rows = method_complexity_records(
        [
            _snapshot_row(10),
            _snapshot_row(10),
            _snapshot_row(20),
            _snapshot_row(40),
        ]
    )
    distribution = severity_distribution(rows)
    assert distribution == {"Critical": 1, "High": 1, "Medium": 2, "Low": 0}


def test_top_methods_orders_descending_and_limits():
    rows = method_complexity_records(
        [
            _snapshot_row(10, signature="a(int)", start_line=1),
            _snapshot_row(40, signature="b(int)", start_line=5),
            _snapshot_row(20, signature="c(int)", start_line=9),
        ]
    )
    top = top_methods(rows, limit=2)
    assert [row["complexity"] for row in top] == [40, 20]


def test_summary_counts_equal_json_counts():
    rows = method_complexity_records(
        [_snapshot_row(10), _snapshot_row(30), _snapshot_row(50)]
    )
    counts = summary_counts(rows)
    assert counts["total"] == 3
    assert counts["max"] == 50
    assert counts["average"] == 30.0
    assert counts["critical"] == 1
    assert counts["high"] == 1


def test_chart_dataframe_construction_from_snapshot():
    """Regression guard: charts must build without error after writes."""
    rows = method_complexity_records(
        [_snapshot_row(10), _snapshot_row(40)]
    )
    distribution = severity_distribution(rows)
    chart_df = pd.DataFrame(
        list(distribution.items()), columns=["Severity", "Count"]
    )
    assert int(chart_df["Count"].sum()) == 2

    top_df = pd.DataFrame(top_methods(rows))[
        ["complexity", "class_name", "signature", "start_line"]
    ]
    assert top_df.iloc[0]["complexity"] == 40


def test_empty_snapshot_renders_aggregates_safely():
    rows = method_complexity_records([])
    assert severity_distribution(rows) == {
        "Critical": 0,
        "High": 0,
        "Medium": 0,
        "Low": 0,
    }
    assert summary_counts(rows) == {
        "total": 0,
        "max": 0,
        "average": 0,
        "critical": 0,
        "high": 0,
    }
    assert top_methods(rows) == []
