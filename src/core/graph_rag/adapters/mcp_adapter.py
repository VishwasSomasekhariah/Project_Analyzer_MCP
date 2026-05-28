"""
MCP Cypher Adapter for the Graph RAG Multi-Agent system.

Adapts MCP session to DynamicSchemaManager interface for executing Cypher queries.
"""

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class MCPCypherAdapter:
    """Adapts MCP session to DynamicSchemaManager interface"""

    def __init__(self, mcp_session):
        """
        Initialize the adapter.

        Args:
            mcp_session: An active MCP session with neo4j_execute_query capability
        """
        self._session = mcp_session

    async def execute_query(self, query: str, params: Optional[dict] = None) -> Dict[str, Any]:
        """
        Execute a Cypher query via MCP.

        Args:
            query: The Cypher query to execute
            params: Optional query parameters (currently not used by MCP)

        Returns:
            Dict with 'data', 'status', and optional 'error' keys
        """
        try:
            result = await self._session.call_tool('neo4j_execute_query', {'query': query})
            if hasattr(result, 'content') and result.content:
                raw = json.loads(result.content[0].text)
                return {
                    'data': raw.get('results', raw.get('data', [])),
                    'status': 'success' if not raw.get('error') else 'error',
                    'error': raw.get('error')
                }
            return {'data': [], 'status': 'error', 'error': 'Empty response'}
        except Exception as e:
            logger.error(f"Query execution error: {e}")
            return {'data': [], 'status': 'error', 'error': str(e)}


__all__ = ['MCPCypherAdapter']
