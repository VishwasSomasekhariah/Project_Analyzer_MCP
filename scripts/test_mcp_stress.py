#!/usr/bin/env python3
"""
MCP Session Pool Stress Test

Tests the MCP session pool and Neo4j MCP server under concurrent load
WITHOUT using LLM tokens. Focuses on:
1. Concurrent session creation
2. Parallel tool calls across sessions
3. Session lifecycle management
4. Error handling and recovery
"""

import asyncio
import json
import logging
import time
import statistics
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce noise from httpx
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("mcp.client.sse").setLevel(logging.WARNING)


@dataclass
class StressTestResult:
    """Results from a stress test run"""
    test_name: str
    total_operations: int
    successful_operations: int
    failed_operations: int
    total_time_ms: float
    avg_time_ms: float
    min_time_ms: float
    max_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    errors: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        success_rate = (self.successful_operations / self.total_operations * 100) if self.total_operations > 0 else 0
        return f"""
{self.test_name}
{'=' * len(self.test_name)}
Total Operations: {self.total_operations}
Successful: {self.successful_operations} ({success_rate:.1f}%)
Failed: {self.failed_operations}
Total Time: {self.total_time_ms:.2f}ms
Avg Time: {self.avg_time_ms:.2f}ms
Min Time: {self.min_time_ms:.2f}ms
Max Time: {self.max_time_ms:.2f}ms
P50: {self.p50_time_ms:.2f}ms
P95: {self.p95_time_ms:.2f}ms
P99: {self.p99_time_ms:.2f}ms
Errors: {len(self.errors)}
"""


