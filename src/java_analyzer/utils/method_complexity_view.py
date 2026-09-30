"""
Pure view helpers for the persistent method-complexity panel.

Everything here is free of Streamlit imports so the distribution and
TOP-board aggregation logic can be unit tested directly. Charts in
``ui_components`` are rendered from these exact structures, which keeps
the on-page numbers identical to ``data/defect_data.json``.
"""

from typing import Any, Dict, List

SEVERITY_ORDER = ("Critical", "High", "Medium", "Low")
SEVERITY_ALIASES = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def normalize_severity(value: Any) -> str:
    """Map stored lowercase severities (and any casing) to display form."""
    if not isinstance(value, str):
        return "Medium"
    return SEVERITY_ALIASES.get(value.strip().lower(), value.strip().title())


def method_complexity_records(
    snapshot: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Return the method-complexity rows with normalized severities."""
    rows = []
    for record in snapshot:
        if not isinstance(record, dict):
            continue
        if record.get("type") != "Method Complexity":
            continue
        rows.append(
            {
                "file": record.get("file", ""),
                "class_name": record.get("class_name", ""),
                "method_name": record.get("method_name", ""),
                "signature": record.get("signature", ""),
                "start_line": int(record.get("start_line", 0) or 0),
                "complexity": int(record.get("complexity", 0) or 0),
                "severity": normalize_severity(record.get("severity")),
                "recorded_at": record.get("recorded_at", ""),
            }
        )
    return rows


def filter_by_min_complexity(
    rows: List[Dict[str, Any]], min_complexity: int
) -> List[Dict[str, Any]]:
    """Apply the page's complexity filter switch."""
    return [row for row in rows if row["complexity"] >= min_complexity]


def severity_distribution(
    rows: List[Dict[str, Any]]
) -> Dict[str, int]:
    """Count rows per severity band (stable key order)."""
    counts = {severity: 0 for severity in SEVERITY_ORDER}
    for row in rows:
        severity = row["severity"]
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def top_methods(
    rows: List[Dict[str, Any]], limit: int = 10
) -> List[Dict[str, Any]]:
    """Return the most complex methods (TOP board)."""
    return sorted(
        rows,
        key=lambda row: (
            -row["complexity"],
            row["class_name"],
            row["signature"],
            row["start_line"],
        ),
    )[:limit]


def summary_counts(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Headline numbers shown above the charts."""
    complexities = [row["complexity"] for row in rows]
    return {
        "total": len(rows),
        "max": max(complexities) if complexities else 0,
        "average": round(sum(complexities) / len(complexities), 2)
        if complexities
        else 0,
        "critical": severity_distribution(rows)["Critical"],
        "high": severity_distribution(rows)["High"],
    }
