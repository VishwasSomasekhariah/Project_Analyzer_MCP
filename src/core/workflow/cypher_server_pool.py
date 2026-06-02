"""
Cypher Server Pool Manager

Manages a pool of persistent cypher server instances for parallel approach execution.
Each server is a project-analyzer CLI process running in cypher server mode.

This enables:
- Parallel execution of approaches without thread explosion
- Fast query execution with no subprocess overhead
- Controlled database connections (pool_size connections vs hundreds)
"""

import asyncio
import json
import logging
from typing import List, Optional, Dict, Any

from src.core.paths import NEO4J_CONFIG, GENPOD_GRAPH_INDEXER_BIN

logger = logging.getLogger(__name__)


class CypherServerInstance:
    """
    Single persistent cypher server process.

    Wraps project-analyzer CLI running in cypher server mode for fast query execution.
    """

    def __init__(self, server_id: int, neo4j_config: str, query_timeout: int = 30):
        """
        Initialize cypher server instance.

        Args:
            server_id: Unique identifier for this server
            neo4j_config: Path to Neo4j configuration file
            query_timeout: Timeout for individual queries in seconds (default: 30)
        """
        self.server_id = server_id
        self.neo4j_config = neo4j_config
        self.query_timeout = query_timeout  # Configurable timeout
        self.process: Optional[asyncio.subprocess.Process] = None
        self.stdin_writer: Optional[asyncio.StreamWriter] = None
        self.stdout_reader: Optional[asyncio.StreamReader] = None
        self.stderr_reader: Optional[asyncio.StreamReader] = None
        self.is_ready = False
        self.queries_executed = 0

    async def start(self) -> bool:
        """
        Start the cypher server process.

        Returns:
            True if server started successfully, False otherwise
        """
        try:
            logger.info(f"🔥 Starting cypher server {self.server_id}...")

            cmd = [
                GENPOD_GRAPH_INDEXER_BIN,
                "--config-file", self.neo4j_config,
                "cypher-server",
                "--input-mode", "stdin",
                "--timeout", str(self.query_timeout)  # Use configurable timeout
            ]

            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            self.stdin_writer = self.process.stdin
            self.stdout_reader = self.process.stdout
            self.stderr_reader = self.process.stderr

            # Wait for server to be ready (learned from cypher_server_service.py)
            await asyncio.sleep(2)  # Give server time to initialize

            if self.process.returncode is None:
                self.is_ready = True
                logger.info(f"✅ Cypher server {self.server_id} started (PID: {self.process.pid})")
                return True
            else:
                logger.error(f"❌ Cypher server {self.server_id} failed to start")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to start cypher server {self.server_id}: {e}")
            return False

    async def execute_query(self, cypher_query: str, params: Optional[Dict[str, Any]] = None, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a Cypher query through this server.

        Args:
            cypher_query: The Cypher query to execute
            params: Optional query parameters
            limit: Optional result limit (overrides default 100 from Neo4j MCP)

        Returns:
            Dict with keys: status, query, data, error, server_id, execution_time
        """
        if not self.is_ready:
            return {
                'status': 'error',
                'query': cypher_query,
                'data': [],
                'error': f'Server {self.server_id} not ready',
                'server_id': self.server_id
            }

        try:
            import time
            start_time = time.time()

            # Build request
            request = {
                "query": cypher_query,
                "params": params or {}
            }

            # Add limit if specified (overrides Neo4j MCP default of 100)
            if limit is not None:
                request["limit"] = limit

            # Write to stdin
            request_json = json.dumps(request) + '\n'
            self.stdin_writer.write(request_json.encode())
            await self.stdin_writer.drain()

            # Read response from stdout (with configurable timeout)
            try:
                response_line = await asyncio.wait_for(
                    self.stdout_reader.readline(),
                    timeout=float(self.query_timeout)  # Use instance timeout
                )
            except asyncio.TimeoutError:
                logger.error(f"⏱️ Query timeout on server {self.server_id}")
                return {
                    'status': 'error',
                    'query': cypher_query,
                    'data': [],
                    'error': 'Query execution timeout',
                    'server_id': self.server_id
                }

            if not response_line:
                logger.error(f"❌ Empty response from server {self.server_id}")
                return {
                    'status': 'error',
                    'query': cypher_query,
                    'data': [],
                    'error': 'Empty response from cypher server',
                    'server_id': self.server_id
                }

            response = json.loads(response_line.decode().strip())

            execution_time = time.time() - start_time
            self.queries_executed += 1

            # Determine status
            # CRITICAL FIX: cypher-server returns 'results', not 'data'
            results = response.get('results', response.get('data', []))

            if response.get('error'):
                status = 'error'
            elif not results or len(results) == 0:
                status = 'empty_result'
            else:
                status = 'success'

            return {
                'status': status,
                'query': cypher_query,
                'data': results,  # Use the extracted results
                'error': response.get('error'),
                'server_id': self.server_id,
                'execution_time': execution_time
            }

        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error on server {self.server_id}: {e}")
            return {
                'status': 'error',
                'query': cypher_query,
                'data': [],
                'error': f'JSON decode error: {e}',
                'server_id': self.server_id
            }
        except Exception as e:
            logger.error(f"❌ Query execution error on server {self.server_id}: {e}")
            return {
                'status': 'error',
                'query': cypher_query,
                'data': [],
                'error': str(e),
                'server_id': self.server_id
            }

    async def stop(self):
        """Stop the cypher server process."""
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
                logger.info(f"🔌 Cypher server {self.server_id} stopped ({self.queries_executed} queries executed)")
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Force killing cypher server {self.server_id}")
                self.process.kill()
                await self.process.wait()
            except Exception as e:
                logger.error(f"❌ Error stopping cypher server {self.server_id}: {e}")

        self.is_ready = False

    def __repr__(self):
        return f"CypherServerInstance(id={self.server_id}, ready={self.is_ready}, queries={self.queries_executed})"


class CypherServerPool:
    """
    Manages a pool of cypher server instances for parallel approach execution.

    Features:
    - Fixed pool size (typically batch_size = 4)
    - Acquire/release pattern for controlled access
    - Automatic initialization and cleanup
    - Health monitoring
    """

    def __init__(self, pool_size: int, neo4j_config: str, query_timeout: int = 30):
        """
        Initialize cypher server pool.

        Args:
            pool_size: Number of cypher servers to maintain (typically 4)
            neo4j_config: Path to Neo4j configuration file
            query_timeout: Timeout for individual queries in seconds (default: 30)
        """
        self.pool_size = pool_size
        self.neo4j_config = neo4j_config
        self.query_timeout = query_timeout
        self.servers: List[CypherServerInstance] = []
        self.available_servers: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self.is_initialized = False

    async def initialize(self) -> bool:
        """
        Start all cypher servers in the pool.

        Returns:
            True if all servers started successfully, False otherwise
        """
        logger.info(f"🔥 Initializing cypher server pool (size={self.pool_size})...")

        # Start all servers concurrently
        start_tasks = []
        for i in range(self.pool_size):
            server = CypherServerInstance(
                server_id=i,
                neo4j_config=self.neo4j_config,
                query_timeout=self.query_timeout  # Pass timeout to each server
            )
            self.servers.append(server)
            start_tasks.append(server.start())

        # Wait for all to start
        results = await asyncio.gather(*start_tasks, return_exceptions=True)

        # Check results
        success_count = sum(1 for r in results if r is True)

        if success_count < self.pool_size:
            logger.error(f"❌ Only {success_count}/{self.pool_size} servers started successfully")
            await self.shutdown()
            return False

        # Add all servers to available queue
        for server in self.servers:
            await self.available_servers.put(server)

        self.is_initialized = True
        logger.info(f"✅ Cypher server pool ready ({self.pool_size} servers)")
        return True

    async def acquire(self) -> CypherServerInstance:
        """
        Get an available server from the pool.

        Blocks until a server becomes available.

        Returns:
            CypherServerInstance ready to execute queries
        """
        server = await self.available_servers.get()
        logger.debug(f"🔒 Acquired cypher server {server.server_id}")
        return server

    async def release(self, server: CypherServerInstance):
        """
        Return a server to the pool.

        Args:
            server: The server to return
        """
        await self.available_servers.put(server)
        logger.debug(f"🔓 Released cypher server {server.server_id}")

    async def shutdown(self):
        """Shutdown all servers in the pool."""
        if not self.servers:
            return

        logger.info(f"🔌 Shutting down cypher server pool ({len(self.servers)} servers)...")

        # Stop all servers concurrently
        stop_tasks = [server.stop() for server in self.servers]
        await asyncio.gather(*stop_tasks, return_exceptions=True)

        total_queries = sum(s.queries_executed for s in self.servers)
        logger.info(f"✅ Cypher server pool shutdown complete ({total_queries} total queries executed)")

        self.servers.clear()
        self.is_initialized = False

    def get_stats(self) -> Dict[str, Any]:
        """
        Get pool statistics.

        Returns:
            Dict with pool stats
        """
        return {
            'pool_size': self.pool_size,
            'is_initialized': self.is_initialized,
            'total_queries_executed': sum(s.queries_executed for s in self.servers),
            'servers': [
                {
                    'id': s.server_id,
                    'ready': s.is_ready,
                    'queries_executed': s.queries_executed
                }
                for s in self.servers
            ]
        }

    def __repr__(self):
        return f"CypherServerPool(size={self.pool_size}, initialized={self.is_initialized})"


# Context manager for automatic cleanup
class CypherServerPoolContext:
    """Context manager for cypher server pool with automatic cleanup."""

    def __init__(self, pool_size: int, neo4j_config: str):
        self.pool = CypherServerPool(pool_size, neo4j_config)

    async def __aenter__(self):
        await self.pool.initialize()
        return self.pool

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.pool.shutdown()


# Factory function for easy usage
async def create_cypher_server_pool(pool_size: int = 4, neo4j_config: str = NEO4J_CONFIG) -> CypherServerPool:
    """
    Create and initialize a cypher server pool.

    Args:
        pool_size: Number of servers in pool (default: 4)
        neo4j_config: Path to Neo4j configuration

    Returns:
        Initialized CypherServerPool ready to use
    """
    pool = CypherServerPool(pool_size, neo4j_config)
    success = await pool.initialize()

    if not success:
        raise RuntimeError(f"Failed to initialize cypher server pool")

    return pool


# Example usage
async def example_usage():
    """Example of how to use cypher server pool."""

    # Create pool
    pool = await create_cypher_server_pool(pool_size=4)

    try:
        # Acquire server
        server = await pool.acquire()

        # Execute query
        result = await server.execute_query("MATCH (n) RETURN count(n) as node_count")
        print(f"Result: {result}")

        # Release server back to pool
        await pool.release(server)

    finally:
        # Always cleanup
        await pool.shutdown()


# Alternative: Use context manager
async def example_with_context_manager():
    """Example using context manager for automatic cleanup."""

    async with CypherServerPoolContext(pool_size=4, neo4j_config=NEO4J_CONFIG) as pool:
        server = await pool.acquire()
        result = await server.execute_query("MATCH (n) RETURN count(n)")
        await pool.release(server)
        print(f"Result: {result}")

    # Pool automatically cleaned up when exiting context


if __name__ == "__main__":
    # Test the pool
    asyncio.run(example_with_context_manager())
