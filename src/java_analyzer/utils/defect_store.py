"""
Persistent defect record storage.

Method-complexity findings are appended to ``data/defect_data.json`` so
existing aggregations and charts keep consuming the same document.

Concurrency model: a process-wide lock serializes read-modify-write
sequences, updates go to a unique temporary file and are published via
``os.replace`` (atomic on both POSIX and Windows), and readers always
work on a freshly loaded snapshot so a chart can never observe a
half-written file.
"""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_PATH = _PROJECT_ROOT / "data" / "defect_data.json"

# One lock per data file path; shared across threads inside the process.
_LOCKS: "Dict[str, threading.RLock]" = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def load_snapshot(data_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    Load an immutable-at-use snapshot of all defect records.

    A missing or empty file yields an empty list. A corrupt file never
    crashes the dashboard; an empty snapshot is returned instead.
    """
    path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def _atomic_write(path: Path, records: List[Dict[str, Any]]) -> None:
    """Write via a unique temp file then atomically replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def build_record(
    *,
    file: str,
    module: str,
    method_name: str,
    class_name: str,
    signature: str,
    start_line: int,
    complexity: int,
    severity: str,
    lines_of_code: int = 0,
    recorded_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build one defect record.

    Keeps the legacy schema keys (``module``/``file``/``defect_count``/
    ``lines_of_code``/``severity``/``resolution_time``) so existing
    aggregation keeps working, and adds method-complexity fields.
    """
    return {
        "module": module,
        "file": file,
        "defect_count": 1,
        "lines_of_code": lines_of_code,
        "severity": severity.lower(),
        "resolution_time": 0,
        "type": "Method Complexity",
        "method_name": method_name,
        "class_name": class_name,
        "signature": signature,
        "start_line": start_line,
        "complexity": complexity,
        "recorded_at": recorded_at or datetime.now().isoformat(timespec="seconds"),
    }


def record_identity(record: Dict[str, Any]) -> Any:
    """
    Stable identity of a method-complexity record.

    ``(class name, signature, start line)`` as required by the spec.
    Legacy rows without the structured fields get a unique identity so
    they are never merged or dropped.
    """
    signature = record.get("signature")
    if signature is None:
        return ("__legacy__", id(record))
    return (record.get("class_name", ""), signature, record.get("start_line", 0))


def append_method_complexity_records(
    new_records: List[Dict[str, Any]],
    data_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """
    Merge method-complexity records into the JSON document.

    Existing records are preserved; rows with the same
    ``(class_name, signature, start_line)`` are replaced in place
    (keeping the earliest ``recorded_at``) so re-analyzing a file never
    inflates counts. Returns the resulting snapshot.
    """
    path = Path(data_path) if data_path is not None else DEFAULT_DATA_PATH
    lock = _lock_for(path)
    with lock:
        records = load_snapshot(path)

        index = {}
        for position, record in enumerate(records):
            if record.get("type") == "Method Complexity":
                index[record_identity(record)] = position

        for record in new_records:
            identity = record_identity(record)
            existing_position = index.get(identity)
            if existing_position is None:
                index[identity] = len(records)
                records.append(record)
            else:
                merged = dict(records[existing_position])
                merged.update(record)
                previous_timestamp = records[existing_position].get("recorded_at")
                if previous_timestamp:
                    merged["recorded_at"] = previous_timestamp
                records[existing_position] = merged

        _atomic_write(path, records)
        return records
