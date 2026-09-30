"""
Method-Level Cyclomatic Complexity Detector

Produces one defect per method whose cyclomatic complexity reaches the
severity thresholds (10 / 20 / 40). Every issue carries structured
fields (class name, signature, start line, complexity) so downstream
consumers (engine de-duplication, persistent storage, dashboard) can
rely on a stable identity: ``(ClassName, Signature, StartLine)``.
"""

from typing import List, Dict, Any, Optional

import javalang

from detectors.base import CodeSmell

# Severity bands. Complexity exactly equal to a threshold enters the
# higher band (>=), so 10 -> Medium, 20 -> High, 40 -> Critical.
MEDIUM_THRESHOLD = 10
HIGH_THRESHOLD = 20
CRITICAL_THRESHOLD = 40

ISSUE_TYPE = "Method Complexity"
ISSUE_CATEGORY = "Implementation"

# Branch node types contributing one independent path each. Kept in
# sync with StaticAnalyzerEngine._calculate_complexity so dashboard
# metrics and detector results never disagree.
BRANCH_TYPES = (
    javalang.tree.IfStatement,
    javalang.tree.WhileStatement,
    javalang.tree.DoStatement,
    javalang.tree.ForStatement,
    javalang.tree.CatchClause,
    javalang.tree.SwitchStatementCase,
    javalang.tree.TernaryExpression,
)


def cyclomatic_complexity(method_node) -> int:
    """
    Count cyclomatic complexity for a single method AST node.

    Base complexity is 1; every branch construct adds 1. A method with
    no body (abstract / interface / native) scores 1 but is never
    reported as a defect.
    """
    count = 1
    for _, node in method_node:
        if isinstance(node, BRANCH_TYPES):
            count += 1
    return count


def severity_for_complexity(complexity: int) -> Optional[str]:
    """Map a complexity value to its severity band (None if below 10)."""
    if complexity >= CRITICAL_THRESHOLD:
        return "Critical"
    if complexity >= HIGH_THRESHOLD:
        return "High"
    if complexity >= MEDIUM_THRESHOLD:
        return "Medium"
    return None


def build_signature(method_node) -> str:
    """Build a compact ``name(paramTypes)`` signature for a method."""
    param_types = []
    for parameter in method_node.parameters:
        type_node = parameter.type
        if isinstance(type_node, javalang.tree.BasicType):
            param_types.append(type_node.name)
        else:
            param_types.append(getattr(type_node, "name", str(type_node)))
    return f"{method_node.name}({', '.join(param_types)})"


def method_source_span(method_node, lines: List[str]) -> int:
    """
    Count the number of source lines covered by a method.

    Braces are scanned from the method declaration line so nested
    strings/chars/braces do not confuse the end-of-body detection.
    Falls back to the statement count when the body brace cannot be
    located (e.g. abstract methods).
    """
    position = getattr(method_node, "position", None)
    if position is None:
        return len(method_node.body) if method_node.body else 0

    start_index = position.line - 1
    depth = 0
    opened = False
    in_block_comment = False

    for index in range(start_index, len(lines)):
        line = lines[index]
        in_string = False
        in_char = False
        escaped = False
        cursor = 0
        while cursor < len(line):
            char = line[cursor]
            next_char = line[cursor + 1] if cursor + 1 < len(line) else ""

            if in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    cursor += 2
                    continue
                cursor += 1
                continue
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                cursor += 1
                continue
            if in_char:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "'":
                    in_char = False
                cursor += 1
                continue

            if char == "/" and next_char == "/":
                break
            if char == "/" and next_char == "*":
                in_block_comment = True
                cursor += 2
                continue
            if char == '"':
                in_string = True
            elif char == "'":
                in_char = True
            elif char == "{":
                depth += 1
                opened = True
            elif char == "}":
                depth -= 1
                if opened and depth == 0:
                    return index - start_index + 1
            cursor += 1

    return len(method_node.body) if method_node.body else 0


class MethodComplexitySmells(CodeSmell):
    """
    Detects method-level cyclomatic complexity defects.

    Class declarations are only traversed to attribute methods to their
    owning class; complexity is measured on the already-parsed method
    nodes, so no full-file re-scan happens.
    """

    def detect(self, tree: javalang.tree.CompilationUnit,
               source_lines: List[str]) -> List[Dict[str, Any]]:
        """Return one issue per method at/above the lowest threshold."""
        results = []
        seen_keys = set()

        declaration_types = (
            javalang.tree.ClassDeclaration,
            javalang.tree.EnumDeclaration,
        )
        for _, class_node in tree:
            if not isinstance(class_node, declaration_types):
                continue
            class_name = class_node.name
            for method_node in class_node.methods:
                issue = self._inspect_method(method_node, class_name, source_lines)
                if issue is None:
                    continue
                key = (
                    issue["ClassName"],
                    issue["Signature"],
                    issue["StartLine"],
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                results.append(issue)

        return results

    def _inspect_method(self, method_node, class_name: str,
                        lines: List[str]) -> Optional[Dict[str, Any]]:
        """Build the issue dict for one method, or None when below band."""
        # Methods without a body (abstract / interface / native) have no
        # branches and can never reach the lowest threshold.
        if not method_node.body:
            return None

        complexity = cyclomatic_complexity(method_node)
        severity = severity_for_complexity(complexity)
        if severity is None:
            return None

        signature = build_signature(method_node)
        start_line = method_node.position.line if method_node.position else 0

        return self._create_issue(
            ISSUE_TYPE,
            f"{class_name}.{method_node.name}",
            severity,
            f"Cyclomatic complexity: {complexity}",
            ISSUE_CATEGORY,
            ClassName=class_name,
            MethodName=method_node.name,
            Signature=signature,
            StartLine=start_line,
            Complexity=complexity,
            MethodLines=method_source_span(method_node, lines),
        )
