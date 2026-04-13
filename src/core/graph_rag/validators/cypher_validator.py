"""
Cypher query validator for security guardrails.

Ensures only READ operations are executed against the graph database.
Blocks all write, update, and delete operations.
"""

import re
import logging
from typing import List, Optional, Tuple

from src.core.graph_rag.core.exceptions import CypherSecurityError


class CypherQueryValidator:
    """
    Security guardrail to ensure only READ operations are executed.
    Blocks all write, update, and delete operations on the graph.
    """

    # Dangerous Cypher keywords that modify the graph
    WRITE_KEYWORDS = frozenset([
        'CREATE',
        'MERGE',
        'SET',
        'DELETE',
        'DETACH DELETE',
        'REMOVE',
    ])

    # Schema modification keywords
    SCHEMA_KEYWORDS = frozenset([
        'CREATE INDEX',
        'CREATE CONSTRAINT',
        'DROP INDEX',
        'DROP CONSTRAINT',
        'DROP',
    ])

    # Administrative operations
    ADMIN_KEYWORDS = frozenset([
        'CALL dbms.',
        'CALL db.index.',
        'CALL db.constraint.',
        ':USE',
        ':BEGIN',
        ':COMMIT',
        ':ROLLBACK',
    ])

    # Potentially dangerous patterns (injection attempts)
    INJECTION_PATTERNS = [
        r';\s*(CREATE|MERGE|SET|DELETE|REMOVE|DROP)',  # Chained write commands
        r'\}\s*(CREATE|MERGE|SET|DELETE|REMOVE|DROP)',  # Breakout attempts
        r'UNION\s+ALL\s+(CREATE|MERGE|SET|DELETE)',  # UNION injection
        r'CALL\s*\{.*?(CREATE|MERGE|SET|DELETE)',  # Subquery write attempts
        r'FOREACH\s*\(.*?(CREATE|MERGE|SET|DELETE)',  # FOREACH write attempts
    ]

    def __init__(self, strict_mode: bool = True):
        """
        Initialize the validator.

        Args:
            strict_mode: If True, blocks ALL write operations.
                        If False, only logs warnings (not recommended for production).
        """
        self._strict_mode = strict_mode
        self._logger = logging.getLogger(f"{__name__}.CypherValidator")
        # Compile injection patterns for performance
        self._injection_regexes: List[re.Pattern] = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for pattern in self.INJECTION_PATTERNS
        ]

    def validate(self, query: str) -> Tuple[bool, Optional[str]]:
        """
        Validate a Cypher query for security.

        Args:
            query: The Cypher query string to validate

        Returns:
            Tuple of (is_safe, error_message)
            - is_safe: True if query is safe to execute
            - error_message: Description of security violation if unsafe, None otherwise
        """
        if not query or not query.strip():
            return False, "Empty query"

        # Normalize query for analysis
        normalized = self._normalize_query(query)

        # Check for write keywords
        violation = self._check_write_keywords(normalized)
        if violation:
            return False, violation

        # Check for schema modification keywords
        violation = self._check_schema_keywords(normalized)
        if violation:
            return False, violation

        # Check for admin operations
        violation = self._check_admin_keywords(normalized)
        if violation:
            return False, violation

        # Check for injection patterns
        violation = self._check_injection_patterns(query)
        if violation:
            return False, violation

        return True, None

    def _normalize_query(self, query: str) -> str:
        """Normalize query for keyword detection"""
        # Remove string literals to avoid false positives
        # Remove single-quoted strings
        normalized = re.sub(r"'[^']*'", "''", query)
        # Remove double-quoted strings
        normalized = re.sub(r'"[^"]*"', '""', normalized)
        # Remove backtick-quoted identifiers
        normalized = re.sub(r'`[^`]*`', '``', normalized)
        # Convert to uppercase for keyword matching
        return normalized.upper()

    def _check_write_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for write operation keywords"""
        for keyword in self.WRITE_KEYWORDS:
            # Use word boundary matching to avoid false positives
            pattern = r'\b' + keyword.replace(' ', r'\s+') + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Write operation '{keyword}' is not allowed. This system is read-only."

        return None

    def _check_schema_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for schema modification keywords"""
        for keyword in self.SCHEMA_KEYWORDS:
            pattern = r'\b' + keyword.replace(' ', r'\s+') + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Schema modification '{keyword}' is not allowed."

        return None

    def _check_admin_keywords(self, normalized_query: str) -> Optional[str]:
        """Check for administrative operation keywords"""
        for keyword in self.ADMIN_KEYWORDS:
            kw_upper = keyword.upper()
            # Use word-boundary / token-aware matching to avoid false positives
            # (e.g. ':USE' must not match inside ':USES_TYPE')
            if kw_upper.startswith(':'):
                # Colon-prefixed shell commands: match only when followed by
                # whitespace, end-of-string, or another non-word character
                # but NOT by a word character (letter/digit/underscore).
                pattern = re.escape(kw_upper) + r'(?!\w)'
            else:
                pattern = r'\b' + re.escape(kw_upper) + r'\b'
            if re.search(pattern, normalized_query):
                return f"SECURITY VIOLATION: Administrative operation '{keyword}' is not allowed."

        return None

    def _check_injection_patterns(self, original_query: str) -> Optional[str]:
        """Check for potential injection attack patterns"""
        for regex in self._injection_regexes:
            if regex.search(original_query):
                return "SECURITY VIOLATION: Potential injection attack detected. Query contains suspicious patterns."

        return None

    def validate_or_raise(self, query: str) -> None:
        """
        Validate query and raise CypherSecurityError if unsafe.

        Args:
            query: The Cypher query to validate

        Raises:
            CypherSecurityError: If the query is not safe
        """
        is_safe, error_message = self.validate(query)
        if not is_safe:
            self._logger.error(f"Query blocked: {error_message}")
            self._logger.debug(f"Blocked query: {query[:200]}...")
            if self._strict_mode:
                raise CypherSecurityError(error_message)
            else:
                self._logger.warning(f"Non-strict mode: {error_message}")


__all__ = ['CypherQueryValidator']
