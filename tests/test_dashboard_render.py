"""Integration test: panel renders charts and numbers match the JSON."""

import json
from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from method_complexity_service import analyze_file
from java_fixtures import EXACTLY_TEN, EXACTLY_TWENTY


PANEL_SCRIPT = """
import sys
from pathlib import Path

ROOT = Path(r"{root}")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "java_analyzer"))

from utils.ui_components import render_method_complexity_panel

render_method_complexity_panel()
"""


def test_panel_renders_and_matches_json(tmp_path, monkeypatch):
    import utils.defect_store as defect_store

    data_file = tmp_path / "defect_data.json"
    monkeypatch.setattr(defect_store, "DEFAULT_DATA_PATH", data_file)

    sample_a = tmp_path / "A.java"
    sample_a.write_text(EXACTLY_TEN, encoding="utf-8")
    sample_b = tmp_path / "B.java"
    sample_b.write_text(EXACTLY_TWENTY, encoding="utf-8")
    analyze_file(str(sample_a), data_path=data_file)
    analyze_file(str(sample_b), data_path=data_file)

    script = tmp_path / "panel_app.py"
    root = Path(__file__).resolve().parents[1]
    script.write_text(PANEL_SCRIPT.format(root=root), encoding="utf-8")

    app = AppTest.from_file(str(script), default_timeout=30)
    app.run()

    assert not app.exception, [ex.message for ex in app.exception]

    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(stored) == 2
    severities = sorted(row["severity"] for row in stored)
    assert severities == ["high", "medium"]

    metric_labels = [metric.label for metric in app.metric]
    assert "Methods Reported" in metric_labels
    reported = {
        metric.label: metric.value for metric in app.metric
    }
    assert reported["Methods Reported"] == "2"
    assert reported["Max Complexity"] == "20"
    assert reported["Critical / High"] == "0 / 1"

    # Switch the filter on: only the complexity-20 method remains.
    toggle = next(
        widget for widget in app.toggle if widget.label == "Filter by complexity"
    )
    toggle.set_value(True).run()
    slider = next(
        widget
        for widget in app.slider
        if widget.label == "Minimum complexity"
    )
    slider.set_value(20).run()
    assert not app.exception
    filtered_values = {
        metric.label: metric.value for metric in app.metric
    }
    assert filtered_values["Methods Reported"] == "1"
