"""Code smell detector package."""

from detectors.base import CodeSmell
from detectors.design import DesignSmells
from detectors.implementation import ImplementationSmells
from detectors.naming_docs import NamingSmells, DocumentationSmells
from detectors.method_complexity import MethodComplexitySmells

__all__ = [
    "CodeSmell",
    "DesignSmells",
    "ImplementationSmells",
    "NamingSmells",
    "DocumentationSmells",
    "MethodComplexitySmells",
]
