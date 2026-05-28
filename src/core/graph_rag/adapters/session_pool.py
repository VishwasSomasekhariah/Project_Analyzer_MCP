"""
MCP Session Pool for the Graph RAG Multi-Agent system.

Manages multiple MCP sessions for parallel agent execution.
Each parallel CoT agent gets its own session to prevent SSE stream conflicts.
"""

import asyncio
import json
import logging
import tempfile
from typing import Any, Dict, Optional, Tuple

from mcp_use import MCPClient, MCPSession
from mcp_use.connectors.http import HttpConnector


class MCPSessionPool:
    """
    Manages multiple MCP sessions for parallel agent execution.
    Each parallel CoT agent gets its own session to prevent SSE stream conflicts.
    """

    def __init__(self, mcp_config_dict: Dict[str, Any], sse_timeout: int = 3600):
        """
        Initialize the session pool.

        Args:
            mcp_config_dict: MCP configuration dictionary with mcpServers
            sse_timeout: SSE read timeout in seconds (default: 3600 = 1 hour)
        """
        self._config_dict = mcp_config_dict
        self._server_name = list(mcp_config_dict.get('mcpServers', {}).keys())[0]
        self._server_config = mcp_config_dict['mcpServers'][self._server_name]
        self._sse_timeout = sse_timeout
        self._active_sessions: Dict[str, Any] = {}  # session_id -> (client, session)
        self._logger = logging.getLogger(f"{__name__}.MCPSessionPool")

        self._logger.info(f"MCPSessionPool initialized with SSE timeout: {sse_timeout}s")

    async def acquire_session(self, session_id: Optional[str] = None) -> Tuple[str, Any]:
        """
        Acquire a new MCP session.

        Args:
            session_id: Optional unique identifier for the session

        Returns:
            Tuple of (session_id, mcp_session)
        """
        if session_id is None:
            session_id = f"session_{len(self._active_sessions) + 1}_{id(asyncio.current_task())}"

        # Create connector with custom SSE timeout
        connector = HttpConnector(
            base_url=self._server_config['url'],
            headers=self._server_config.get('headers'),
            auth_token=self._server_config.get('auth_token'),
            timeout=60,  # HTTP POST timeout - increased for long-running Neo4j queries
            sse_read_timeout=self._sse_timeout,  # Custom SSE timeout (1 hour default)
        )

        # Create session with custom connector
        session = MCPSession(connector)
        await session.initialize()

        # Store session with connector (maintains API: tuple of (client_or_connector, session))
        self._active_sessions[session_id] = (connector, session)
        self._logger.debug(f"Acquired MCP session: {session_id} (SSE timeout: {self._sse_timeout}s)")

        return session_id, session

    async def release_session(self, session_id: str) -> None:
        """
        Release an MCP session from the pool.

        Note: We don't explicitly close the session here because MCP sessions
        have async context managers that must be exited in the same task/cancel
        scope they were created in. Instead, we just remove from tracking and
        let the session be garbage collected. The SSE connection will close
        when the client object goes out of scope.

        Args:
            session_id: The session identifier to release
        """
        if session_id not in self._active_sessions:
            self._logger.warning(f"Session {session_id} not found in pool")
            return

        # Just remove from tracking - don't try to close explicitly
        # This avoids anyio cancel scope issues
        self._active_sessions.pop(session_id)
        self._logger.debug(f"Released MCP session: {session_id}")

    async def release_all(self) -> None:
        """Release all active sessions."""
        session_ids = list(self._active_sessions.keys())
        for session_id in session_ids:
            await self.release_session(session_id)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self._active_sessions)


__all__ = ['MCPSessionPool']
