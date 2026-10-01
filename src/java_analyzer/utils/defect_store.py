"""
Atomic defect-data storage for the method complexity service.

The dashboard aggregation and charts consume ``data/defect_data.json``.
Several HTTP requests can target the same file concurrently, so writes
are serialized with a process-wide lock, staged through a temporary
file in the same directory and published with an atomic
``os.replace``.  Readers always take a snapshot copy, which guarantees a
chart can never observe a half-written JSON document.
"""

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional


# Repository root: .../src/java_analyzer/utils -> four parents up.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STORE_PATH = PROJECT_ROOT / "data" / "defect_data.json"

# One lock per store path, shared across threads in this process.
_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()

COMPLEXITY_KIND = "method_complexity"

# Resolution time per severity band so the records remain meaningful to
# the existing aggregation consumers.
_RESOLUTION_TIME = {
    "low": 3,
    "medium": 8,
    "high": 16,
    "critical": 24,
}


def resolve_store_path(path: Optional[os.PathLike] = None) -> Path:
    """Resolve the defect-data path (env override is mainly used by tests)."""
    if path is not None:
        return Path(path)
    override = os.environ.get("DEFECT_DATA_PATH")
    if override:
        return Path(override)
    return DEFAULT_STORE_PATH


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _read_unlocked(path: Path) -> List[Dict[str, Any]]:
    """Read the JSON document without locking (caller must hold the lock)."""
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON array")
    return data


def _write_unlocked(path: Path, records: List[Dict[str, Any]]) -> None:
    """
    Atomically publish ``records``.

    The temporary file lives next to the target so ``os.replace`` is an
    atomic rename on the same filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(records, handle, indent=4, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def read_snapshot(path: Optional[os.PathLike] = None) -> List[Dict[str, Any]]:
    """
    Return a deep snapshot of the defect data.

    The copy is detached from the on-disk document, so consumers (charts,
    aggregation) can iterate it without ever seeing a torn write.
    """
    target = resolve_store_path(path)
    with _lock_for(target):
        return deepcopy(_read_unlocked(target))


def is_complexity_record(record: Dict[str, Any]) -> bool:
    """Return True for records produced by the method complexity service."""
    return record.get("record_kind") == COMPLEXITY_KIND


def complexity_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter a snapshot down to method-complexity records."""
    return [record for record in records if is_complexity_record(record)]


def complexity_finding_key(record: Dict[str, Any]) -> Any:
    """
    Identity key of a complexity finding.

    Same ``(class name, signature, start line)`` as the detector, plus the
    source file so identical methods in different files stay distinct.
    """
    return (
        record.get("source_file"),
        record.get("class_name"),
        record.get("signature"),
        record.get("line"),
    )


def _finding_to_record(finding: Dict[str, Any], source_file: str,
                       total_lines: int) -> Dict[str, Any]:
    """Convert a detector finding / analyze_methods record to a stored row."""
    class_name = finding.get("ClassName") or finding.get("class_name") or ""
    signature = finding.get("Signature") or finding.get("signature") or ""
    line = finding.get("Line")
    if line is None:
        line = finding.get("line")
    complexity = int(
        finding.get("Complexity")
        if finding.get("Complexity") is not None
        else finding.get("complexity")
    )

    severity_cap = finding.get("Severity") or finding.get("severity") or "Medium"
    severity_lower = str(severity_cap).lower()
    method_name = finding.get("MethodName") or finding.get("method_name") \
        or finding.get("Target") or signature.split("(", 1)[0]

    record = {
        # Fields consumed by the existing aggregation / charts.
        "module": Path(source_file).stem or class_name,
        "file": Path(source_file).name,
        "defect_count": 1,
        "lines_of_code": int(total_lines),
        "severity": severity_lower,
        "resolution_time": _RESOLUTION_TIME.get(severity_lower, 12),
        # Method-complexity details.
        "record_kind": COMPLEXITY_KIND,
        "source_file": source_file,
        "method_name": method_name,
        "class_name": class_name,
        "signature": signature,
        "line": int(line) if line is not None else None,
        "complexity": complexity,
        "severity_level": str(severity_cap),
        "type": finding.get("Type", "Method Complexity"),
        "category": finding.get("Category", "Complexity"),
    }
    return record


def append_complexity_findings(
    findings: List[Dict[str, Any]],
    source_file: str,
    total_lines: int = 0,
    path: Optional[os.PathLike] = None,
) -> List[Dict[str, Any]]:
    """
    Append method-complexity findings and return the stored records.

    Re-analysing the same ``source_file`` replaces its previous
    complexity records, and the
    ``(class name, signature, start line)`` triple is unique, so the
    existing detectors can never inflate the counts.  All pre-existing
    non-complexity records are preserved untouched.
    """
    target = resolve_store_path(path)
    new_records = [
        _finding_to_record(finding, source_file, total_lines)
        for finding in findings
    ]

    with _lock_for(target):
        existing = _read_unlocked(target)

        # Drop every previous complexity record for this source file...
        retained = [
            record for record in existing
            if not (
                is_complexity_record(record)
                and record.get("source_file") == source_file
            )
        ]

        # ...then add the new records, collapsing duplicate identity keys.
        unique: Dict[Any, Dict[str, Any]] = {}
        for record in new_records:
            unique[complexity_finding_key(record)] = record

        updated = retained + list(unique.values())
        if unique:
            _write_unlocked(target, updated)
        return list(unique.values())


def snapshot_summary(path: Optional[os.PathLike] = None) -> Dict[str, Any]:
    """
    Aggregate a snapshot into dashboard-friendly counters.

    Numbers computed here are derived from the same JSON document that the
    charts read, so page metrics and the file contents always agree.
    """
    records = complexity_records(read_snapshot(path))
    bands = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    max_complexity = 0

    for record in records:
        label = record.get("severity_level") or str(record.get("severity", "")).title()
        if label in bands:
            bands[label] += 1
        max_complexity = max(max_complexity, int(record.get("complexity", 0)))

    return {
        "total": len(records),
        "critical": bands["Critical"],
        "high": bands["High"],
        "medium": bands["Medium"],
        "low": bands["Low"],
        "max_complexity": max_complexity,
        "records": records,
    }
