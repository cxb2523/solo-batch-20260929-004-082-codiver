"""
Static Analyzer Engine
Core logic for AST parsing and metric calculation
"""

import javalang
from typing import List, Dict, Any, Tuple
from detectors.base import CodeSmell
from detectors.design import DesignSmells
from detectors.implementation import ImplementationSmells
from detectors.naming_docs import NamingSmells, DocumentationSmells
from detectors.method_complexity import (
    MethodComplexityDetector,
    calculate_method_complexity,
    build_method_signature,
    method_start_line,
    complexity_severity,
)
from utils.helpers import count_blank_lines, count_comment_lines


class StaticAnalyzerEngine:
    """
    Main analyzer engine that orchestrates all code smell detectors
    and calculates comprehensive code metrics.
    """
    
    def __init__(self, code: str, config: Dict[str, bool] = None):
        """
        Initialize the analyzer engine.
        
        Args:
            code: Java source code as a string
            config: Dictionary specifying which detectors to enable
        """
        self.code = code
        self.lines = code.split('\n')
        self.config = config or {
            'design': True,
            'implementation': True,
            'naming': True,
            'documentation': True,
            'complexity': True,
        }
        # Most recently parsed tree.  Method-level analysis reuses this
        # result whenever it is still available; only a missing tree
        # triggers a method-level second parse.
        self.tree = None
        self.detectors: List[CodeSmell] = self._initialize_detectors()
    
    def _initialize_detectors(self) -> List[CodeSmell]:
        """
        Initialize all detector instances based on configuration.
        
        Returns:
            List of code smell detector instances
        """
        detectors = []
        if self.config.get('design', True):
            detectors.append(DesignSmells())
        if self.config.get('implementation', True):
            detectors.append(ImplementationSmells())
        if self.config.get('naming', True):
            detectors.append(NamingSmells())
        if self.config.get('documentation', True):
            detectors.append(DocumentationSmells())
        if self.config.get('complexity', True):
            detectors.append(MethodComplexityDetector())
        return detectors
    
    def run(self) -> Tuple[List[Dict[str, Any]], javalang.tree.CompilationUnit]:
        """
        Run the complete analysis pipeline.
        
        Returns:
            Tuple of (list of detected issues, parsed AST tree)
            
        Raises:
            ValueError: If syntax error or parsing fails
        """
        try:
            # Parse the Java source code into an AST
            tree = javalang.parse.parse(self.code)
            self.tree = tree
            
            # Run all detectors
            all_issues = []
            for detector in self.detectors:
                issues = detector.detect(tree, self.lines)
                all_issues.extend(issues)
            
            return all_issues, tree
            
        except javalang.parser.JavaSyntaxError as e:
            raise ValueError(f"Syntax Error at {e.at}: {e.description}")
        except Exception as e:
            raise ValueError(f"AST Analysis Failed: {str(e)}")
    
    def calculate_metrics(self, tree: javalang.tree.CompilationUnit) -> Dict[str, Any]:
        """
        Calculate comprehensive code metrics from the AST.
        
        Args:
            tree: Parsed Java AST
            
        Returns:
            Dictionary containing various code metrics
        """
        metrics = {
            'total_classes': 0,
            'total_methods': 0,
            'total_fields': 0,
            'total_lines': len(self.lines),
            'blank_lines': count_blank_lines(self.lines),
            'comment_lines': count_comment_lines(self.lines),
            'avg_method_length': 0,
            'max_method_length': 0,
            'avg_complexity': 0,
            'max_complexity': 0,
            'code_lines': 0
        }
        
        method_lengths = []
        complexities = []
        
        # Analyze classes
        for _, node in tree.filter(javalang.tree.ClassDeclaration):
            metrics['total_classes'] += 1
            
            # Count methods
            if node.methods:
                metrics['total_methods'] += len(node.methods)
                
                for method in node.methods:
                    # Calculate method length
                    if method.body:
                        length = len(method.body)
                        method_lengths.append(length)
                        
                        # Calculate cyclomatic complexity
                        complexity = self._calculate_complexity(method)
                        complexities.append(complexity)
            
            # Count fields
            if node.fields:
                metrics['total_fields'] += len(node.fields)
        
        # Calculate averages
        if method_lengths:
            metrics['avg_method_length'] = sum(method_lengths) / len(method_lengths)
            metrics['max_method_length'] = max(method_lengths)
        
        if complexities:
            metrics['avg_complexity'] = sum(complexities) / len(complexities)
            metrics['max_complexity'] = max(complexities)
        
        # Calculate code lines (excluding blanks and comments)
        metrics['code_lines'] = (metrics['total_lines'] - 
                                 metrics['blank_lines'] - 
                                 metrics['comment_lines'])
        
        return metrics
    
    def analyze_methods(self, tree: javalang.tree.CompilationUnit = None) -> List[Dict[str, Any]]:
        """
        Analyze cyclomatic complexity at the method level.
        
        The already-parsed engine tree is reused when available; only when
        no tree exists is a method-level parse performed.  Class
        declarations are traversed purely to attribute each method to its
        owning class - the file is never re-scanned by every detector.

        Args:
            tree: Optional pre-parsed AST.  Falls back to the tree
                produced by :meth:`run`, then to a fresh parse.
            
        Returns:
            One record per method with keys: method_name, class_name,
            signature, line, complexity, severity.
        """
        tree = tree or self.tree or javalang.parse.parse(self.code)
        self.tree = tree

        records: List[Dict[str, Any]] = []
        for _, class_node in tree.filter(javalang.tree.ClassDeclaration):
            for method_node in class_node.methods or []:
                complexity = calculate_method_complexity(method_node)
                records.append({
                    'method_name': method_node.name,
                    'class_name': class_node.name,
                    'signature': build_method_signature(method_node),
                    'line': method_start_line(method_node),
                    'complexity': complexity,
                    'severity': complexity_severity(complexity),
                })
        return records

    def _calculate_complexity(self, method_node: javalang.tree.MethodDeclaration) -> int:
        """Calculate cyclomatic complexity for a method (shared implementation)."""
        return calculate_method_complexity(method_node)
