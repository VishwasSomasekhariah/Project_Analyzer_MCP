"""
Code Content Analyzer for Advanced Graph RAG
Parse and analyze retrieved code content based on query intent
"""

import re
import json
from typing import Dict, List, Any, Optional, Tuple
import ast
import logging


class CodeContentAnalyzer:
    """Parse and analyze retrieved code content for specific analysis types"""
    
    def __init__(self):
        # Comment patterns for different languages
        self.comment_patterns = {
            "single_line": [
                r'//.*$',           # C#, Java, JavaScript, TypeScript
                r'#.*$',            # Python, Shell
                r'%.*$',            # MATLAB
                r'--.*$'            # SQL, Haskell
            ],
            "multi_line": [
                r'/\*.*?\*/',       # C#, Java, JavaScript, C/C++
                r'""".*?"""',       # Python docstrings
                r"'''.*?'''",       # Python docstrings
                r'<!--.*?-->',      # HTML, XML
                r'\(\*.*?\*\)'      # Pascal, OCaml
            ]
        }
        
        # Code structure patterns
        self.structure_patterns = {
            "methods": [
                r'(?:public|private|protected|internal)?\s*(?:static\s+)?(?:virtual\s+)?(?:override\s+)?[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*{',  # C# methods
                r'def\s+(\w+)\s*\([^)]*\):',  # Python functions
                r'function\s+(\w+)\s*\([^)]*\)\s*{',  # JavaScript functions
                r'(\w+)\s*:\s*function\s*\([^)]*\)\s*{',  # JavaScript object methods
                r'(?:public|private|protected)?\s*[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*{',  # Java methods
            ],
            "classes": [
                r'(?:public|internal|private|protected)?\s*(?:abstract\s+)?(?:sealed\s+)?class\s+(\w+)',  # C# classes
                r'class\s+(\w+)(?:\([^)]*\))?:',  # Python classes
                r'class\s+(\w+)\s*{',  # JavaScript classes
                r'(?:public|private|protected)?\s*(?:abstract\s+)?(?:final\s+)?class\s+(\w+)',  # Java classes
            ],
            "interfaces": [
                r'(?:public|internal|private|protected)?\s*interface\s+(\w+)',  # C#, Java interfaces
                r'interface\s+(\w+)\s*{',  # TypeScript interfaces
            ],
            "variables": [
                r'(?:public|private|protected|internal)?\s*(?:static\s+)?(?:readonly\s+)?[\w<>\[\]]+\s+(\w+)\s*[=;]',  # C# fields
                r'(\w+)\s*=\s*[^;]+',  # General assignments
                r'(?:var|let|const)\s+(\w+)',  # JavaScript variables
            ],
            "loops": [
                r'foreach\s*\([^)]+\)',  # C# foreach
                r'for\s*\([^)]+\)',      # C/C#/Java/JavaScript for
                r'while\s*\([^)]+\)',    # while loops
                r'for\s+\w+\s+in\s+',    # Python for loops
                r'while\s+.+:',          # Python while loops
            ]
        }
        
        # Language detection patterns
        self.language_indicators = {
            "csharp": [r'\busing\s+\w+', r'\bnamespace\s+\w+', r'\bpublic\s+class', r'Console\.WriteLine'],
            "java": [r'\bimport\s+\w+', r'\bpublic\s+class', r'System\.out\.println'],
            "python": [r'\bimport\s+\w+', r'\bdef\s+\w+', r'\bclass\s+\w+.*:'],
            "javascript": [r'\bfunction\s+\w+', r'\bconsole\.log', r'\bvar\s+\w+', r'\blet\s+\w+'],
            "typescript": [r'\binterface\s+\w+', r':\s*\w+\s*=', r'\bexport\s+']
        }
    
    async def analyze_for_intent(self, content: str, intent: str, concepts: List[str], entities: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Analyze code content based on query intent and concepts
        
        Args:
            content: Code content to analyze (body property from graph nodes)
            intent: Query intent (count_analysis, structural_analysis, etc.)
            concepts: List of concepts from entity extraction
            entities: Optional entity context
            
        Returns:
            {
                "analysis_type": str,
                "results": {...},  # Intent-specific results
                "metadata": {...},
                "language": str,
                "confidence": float
            }
        """
        if not content or not isinstance(content, str):
            return {
                "analysis_type": intent,
                "results": {},
                "metadata": {"error": "No content provided or invalid content type"},
                "language": "unknown",
                "confidence": 0.0
            }
        
        # Detect programming language
        detected_language = self._detect_language(content)
        
        # Route to appropriate analysis method
        if intent == "count_analysis":
            analysis_results = await self._analyze_for_counting(content, concepts, detected_language)
        elif intent == "structural_analysis":
            analysis_results = await self._analyze_for_structure(content, concepts, detected_language)
        elif intent == "relationship_analysis":
            analysis_results = await self._analyze_for_relationships(content, concepts, detected_language)
        elif intent == "behavioral_analysis":
            analysis_results = await self._analyze_for_behavior(content, concepts, detected_language)
        else:
            analysis_results = await self._analyze_general(content, detected_language)
        
        return {
            "analysis_type": intent,
            "results": analysis_results,
            "metadata": {
                "content_length": len(content),
                "line_count": len(content.split('\n')),
                "language": detected_language,
                "concepts_analyzed": concepts
            },
            "language": detected_language,
            "confidence": analysis_results.get("confidence", 0.7)
        }
    
    async def _analyze_for_counting(self, content: str, concepts: List[str], language: str) -> Dict[str, Any]:
        """Analyze content for counting-based queries"""
        results = {"confidence": 0.8}
        
        # Count comment lines
        if any("comment" in concept.lower() for concept in concepts):
            comment_count = self._count_comments(content, language)
            results["comment_lines"] = comment_count["total_lines"]
            results["comment_details"] = comment_count
        
        # Count method calls
        if any("method call" in concept.lower() or "call" in concept.lower() for concept in concepts):
            method_calls = self._count_method_calls(content, language)
            results["method_calls"] = method_calls["total_calls"]
            results["method_call_details"] = method_calls
        
        # Count loops
        if any("loop" in concept.lower() or "foreach" in concept.lower() for concept in concepts):
            loop_count = self._count_loops(content, language)
            results["loops"] = loop_count["total_loops"]
            results["loop_details"] = loop_count
        
        # Count methods/functions
        if any("method" in concept.lower() or "function" in concept.lower() for concept in concepts):
            method_count = self._count_methods(content, language)
            results["methods"] = method_count["total_methods"]
            results["method_details"] = method_count
        
        # Count variables/fields
        if any("variable" in concept.lower() or "field" in concept.lower() for concept in concepts):
            variable_count = self._count_variables(content, language)
            results["variables"] = variable_count["total_variables"]
            results["variable_details"] = variable_count
        
        return results
    
    async def _analyze_for_structure(self, content: str, concepts: List[str], language: str) -> Dict[str, Any]:
        """Analyze content for structural queries"""
        results = {"confidence": 0.7}
        
        # Extract method signatures
        methods = self._extract_methods(content, language)
        results["methods"] = methods
        
        # Extract class structure
        classes = self._extract_classes(content, language)
        results["classes"] = classes
        
        # Extract interfaces
        interfaces = self._extract_interfaces(content, language)
        results["interfaces"] = interfaces
        
        # Extract variables/fields
        variables = self._extract_variables(content, language)
        results["variables"] = variables
        
        return results
    
    async def _analyze_for_relationships(self, content: str, concepts: List[str], language: str) -> Dict[str, Any]:
        """Analyze content for relationship queries"""
        results = {"confidence": 0.6}
        
        # Extract method calls
        method_calls = self._extract_method_calls(content, language)
        results["method_calls"] = method_calls
        
        # Extract inheritance/implementation relationships
        inheritance = self._extract_inheritance_info(content, language)
        results["inheritance"] = inheritance
        
        # Extract dependencies (using statements, imports)
        dependencies = self._extract_dependencies(content, language)
        results["dependencies"] = dependencies
        
        return results
    
    async def _analyze_for_behavior(self, content: str, concepts: List[str], language: str) -> Dict[str, Any]:
        """Analyze content for behavioral queries"""
        results = {"confidence": 0.6}
        
        # Extract control flow patterns
        control_flow = self._extract_control_flow(content, language)
        results["control_flow"] = control_flow
        
        # Extract method call sequences
        call_sequences = self._extract_call_sequences(content, language)
        results["call_sequences"] = call_sequences
        
        return results
    
    async def _analyze_general(self, content: str, language: str) -> Dict[str, Any]:
        """General analysis for unknown intents"""
        results = {"confidence": 0.5}
        
        # Basic code metrics
        results["metrics"] = {
            "lines_of_code": len([line for line in content.split('\n') if line.strip()]),
            "total_lines": len(content.split('\n')),
            "characters": len(content)
        }
        
        # Basic structure extraction
        results["structure"] = {
            "methods": len(self._extract_methods(content, language)),
            "classes": len(self._extract_classes(content, language)),
            "variables": len(self._extract_variables(content, language))
        }
        
        return results
    
    def _detect_language(self, content: str) -> str:
        """Detect programming language from code content"""
        scores = {}
        
        for language, patterns in self.language_indicators.items():
            score = 0
            for pattern in patterns:
                matches = len(re.findall(pattern, content, re.IGNORECASE | re.MULTILINE))
                score += matches
            scores[language] = score
        
        if not scores or max(scores.values()) == 0:
            return "unknown"
        
        return max(scores, key=scores.get)
    
    def _count_comments(self, content: str, language: str) -> Dict[str, Any]:
        """Count comment lines in code"""
        single_line_comments = 0
        multi_line_comments = 0
        comment_blocks = []
        
        # Count single-line comments
        for pattern in self.comment_patterns["single_line"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                single_line_comments += 1
                comment_blocks.append({
                    "type": "single_line",
                    "content": match.group().strip(),
                    "line": content[:match.start()].count('\n') + 1
                })
        
        # Count multi-line comments
        for pattern in self.comment_patterns["multi_line"]:
            matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)
            for match in matches:
                comment_content = match.group()
                line_count = comment_content.count('\n') + 1
                multi_line_comments += line_count
                comment_blocks.append({
                    "type": "multi_line",
                    "content": comment_content.strip(),
                    "start_line": content[:match.start()].count('\n') + 1,
                    "line_count": line_count
                })
        
        return {
            "total_lines": single_line_comments + multi_line_comments,
            "single_line_comments": single_line_comments,
            "multi_line_comments": multi_line_comments,
            "comment_blocks": comment_blocks
        }
    
    def _count_method_calls(self, content: str, language: str) -> Dict[str, Any]:
        """Count method calls in code"""
        # General method call pattern (works for most languages)
        call_patterns = [
            r'\b(\w+)\s*\([^)]*\)',  # Simple method calls
            r'(\w+)\.(\w+)\s*\([^)]*\)',  # Method calls on objects
            r'(\w+)::(\w+)\s*\([^)]*\)',  # Static method calls (C++/C#)
        ]
        
        method_calls = []
        total_calls = 0
        
        for pattern in call_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                total_calls += 1
                line_num = content[:match.start()].count('\n') + 1
                
                if '.' in match.group() or '::' in match.group():
                    # Object/static method call
                    parts = re.split(r'[.:]', match.group())
                    if len(parts) >= 2:
                        object_name = parts[0].strip()
                        method_name = parts[1].split('(')[0].strip()
                        method_calls.append({
                            "object": object_name,
                            "method": method_name,
                            "full_call": match.group().strip(),
                            "line": line_num
                        })
                else:
                    # Simple method call
                    method_name = match.group(1) if match.groups() else match.group().split('(')[0]
                    method_calls.append({
                        "method": method_name,
                        "full_call": match.group().strip(),
                        "line": line_num
                    })
        
        return {
            "total_calls": total_calls,
            "method_calls": method_calls
        }
    
    def _count_loops(self, content: str, language: str) -> Dict[str, Any]:
        """Count loops in code"""
        loops = []
        total_loops = 0
        
        for pattern in self.structure_patterns["loops"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                total_loops += 1
                line_num = content[:match.start()].count('\n') + 1
                
                # Determine loop type
                loop_text = match.group().strip()
                if loop_text.startswith('foreach'):
                    loop_type = 'foreach'
                elif loop_text.startswith('for'):
                    loop_type = 'for'
                elif loop_text.startswith('while'):
                    loop_type = 'while'
                else:
                    loop_type = 'unknown'
                
                loops.append({
                    "type": loop_type,
                    "definition": loop_text,
                    "line": line_num
                })
        
        return {
            "total_loops": total_loops,
            "loops": loops
        }
    
    def _count_methods(self, content: str, language: str) -> Dict[str, Any]:
        """Count methods/functions in code"""
        methods = []
        total_methods = 0
        
        for pattern in self.structure_patterns["methods"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                total_methods += 1
                method_name = match.group(1) if match.groups() else "unknown"
                line_num = content[:match.start()].count('\n') + 1
                
                methods.append({
                    "name": method_name,
                    "definition": match.group().strip(),
                    "line": line_num
                })
        
        return {
            "total_methods": total_methods,
            "methods": methods
        }
    
    def _count_variables(self, content: str, language: str) -> Dict[str, Any]:
        """Count variables/fields in code"""
        variables = []
        total_variables = 0
        
        for pattern in self.structure_patterns["variables"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                total_variables += 1
                var_name = match.group(1) if match.groups() else "unknown"
                line_num = content[:match.start()].count('\n') + 1
                
                variables.append({
                    "name": var_name,
                    "definition": match.group().strip(),
                    "line": line_num
                })
        
        return {
            "total_variables": total_variables,
            "variables": variables
        }
    
    def _extract_methods(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract method signatures and details"""
        return self._count_methods(content, language)["methods"]
    
    def _extract_classes(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract class definitions"""
        classes = []
        
        for pattern in self.structure_patterns["classes"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                class_name = match.group(1) if match.groups() else "unknown"
                line_num = content[:match.start()].count('\n') + 1
                
                classes.append({
                    "name": class_name,
                    "definition": match.group().strip(),
                    "line": line_num
                })
        
        return classes
    
    def _extract_interfaces(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract interface definitions"""
        interfaces = []
        
        for pattern in self.structure_patterns["interfaces"]:
            matches = re.finditer(pattern, content, re.MULTILINE)
            for match in matches:
                interface_name = match.group(1) if match.groups() else "unknown"
                line_num = content[:match.start()].count('\n') + 1
                
                interfaces.append({
                    "name": interface_name,
                    "definition": match.group().strip(),
                    "line": line_num
                })
        
        return interfaces
    
    def _extract_variables(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract variable definitions"""
        return self._count_variables(content, language)["variables"]
    
    def _extract_method_calls(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract method call details"""
        return self._count_method_calls(content, language)["method_calls"]
    
    def _extract_inheritance_info(self, content: str, language: str) -> Dict[str, Any]:
        """Extract inheritance and implementation information"""
        inheritance_info = {
            "inherits_from": [],
            "implements": []
        }
        
        # C# inheritance patterns
        inherits_pattern = r'class\s+\w+\s*:\s*(\w+)'
        implements_pattern = r'class\s+\w+\s*:\s*[^{]*?(\w+Interface|\bI\w+)'
        
        # Find inheritance
        inherits_matches = re.finditer(inherits_pattern, content, re.MULTILINE)
        for match in inherits_matches:
            base_class = match.group(1)
            if not base_class.startswith('I'):  # Not an interface
                inheritance_info["inherits_from"].append(base_class)
        
        # Find interface implementations
        implements_matches = re.finditer(implements_pattern, content, re.MULTILINE)
        for match in implements_matches:
            interface_name = match.group(1)
            inheritance_info["implements"].append(interface_name)
        
        return inheritance_info
    
    def _extract_dependencies(self, content: str, language: str) -> List[str]:
        """Extract using statements/imports"""
        dependencies = []
        
        # Different patterns for different languages
        dependency_patterns = {
            "csharp": r'using\s+([\w.]+);',
            "java": r'import\s+([\w.]+);',
            "python": r'(?:from\s+[\w.]+\s+)?import\s+([\w.]+)',
            "javascript": r'import\s+.*from\s+[\'"]([^\'"]+)[\'"]'
        }
        
        pattern = dependency_patterns.get(language, dependency_patterns["csharp"])
        matches = re.finditer(pattern, content, re.MULTILINE)
        
        for match in matches:
            dependencies.append(match.group(1))
        
        return dependencies
    
    def _extract_control_flow(self, content: str, language: str) -> Dict[str, Any]:
        """Extract control flow patterns"""
        control_flow = {
            "conditionals": [],
            "loops": [],
            "try_catch": []
        }
        
        # Find if/else statements
        if_pattern = r'if\s*\([^)]+\)'
        if_matches = re.finditer(if_pattern, content, re.MULTILINE)
        for match in matches:
            line_num = content[:match.start()].count('\n') + 1
            control_flow["conditionals"].append({
                "type": "if",
                "condition": match.group().strip(),
                "line": line_num
            })
        
        # Find try/catch blocks
        try_pattern = r'try\s*{'
        try_matches = re.finditer(try_pattern, content, re.MULTILINE)
        for match in try_matches:
            line_num = content[:match.start()].count('\n') + 1
            control_flow["try_catch"].append({
                "type": "try",
                "line": line_num
            })
        
        # Add loop information
        control_flow["loops"] = self._count_loops(content, language)["loops"]
        
        return control_flow
    
    def _extract_call_sequences(self, content: str, language: str) -> List[Dict[str, Any]]:
        """Extract method call sequences within methods"""
        # This is a simplified implementation
        # In a full implementation, this would parse the AST to get accurate call sequences
        method_calls = self._extract_method_calls(content, language)
        
        # Group calls by approximate method context (simplified)
        call_sequences = []
        current_sequence = []
        last_line = 0
        
        for call in method_calls:
            if call["line"] - last_line > 5:  # New method context (rough heuristic)
                if current_sequence:
                    call_sequences.append(current_sequence)
                current_sequence = [call]
            else:
                current_sequence.append(call)
            last_line = call["line"]
        
        if current_sequence:
            call_sequences.append(current_sequence)
        
        return call_sequences