class MCPStressTester:
    """Stress tester for MCP session pool and connections"""

    # Simple Cypher queries that don't require complex processing
    TEST_QUERIES = [
        "MATCH (n) RETURN count(n) as count",
        "MATCH (t:Type) RETURN t.name LIMIT 5",
        "MATCH (f:Function) RETURN f.name LIMIT 5",
        "MATCH ()-[r]->() RETURN type(r), count(r) as cnt LIMIT 5",
        "MATCH (t:Type)-[:CONTAINS]->(f:Function) RETURN t.name, f.name LIMIT 3",
    ]

    def __init__(self, config_path: str = "neo4j_config.json"):
        self.config_path = config_path
        self._load_config()

    def _load_config(self):
        """Load MCP configuration"""
        with open(self.config_path, 'r') as f:
            self.config_dict = json.load(f)
        self.server_name = list(self.config_dict.get('mcpServers', {}).keys())[0]
        logger.info(f"Loaded config for server: {self.server_name}")

    async def _create_session(self) -> Tuple[MCPClient, Any]:
        """Create a new MCP client and session"""
        client = MCPClient.from_config_file(self.config_path)
        session = await client.create_session(self.server_name)
        return client, session

    async def _close_session(self, client: MCPClient):
        """Close an MCP session"""
        try:
            await client.close_session(self.server_name)
        except Exception as e:
            logger.warning(f"Error closing session: {e}")

    async def _execute_query(self, session, query: str) -> Tuple[bool, float, Optional[str]]:
        """Execute a single query and return (success, time_ms, error)"""
        start = time.perf_counter()
        try:
            result = await session.call_tool('neo4j_execute_query', {'query': query})
            elapsed_ms = (time.perf_counter() - start) * 1000

            if hasattr(result, 'content') and result.content:
                return True, elapsed_ms, None
            return False, elapsed_ms, "Empty response"
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return False, elapsed_ms, str(e)

    def _compute_percentile(self, times: List[float], percentile: float) -> float:
        """Compute percentile from list of times"""
        if not times:
            return 0.0
        sorted_times = sorted(times)
        idx = int(len(sorted_times) * percentile / 100)
        idx = min(idx, len(sorted_times) - 1)
        return sorted_times[idx]

    def _compute_stats(self, test_name: str, times: List[float],
                       errors: List[str], total_time: float) -> StressTestResult:
        """Compute statistics from test results"""
        successful = len(times)
        failed = len(errors)
        total = successful + failed

        if times:
            return StressTestResult(
                test_name=test_name,
                total_operations=total,
                successful_operations=successful,
                failed_operations=failed,
                total_time_ms=total_time * 1000,
                avg_time_ms=statistics.mean(times) if times else 0,
                min_time_ms=min(times) if times else 0,
                max_time_ms=max(times) if times else 0,
                p50_time_ms=self._compute_percentile(times, 50),
                p95_time_ms=self._compute_percentile(times, 95),
                p99_time_ms=self._compute_percentile(times, 99),
                errors=errors[:10]  # Keep first 10 errors
            )
        else:
            return StressTestResult(
                test_name=test_name,
                total_operations=total,
                successful_operations=0,
                failed_operations=failed,
                total_time_ms=total_time * 1000,
                avg_time_ms=0, min_time_ms=0, max_time_ms=0,
                p50_time_ms=0, p95_time_ms=0, p99_time_ms=0,
                errors=errors[:10]
            )

    # =========================================================================
    # TEST 1: Sequential Session Creation
    # =========================================================================
    async def test_sequential_session_creation(self, num_sessions: int = 10) -> StressTestResult:
        """Test creating and closing sessions sequentially"""
        logger.info(f"TEST: Sequential session creation ({num_sessions} sessions)")

        times = []
        errors = []
        start_total = time.perf_counter()

        for i in range(num_sessions):
            start = time.perf_counter()
            try:
                client, session = await self._create_session()

                # Execute a simple query to verify session works
                success, _, error = await self._execute_query(session, "RETURN 1 as test")

                await self._close_session(client)

                elapsed_ms = (time.perf_counter() - start) * 1000
                if success:
                    times.append(elapsed_ms)
                    logger.debug(f"  Session {i+1}: {elapsed_ms:.2f}ms")
                else:
                    errors.append(f"Session {i+1}: {error}")

            except Exception as e:
                errors.append(f"Session {i+1}: {str(e)}")

        total_time = time.perf_counter() - start_total
        return self._compute_stats("Sequential Session Creation", times, errors, total_time)

    # =========================================================================
    # TEST 2: Concurrent Session Creation
    # =========================================================================
    async def test_concurrent_session_creation(self, num_sessions: int = 10) -> StressTestResult:
        """Test creating multiple sessions concurrently"""
        logger.info(f"TEST: Concurrent session creation ({num_sessions} sessions)")

        async def create_and_test_session(session_id: int) -> Tuple[bool, float, Optional[str]]:
            start = time.perf_counter()
            try:
                client, session = await self._create_session()

                # Execute a simple query
                success, _, error = await self._execute_query(session, "RETURN 1 as test")

                await self._close_session(client)

                elapsed_ms = (time.perf_counter() - start) * 1000
                return success, elapsed_ms, error
            except Exception as e:
                elapsed_ms = (time.perf_counter() - start) * 1000
                return False, elapsed_ms, str(e)

        start_total = time.perf_counter()

        # Create all sessions concurrently
        tasks = [create_and_test_session(i) for i in range(num_sessions)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start_total

        times = []
        errors = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                errors.append(f"Session {i+1}: {str(result)}")
            else:
                success, elapsed_ms, error = result
                if success:
                    times.append(elapsed_ms)
                else:
                    errors.append(f"Session {i+1}: {error}")

        return self._compute_stats("Concurrent Session Creation", times, errors, total_time)

    # =========================================================================
    # TEST 3: Sequential Queries on Single Session
    # =========================================================================
    async def test_sequential_queries_single_session(self, num_queries: int = 50) -> StressTestResult:
        """Test running many sequential queries on a single session"""
        logger.info(f"TEST: Sequential queries on single session ({num_queries} queries)")

        client, session = await self._create_session()

        times = []
        errors = []
        start_total = time.perf_counter()

        try:
            for i in range(num_queries):
                query = self.TEST_QUERIES[i % len(self.TEST_QUERIES)]
                success, elapsed_ms, error = await self._execute_query(session, query)

                if success:
                    times.append(elapsed_ms)
                else:
                    errors.append(f"Query {i+1}: {error}")
        finally:
            await self._close_session(client)

        total_time = time.perf_counter() - start_total
        return self._compute_stats("Sequential Queries (Single Session)", times, errors, total_time)

    # =========================================================================
    # TEST 4: Concurrent Queries on Separate Sessions
    # =========================================================================
    async def test_concurrent_queries_separate_sessions(
        self, num_sessions: int = 5, queries_per_session: int = 10
    ) -> StressTestResult:
        """Test running concurrent queries each with its own session"""
        logger.info(f"TEST: Concurrent queries on separate sessions ({num_sessions} sessions x {queries_per_session} queries)")

        async def session_worker(session_id: int) -> List[Tuple[bool, float, Optional[str]]]:
            """Worker that creates session, runs queries, closes session"""
            results = []
            try:
                client, session = await self._create_session()
                try:
                    for i in range(queries_per_session):
                        query = self.TEST_QUERIES[(session_id + i) % len(self.TEST_QUERIES)]
                        success, elapsed_ms, error = await self._execute_query(session, query)
                        results.append((success, elapsed_ms, error))
                finally:
                    await self._close_session(client)
            except Exception as e:
                results.append((False, 0, str(e)))
            return results

        start_total = time.perf_counter()

        # Run all sessions concurrently
        tasks = [session_worker(i) for i in range(num_sessions)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start_total

        times = []
        errors = []
        for session_id, session_results in enumerate(all_results):
            if isinstance(session_results, Exception):
                errors.append(f"Session {session_id+1}: {str(session_results)}")
            else:
                for i, (success, elapsed_ms, error) in enumerate(session_results):
                    if success:
                        times.append(elapsed_ms)
                    else:
                        errors.append(f"S{session_id+1}/Q{i+1}: {error}")

        return self._compute_stats(
            f"Concurrent Queries (Separate Sessions: {num_sessions}x{queries_per_session})",
            times, errors, total_time
        )

    # =========================================================================
    # TEST 5: Session Pool Stress (Rapid Create/Release)
    # =========================================================================
    async def test_session_pool_stress(self, cycles: int = 20, sessions_per_cycle: int = 3) -> StressTestResult:
        """Test rapid session creation and release cycles"""
        logger.info(f"TEST: Session pool stress ({cycles} cycles x {sessions_per_cycle} sessions)")

        async def cycle_worker(cycle_id: int) -> List[Tuple[bool, float, Optional[str]]]:
            """One cycle: create sessions, run query, close"""
            results = []
            sessions = []

            try:
                # Create multiple sessions
                for i in range(sessions_per_cycle):
                    client, session = await self._create_session()
                    sessions.append((client, session))

                # Run a query on each
                for i, (client, session) in enumerate(sessions):
                    query = self.TEST_QUERIES[i % len(self.TEST_QUERIES)]
                    success, elapsed_ms, error = await self._execute_query(session, query)
                    results.append((success, elapsed_ms, error))

            except Exception as e:
                results.append((False, 0, str(e)))
            finally:
                # Close all sessions
                for client, _ in sessions:
                    try:
                        await self._close_session(client)
                    except:
                        pass

            return results

        start_total = time.perf_counter()

        # Run all cycles concurrently
        tasks = [cycle_worker(i) for i in range(cycles)]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.perf_counter() - start_total

        times = []
        errors = []
        for cycle_id, cycle_results in enumerate(all_results):
            if isinstance(cycle_results, Exception):
                errors.append(f"Cycle {cycle_id+1}: {str(cycle_results)}")
            else:
                for i, (success, elapsed_ms, error) in enumerate(cycle_results):
                    if success:
                        times.append(elapsed_ms)
                    else:
                        errors.append(f"C{cycle_id+1}/Q{i+1}: {error}")

        return self._compute_stats(
            f"Session Pool Stress ({cycles}x{sessions_per_cycle})",
            times, errors, total_time
        )

    # =========================================================================
    # TEST 6: Sustained Load
    # =========================================================================
    async def test_sustained_load(
        self, duration_seconds: int = 30, concurrent_sessions: int = 3
    ) -> StressTestResult:
        """Run sustained concurrent load for a duration"""
        logger.info(f"TEST: Sustained load ({duration_seconds}s, {concurrent_sessions} concurrent sessions)")

        stop_event = asyncio.Event()
        all_times = []
        all_errors = []
        lock = asyncio.Lock()

        async def worker(worker_id: int):
            """Continuously create sessions, run queries until stopped"""
            local_times = []
            local_errors = []

            while not stop_event.is_set():
                try:
                    client, session = await self._create_session()
                    try:
                        # Run a few queries
                        for i in range(3):
                            if stop_event.is_set():
                                break
                            query = self.TEST_QUERIES[(worker_id + i) % len(self.TEST_QUERIES)]
                            success, elapsed_ms, error = await self._execute_query(session, query)
                            if success:
                                local_times.append(elapsed_ms)
                            else:
                                local_errors.append(f"W{worker_id}: {error}")
                    finally:
                        await self._close_session(client)
                except Exception as e:
                    local_errors.append(f"W{worker_id}: {str(e)}")
                    await asyncio.sleep(0.1)  # Brief pause on error

            # Merge results
            async with lock:
                all_times.extend(local_times)
                all_errors.extend(local_errors)

        start_total = time.perf_counter()

        # Start workers
        workers = [asyncio.create_task(worker(i)) for i in range(concurrent_sessions)]

        # Wait for duration
        await asyncio.sleep(duration_seconds)
        stop_event.set()

        # Wait for workers to finish
        await asyncio.gather(*workers, return_exceptions=True)

        total_time = time.perf_counter() - start_total

        return self._compute_stats(
            f"Sustained Load ({duration_seconds}s, {concurrent_sessions} workers)",
            all_times, all_errors, total_time
        )

    # =========================================================================
    # RUN ALL TESTS
    # =========================================================================
    async def run_all_tests(self) -> List[StressTestResult]:
        """Run all stress tests"""
        results = []

        print("\n" + "=" * 70)
        print("MCP SESSION POOL STRESS TEST")
        print("=" * 70)

        # Test 1: Sequential session creation
        result = await self.test_sequential_session_creation(num_sessions=10)
        results.append(result)
        print(result)

        # Test 2: Concurrent session creation
        result = await self.test_concurrent_session_creation(num_sessions=10)
        results.append(result)
        print(result)

        # Test 3: Sequential queries on single session
        result = await self.test_sequential_queries_single_session(num_queries=50)
        results.append(result)
        print(result)

        # Test 4: Concurrent queries on separate sessions
        result = await self.test_concurrent_queries_separate_sessions(
            num_sessions=5, queries_per_session=10
        )
        results.append(result)
        print(result)

        # Test 5: Session pool stress
        result = await self.test_session_pool_stress(cycles=20, sessions_per_cycle=3)
        results.append(result)
        print(result)

        # Test 6: Sustained load (shorter duration for quick test)
        result = await self.test_sustained_load(duration_seconds=15, concurrent_sessions=3)
        results.append(result)
        print(result)

        # Summary
        print("=" * 70)
        print("SUMMARY")
        print("=" * 70)
        total_ops = sum(r.total_operations for r in results)
        total_success = sum(r.successful_operations for r in results)
        total_failed = sum(r.failed_operations for r in results)
        overall_success_rate = (total_success / total_ops * 100) if total_ops > 0 else 0

        print(f"Total Operations: {total_ops}")
        print(f"Successful: {total_success} ({overall_success_rate:.1f}%)")
        print(f"Failed: {total_failed}")

        if total_failed > 0:
            print("\nErrors encountered:")
            for result in results:
                if result.errors:
                    print(f"\n  {result.test_name}:")
                    for error in result.errors[:3]:
                        print(f"    - {error}")

        print("=" * 70)

        return results


async def main():
    """Run the stress tests"""
    tester = MCPStressTester("neo4j_config.json")
    await tester.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
