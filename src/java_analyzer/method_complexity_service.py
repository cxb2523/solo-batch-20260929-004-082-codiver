"""
Resident method-complexity analysis service.

Exposes ``POST /api/method-complexity`` from inside the dashboard
process. The request body is ``{"file_path": "..."}``; the response
contains every method at/above the severity bands (10 / 20 / 40) with
method name, class name, start line, complexity and severity, and the
findings are appended (de-duplicated) into ``data/defect_data.json``.

Analysis strategy:
* The engine parses the file once and returns its AST; method bodies
  are taken directly from those already-parsed method nodes.
* Method-level secondary parsing only happens when a method lacks a
  usable start position, and it is limited to that method's owning
  class - the whole file is never re-scanned.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

import javalang

from analyzer_engine import StaticAnalyzerEngine
from detectors.method_complexity import (
    MethodComplexitySmells,
    cyclomatic_complexity,
    severity_for_complexity,
    build_signature,
    method_source_span,
)
from utils.defect_store import (
    append_method_complexity_records,
    build_record,
    load_snapshot,
)

API_ROUTE = "/api/method-complexity"


def analyze_file(
    file_path: str,
    *,
    data_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Analyze one Java file and persist method-complexity defects.

    Args:
        file_path: Absolute or relative path to a ``.java`` file.
        data_path: Override for the defect JSON (used by tests).

    Returns:
        ``{"file", "methods", "count"}`` where ``methods`` lists the
        structured findings.

    Raises:
        FileNotFoundError: The path does not exist.
        ValueError: The file is not Java or cannot be parsed.
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Java file not found: {file_path}")
    if path.suffix.lower() != ".java":
        raise ValueError(f"Not a Java source file: {file_path}")

    source = path.read_text(encoding="utf-8")
    lines = source.split("\n")

    # Single parse through the engine; its reconciled issues and AST are
    # both reused instead of parsing the file a second time.
    engine = StaticAnalyzerEngine(source)
    issues, tree = engine.run()

    findings = [
        issue
        for issue in issues
        if issue.get("Type") == "Method Complexity"
    ]
    findings = _fill_missing_positions(findings, tree, lines)

    methods = [_finding_to_response(finding) for finding in findings]

    records = [
        build_record(
            file=path.name,
            module=path.stem,
            method_name=finding["MethodName"],
            class_name=finding["ClassName"],
            signature=finding["Signature"],
            start_line=finding["StartLine"],
            complexity=finding["Complexity"],
            severity=finding["Severity"],
            lines_of_code=finding.get("MethodLines", 0),
        )
        for finding in findings
    ]
    if records:
        append_method_complexity_records(records, data_path=data_path)

    return {
        "file": str(path),
        "methods": methods,
        "count": len(methods),
    }


def _fill_missing_positions(
    findings: List[Dict[str, Any]],
    tree: javalang.tree.CompilationUnit,
    lines: List[str],
) -> List[Dict[str, Any]]:
    """
    Recover start lines / spans for findings missing position metadata.

    This is the only secondary parse path: it walks the already-parsed
    class used for attribution and re-inspects just that class's method
    nodes, never the entire file.
    """
    if findings and all(finding.get("StartLine") for finding in findings):
        return findings

    class_types = (
        javalang.tree.ClassDeclaration,
        javalang.tree.EnumDeclaration,
    )
    class_index = {}
    for _, class_node in tree.filter(class_types):
        class_index[class_node.name] = class_node

    repaired = []
    for finding in findings:
        if finding.get("StartLine"):
            repaired.append(finding)
            continue

        class_node = class_index.get(finding.get("ClassName"))
        if class_node is None:
            repaired.append(finding)
            continue

        for method_node in class_node.methods:
            if build_signature(method_node) != finding.get("Signature"):
                continue
            if method_node.position:
                finding["StartLine"] = method_node.position.line
                finding["MethodLines"] = method_source_span(method_node, lines)
            break
        repaired.append(finding)

    return repaired


def _finding_to_response(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Project an engine issue onto the stable API response shape."""
    return {
        "method_name": finding["MethodName"],
        "class_name": finding["ClassName"],
        "signature": finding["Signature"],
        "start_line": finding["StartLine"],
        "complexity": finding["Complexity"],
        "severity": finding["Severity"],
        "lines_of_code": finding.get("MethodLines", 0),
    }


class MethodComplexityHandler(BaseHTTPRequestHandler):
    """HTTP handler for the resident analysis service."""

    server_version = "CoDiverMethodComplexity/1.0"

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") == API_ROUTE:
            data_path = getattr(self.server, "data_path", None)
            records = load_snapshot(data_path)
            self._send_json(200, {"records": records, "count": len(records)})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") != API_ROUTE:
            self._send_json(404, {"error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw_body = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "Invalid JSON body"})
            return

        file_path = payload.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            self._send_json(
                400, {"error": "Missing 'file_path' in request body"}
            )
            return

        data_path = getattr(self.server, "data_path", None)
        try:
            result = analyze_file(file_path, data_path=data_path)
        except FileNotFoundError as error:
            self._send_json(404, {"error": str(error)})
            return
        except (ValueError, javalang.parser.JavaSyntaxError) as error:
            self._send_json(422, {"error": str(error)})
            return
        except OSError as error:
            self._send_json(500, {"error": f"OSError: {error}"})
        except Exception as error:  # pragma: no cover - safety net
            self._send_json(
                500,
                {
                    "error": f"{type(error).__name__}: {error}"
                },
            )
            return

        self._send_json(200, result)

    def log_message(self, format: str, *args: Any) -> None:
        """Keep the Streamlit console quiet."""
        return


class _DaemonThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded server whose worker threads never block shutdown."""

    daemon_threads = True
    allow_reuse_address = True


def create_server(
    port: int = 8765,
    *,
    data_path: Optional[Path] = None,
) -> _DaemonThreadingHTTPServer:
    """Create (but do not start) the HTTP service."""
    server = _DaemonThreadingHTTPServer(("127.0.0.1", port), MethodComplexityHandler)
    server.data_path = data_path  # type: ignore[attr-defined]
    return server
