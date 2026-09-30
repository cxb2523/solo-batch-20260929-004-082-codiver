"""Tests for atomic, concurrency-safe defect JSON storage."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from utils.defect_store import (
    append_method_complexity_records,
    build_record,
    load_snapshot,
)


def _record(class_name="A", signature="m(int)", start_line=1, complexity=10,
            severity="Medium", file="A.java"):
    return build_record(
        file=file,
        module=Path(file).stem,
        method_name=signature.split("(", 1)[0],
        class_name=class_name,
        signature=signature,
        start_line=start_line,
        complexity=complexity,
        severity=severity,
    )


def test_load_snapshot_handles_missing_file(tmp_path):
    assert load_snapshot(tmp_path / "missing.json") == []


def test_load_snapshot_survives_half_written_file(tmp_path):
    target = tmp_path / "defect_data.json"
    target.write_text('[{"module": "broken",', encoding="utf-8")
    assert load_snapshot(target) == []


def test_append_creates_list_document(tmp_path):
    target = tmp_path / "defect_data.json"
    append_method_complexity_records([_record()], data_path=target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["type"] == "Method Complexity"
    assert data[0]["severity"] == "medium"


def test_same_identity_replaces_not_duplicates(tmp_path):
    target = tmp_path / "defect_data.json"
    append_method_complexity_records([_record(complexity=10)], data_path=target)
    append_method_complexity_records([_record(complexity=12)], data_path=target)

    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["complexity"] == 12


def test_different_identities_accumulate(tmp_path):
    target = tmp_path / "defect_data.json"
    append_method_complexity_records(
        [
            _record(signature="a(int)", start_line=1),
            _record(signature="b(int)", start_line=5),
        ],
        data_path=target,
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    assert {row["signature"] for row in data} == {"a(int)", "b(int)"}


def test_legacy_records_are_preserved(tmp_path):
    target = tmp_path / "defect_data.json"
    target.write_text(
        json.dumps(
            [
                {
                    "module": "authentication",
                    "file": "main.py",
                    "defect_count": 5,
                    "lines_of_code": 300,
                    "severity": "high",
                    "resolution_time": 12,
                }
            ]
        ),
        encoding="utf-8",
    )
    append_method_complexity_records([_record()], data_path=target)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["module"] == "authentication"
    assert data[1]["type"] == "Method Complexity"


def test_concurrent_writes_never_lose_or_corrupt_records(tmp_path):
    target = tmp_path / "defect_data.json"

    def worker(index):
        append_method_complexity_records(
            [_record(signature=f"m{index}(int)", start_line=index + 1)],
            data_path=target,
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(worker, range(60)))

    data = json.loads(target.read_text(encoding="utf-8"))
    signatures = {row["signature"] for row in data}
    assert len(data) == 60
    assert signatures == {f"m{i}(int)" for i in range(60)}


def test_concurrent_writes_same_identity_keep_single_record(tmp_path):
    target = tmp_path / "defect_data.json"

    def worker(_index):
        append_method_complexity_records([_record(complexity=11)], data_path=target)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(worker, range(40)))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_snapshot_is_independent_of_later_writes(tmp_path):
    target = tmp_path / "defect_data.json"
    append_method_complexity_records([_record(signature="first(int)")],
                                     data_path=target)
    snapshot = load_snapshot(target)
    append_method_complexity_records([_record(signature="second(int)")],
                                     data_path=target)
    assert {row["signature"] for row in snapshot} == {"first(int)"}
