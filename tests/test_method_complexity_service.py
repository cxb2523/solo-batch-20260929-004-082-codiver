"""Tests for the resident HTTP analysis service."""

import json
from pathlib import Path

import pytest

from method_complexity_service import analyze_file, create_server
from java_fixtures import (
    CLEAN_CLASS,
    EMPTY_BODY_CLASS,
    EXACTLY_TEN,
    EXACTLY_TWENTY,
)


def _write_java(tmp_path, source, name="Sample.java"):
    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return target


def test_analyze_file_returns_method_details_and_persists(tmp_path):
    java_file = _write_java(tmp_path, EXACTLY_TEN)
    data_file = tmp_path / "defect_data.json"

    result = analyze_file(str(java_file), data_path=data_file)

    assert result["count"] == 1
    method = result["methods"][0]
    assert set(method) == {
        "method_name",
        "class_name",
        "signature",
        "start_line",
        "complexity",
        "severity",
        "lines_of_code",
    }
    assert method["method_name"] == "exactlyTen"
    assert method["class_name"] == "Sample"
    assert method["start_line"] == 2
    assert method["complexity"] == 10
    assert method["severity"] == "Medium"

    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["class_name"] == "Sample"


def test_clean_file_persists_nothing(tmp_path):
    java_file = _write_java(tmp_path, CLEAN_CLASS, name="Clean.java")
    data_file = tmp_path / "defect_data.json"

    result = analyze_file(str(java_file), data_path=data_file)
    assert result["methods"] == []
    assert result["count"] == 0
    assert not data_file.exists()


def test_empty_method_body_does_not_crash(tmp_path):
    java_file = _write_java(tmp_path, EMPTY_BODY_CLASS, name="Empty.java")
    data_file = tmp_path / "defect_data.json"

    result = analyze_file(str(java_file), data_path=data_file)
    assert result["count"] == 0
    assert not data_file.exists()


def test_repeated_analysis_does_not_double_count(tmp_path):
    java_file = _write_java(tmp_path, EXACTLY_TEN)
    data_file = tmp_path / "defect_data.json"

    analyze_file(str(java_file), data_path=data_file)
    analyze_file(str(java_file), data_path=data_file)

    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(stored) == 1


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        analyze_file(str(tmp_path / "Missing.java"),
                     data_path=tmp_path / "defect_data.json")


def test_non_java_file_raises_value_error(tmp_path):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        analyze_file(str(text_file), data_path=tmp_path / "defect_data.json")


def test_syntax_error_raises_value_error(tmp_path):
    broken = _write_java(tmp_path, "public class Broken {{{")
    with pytest.raises(ValueError):
        analyze_file(str(broken), data_path=tmp_path / "defect_data.json")


@pytest.fixture
def live_server(tmp_path):
    data_file = tmp_path / "defect_data.json"
    server = create_server(0, data_path=data_file)
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, data_file
    server.shutdown()
    server.server_close()


def test_http_post_analyzes_and_returns_json(live_server, tmp_path):
    server, _data_file = live_server
    java_file = _write_java(tmp_path, EXACTLY_TEN, name="Api.java")

    import urllib.request

    body = json.dumps({"file_path": str(java_file)}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/api/method-complexity",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))

    assert payload["count"] == 1
    assert payload["methods"][0]["complexity"] == 10
    assert payload["methods"][0]["severity"] == "Medium"


def test_http_post_concurrent_requests_dedup(live_server, tmp_path):
    server, data_file = live_server
    java_file = _write_java(tmp_path, EXACTLY_TEN, name="Concurrent.java")

    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    url = f"http://127.0.0.1:{server.server_port}/api/method-complexity"

    def call(_):
        body = json.dumps({"file_path": str(java_file)}).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(call, range(12)))

    assert all(status == 200 for status in statuses)
    stored = json.loads(data_file.read_text(encoding="utf-8"))
    assert len(stored) == 1


def test_http_post_reports_missing_file_path(live_server):
    server, _ = live_server
    import urllib.error
    import urllib.request

    body = json.dumps({}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/api/method-complexity",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(request, timeout=5)
    assert exc_info.value.code == 400


def test_http_get_snapshot(live_server, tmp_path):
    server, data_file = live_server
    _write_java(tmp_path, EXACTLY_TEN, name="Snap.java")
    analyze_file(
        str(tmp_path / "Snap.java"), data_path=Path(data_file)
    )

    import urllib.request

    with urllib.request.urlopen(
        f"http://127.0.0.1:{server.server_port}/api/method-complexity",
        timeout=5,
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["count"] == 1
