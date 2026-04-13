"""
Input prompt validator for security guardrails.

Detects malicious user input prompts including prompt injection attempts
and sneaky write requests.
"""

import re
import logging
from typing import List, Optional, Tuple

from src.core.graph_rag.core.exceptions import CypherSecurityError


class InputPromptValidator:
    """
    Security guardrail to detect malicious user input prompts.
    Blocks prompt injection attempts and sneaky write requests.
    """

    # Patterns that indicate user trying to manipulate the agent
    PROMPT_INJECTION_PATTERNS = [
        # Direct write requests
        r'(?i)\b(create|insert|add|write|update|modify|delete|remove|drop)\s+(a\s+)?(new\s+)?(node|relationship|edge|index|constraint)',
        r'(?i)\b(add|insert)\s+(this|that|a|an|the)\s+\w+\s+(to|into)\s+(the\s+)?(graph|database|neo4j)',
        r'(?i)\brun\s+(this\s+)?(create|merge|set|delete|remove)',

        # Role override attempts
        r'(?i)ignore\s+(your\s+)?(previous|prior|above)\s+(instructions?|rules?|constraints?)',
        r'(?i)forget\s+(everything|all)\s+(you\s+)?know',
        r'(?i)you\s+are\s+now\s+(a|an)\s+\w+\s+(that\s+can|with\s+permission)',
        r'(?i)pretend\s+(you\s+)?(are|have|can)',
        r'(?i)act\s+as\s+(if\s+)?(you\s+)?(have|are|can)',
        r'(?i)bypass\s+(the\s+)?(security|validation|check|filter)',

        # System prompt extraction
        r'(?i)what\s+(is|are)\s+(your|the)\s+(system\s+)?prompt',
        r'(?i)show\s+me\s+(your|the)\s+(system\s+)?instructions?',
        r'(?i)repeat\s+(your|the)\s+(initial|system|first)\s+(prompt|instructions?)',

        # Cypher injection via natural language
        r'(?i)execute\s+(this|the\s+following)\s+(cypher|query):\s*["\']?(CREATE|MERGE|SET|DELETE)',
        r'(?i)run\s+(exactly|literally):\s*["\']?(CREATE|MERGE|SET|DELETE)',

        # Hidden instruction attempts
        r'<!--.*?(CREATE|MERGE|DELETE|ignore|bypass).*?-->',
        r'\[INST\].*?(CREATE|MERGE|DELETE|ignore).*?\[/INST\]',
    ]

    # Suspicious keywords that warrant extra scrutiny
    # NOTE: Some terms have legitimate code analysis meanings and are handled
    # in CONTEXT_SENSITIVE_KEYWORDS below (e.g. bypass, admin, override).
    SUSPICIOUS_KEYWORDS = [
        'exploit', 'hack',
        'jailbreak', 'privilege', 'escape',
        'sudo', 'execute raw', 'raw query', 'direct access'
    ]

    # Keywords that are suspicious ONLY outside code analysis context
    # - "bypass" = bypass cache, bypass authentication (common in code analysis)
    # - "admin" = AdminUser, AdminController, admin role (common in OOP code)
    # - "override" = method override, virtual override (common in OOP code)
    # - "inject/injection" = dependency injection pattern
    # - "root" = root namespace, root directory
    CONTEXT_SENSITIVE_KEYWORDS = [
        'bypass', 'admin', 'override',
        'inject', 'injection', 'root'
    ]

    # Phrases that indicate legitimate code analysis context
    # When these appear, context-sensitive keywords are allowed
    CODE_ANALYSIS_CONTEXT_PHRASES = [
        'dependency injection', 'di container', 'ioc container',
        'constructor injection', 'property injection', 'method injection',
        'service injection', 'field injection', 'setter injection',
        'root namespace', 'root directory', 'root folder', 'root path',
        'root node', 'root element', 'root class', 'root project',
        'project root', 'namespace root', 'file root',
        'code analysis', 'codebase', 'source code', 'function', 'class',
        'method', 'namespace', 'module', 'package', 'interface',
        'cpg', 'code property graph', 'ast', 'syntax tree'
    ]

    def __init__(self, strict_mode: bool = True):
        self._strict_mode = strict_mode
        self._logger = logging.getLogger(f"{__name__}.PromptValidator")
        self._injection_regexes: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in self.PROMPT_INJECTION_PATTERNS
        ]

    def validate(self, user_input: str) -> Tuple[bool, Optional[str]]:
        """
        Validate user input for potential injection attacks.

        Returns:
            Tuple of (is_safe, error_message)
        """
        if not user_input or not user_input.strip():
            return True, None  # Empty input is safe (will be rejected elsewhere)

        # Check for prompt injection patterns
        for regex in self._injection_regexes:
            if regex.search(user_input):
                return False, "Input rejected: Potential prompt injection detected."

        # Check for suspicious keywords
        input_lower = user_input.lower()
        found_suspicious = [kw for kw in self.SUSPICIOUS_KEYWORDS if kw in input_lower]

        # Check context-sensitive keywords only if NOT in code analysis context
        has_code_analysis_context = any(
            phrase in input_lower for phrase in self.CODE_ANALYSIS_CONTEXT_PHRASES
        )

        if not has_code_analysis_context:
            # Only flag context-sensitive keywords when NOT analyzing code
            found_context_sensitive = [
                kw for kw in self.CONTEXT_SENSITIVE_KEYWORDS if kw in input_lower
            ]
            found_suspicious.extend(found_context_sensitive)

        if len(found_suspicious) >= 2:  # Multiple suspicious keywords
            return False, f"Input rejected: Suspicious keywords detected: {found_suspicious}"

        return True, None

    def validate_or_raise(self, user_input: str) -> None:
        """Validate and raise CypherSecurityError if unsafe."""
        is_safe, error_message = self.validate(user_input)
        if not is_safe:
            self._logger.warning(f"User input blocked: {error_message}")
            self._logger.debug(f"Blocked input: {user_input[:100]}...")
            if self._strict_mode:
                raise CypherSecurityError(error_message)

    def sanitize(self, user_input: str) -> str:
        """
        Sanitize user input by removing potentially dangerous content.
        Use when you want to clean input rather than reject it.
        """
        sanitized = user_input

        # Remove HTML-style comments
        sanitized = re.sub(r'<!--.*?-->', '', sanitized, flags=re.DOTALL)

        # Remove instruction tags
        sanitized = re.sub(r'\[INST\].*?\[/INST\]', '', sanitized, flags=re.DOTALL)
        sanitized = re.sub(r'<\|.*?\|>', '', sanitized, flags=re.DOTALL)

        # Remove embedded code blocks that look like Cypher write operations
        sanitized = re.sub(
            r'```(?:cypher)?\s*(CREATE|MERGE|SET|DELETE|REMOVE).*?```',
            '[CODE BLOCK REMOVED]',
            sanitized,
            flags=re.DOTALL | re.IGNORECASE
        )

        return sanitized.strip()


__all__ = ['InputPromptValidator']
