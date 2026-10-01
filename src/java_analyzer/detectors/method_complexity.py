"""
Method-Level Cyclomatic Complexity Detector

Reports one finding per method that crosses the cyclomatic complexity
thresholds (10 / 20 / 40).  Findings are keyed by the tuple
(class name, signature, start line) so the same method can never be
counted twice when the detector is combined with the other detectors.
"""

from typing import List, Dict, Any, Optional, Iterable

import javalang

from detectors.base import CodeSmell


# Cyclomatic complexity thresholds.  A value *equal* to a threshold is
# promoted to the higher severity band.
MEDIUM_THRESHOLD = 10
HIGH_THRESHOLD = 20
CRITICAL_THRESHOLD = 40

# Threshold -> severity label used across the dashboard / JSON store.
SEVERITY_LOW = "Low"
SEVERITY_MEDIUM = "Medium"
SEVERITY_HIGH = "High"
SEVERITY_CRITICAL = "Critical"

COMPLEXITY_CATEGORY = "Complexity"
COMPLEXITY_TYPE = "Method Complexity"


def complexity_severity(complexity: int) -> str:
    """
    Map a cyclomatic complexity value to a severity band.

    Threshold boundaries are inclusive on the upper side, i.e. a method
    with complexity exactly 10/20/40 enters the higher band.
    """
    if complexity >= CRITICAL_THRESHOLD:
        return SEVERITY_CRITICAL
    if complexity >= HIGH_THRESHOLD:
        return SEVERITY_HIGH
    if complexity >= MEDIUM_THRESHOLD:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def calculate_method_complexity(method_node: javalang.tree.MethodDeclaration) -> int:
    """
    Calculate the cyclomatic complexity of a single method.

    The base complexity is 1 (the method itself) and one is added for each
    decision point.  The decision-point set matches the engine's existing
    metric calculation so dashboard metrics and detector findings never
    disagree.
    """
    branch_types = (
        javalang.tree.IfStatement,
        javalang.tree.WhileStatement,
        javalang.tree.DoStatement,
        javalang.tree.ForStatement,
        javalang.tree.CatchClause,
        javalang.tree.SwitchStatementCase,
        javalang.tree.TernaryExpression,
    )

    complexity = 1
    if method_node is None:
        return complexity
    for _, _ in method_node.filter(branch_types):
        complexity += 1
    return complexity


def _type_name(type_node) -> str:
    """Best-effort textual rendering of a javalang type reference."""
    if type_node is None:
        return ""
    name = getattr(type_node, "name", None)
    if name:
        return str(name)
    # javalang <0.13 models array types with a ``type`` attribute; newer
    # releases use ``component_type``.
    component = getattr(type_node, "component_type", None) or getattr(type_node, "type", None)
    return _type_name(component)


def build_method_signature(method_node: javalang.tree.MethodDeclaration) -> str:
    """Build a stable ``name(paramTypes)`` signature for a method node."""
    parameter_types = []
    for parameter in method_node.parameters or []:
        parameter_types.append(_type_name(parameter.type))
    return f"{method_node.name}({', '.join(parameter_types)})"


def method_start_line(method_node: javalang.tree.MethodDeclaration) -> Optional[int]:
    """Return the 1-based source line of a method declaration."""
    position = getattr(method_node, "position", None)
    if position is None:
        return None
    return int(position.line)


def _owning_classes(tree: javalang.tree.CompilationUnit) -> Iterable[Any]:
    """
    Yield type declarations whose methods are owned by the file.

    Only class declarations are inspected: the engine metric pipeline also
    counts methods on classes exclusively, and class-level information is
    used solely for ownership attribution.
    """
    for _, class_node in tree.filter(javalang.tree.ClassDeclaration):
        yield class_node


class MethodComplexityDetector(CodeSmell):
    """
    Method-level cyclomatic complexity detector.

    Emits a single ``Method Complexity`` finding for each method whose
    complexity is at least :data:`MEDIUM_THRESHOLD`.  Duplicate findings
    for the same ``(class name, signature, start line)`` triple are
    collapsed so combining this detector with the existing smell
    detectors cannot double-count a method.
    """

    def detect(self, tree: javalang.tree.CompilationUnit, lines: List[str]) -> List[Dict[str, Any]]:
        """Detect methods exceeding the cyclomatic complexity thresholds."""
        results: List[Dict[str, Any]] = []
        seen = set()

        for class_node in _owning_classes(tree):
            class_name = class_node.name
            for method_node in class_node.methods or []:
                record = self.analyze_method(method_node, class_name)
                if record is None:
                    continue
                key = (record["ClassName"], record["Signature"], record["Line"])
                if key in seen:
                    continue
                seen.add(key)
                results.append(record)

        return results

    def analyze_method(
        self,
        method_node: javalang.tree.MethodDeclaration,
        class_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Analyze a single method.

        Returns a finding dictionary when the method crosses the lowest
        threshold, otherwise ``None``.  An empty/abstract method body has
        no decision points and therefore complexity 1, yielding ``None``.
        """
        complexity = calculate_method_complexity(method_node)
        severity = complexity_severity(complexity)
        if severity == SEVERITY_LOW:
            return None

        signature = build_method_signature(method_node)
        line = method_start_line(method_node)
        method_name = method_node.name

        return self._create_issue(
            COMPLEXITY_TYPE,
            method_name,
            severity,
            f"Cyclomatic complexity: {complexity}",
            COMPLEXITY_CATEGORY,
            ClassName=class_name,
            MethodName=method_name,
            Signature=signature,
            Line=line,
            Complexity=complexity,
        )

    def _create_issue(self, smell_type: str, target: str, severity: str,
                      reason: str, category: str, **extra: Any) -> Dict[str, Any]:
        issue = super()._create_issue(smell_type, target, severity, reason, category)
        issue.update(extra)
        return issue
