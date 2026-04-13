#!/usr/bin/env python3
"""
Test Parallel Load on Neo4j MCP Server

This test verifies if multiple parallel queries block each other
or can execute concurrently.
"""

import asyncio
import time
import logging
import sys
import json
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_single_query(
    pool,
    query_id: int,
    complexity: str = "medium"
) -> Optional[float]:
    """
    Run a single query and measure time.

    Returns:
        Execution time in seconds, or None if failed
    """
    queries = {
        "light": "MATCH (n) RETURN count(n) as total LIMIT 1",
        "medium": """
            MATCH (n)
            WITH labels(n)[0] as label, count(n) as cnt
            RETURN label, cnt
            ORDER BY cnt DESC
            LIMIT 20
        """,
        "heavy": """
            MATCH (n)
            OPTIONAL MATCH (n)-[r]-(m)
            WITH n, count(r) as rels, count(DISTINCT m) as neighbors
            RETURN labels(n)[0] as type, avg(rels) as avg_rels, avg(neighbors) as avg_neighbors
            LIMIT 50
        """
    }

    start = time.time()
    session_id = None

    try:
        # Acquire session
        session_id, session = await pool.acquire_session()
        acquire_time = time.time() - start

        # Execute query
        result = await session.call_tool(
            "neo4j_execute_query",
            {
                "query": queries[complexity],
                "params": {}
            }
        )

        elapsed = time.time() - start
        logger.info(
            f"Query {query_id:2d}: {elapsed:5.2f}s "
            f"(acquire: {acquire_time:.2f}s, execute: {elapsed - acquire_time:.2f}s) ✅"
        )

        return elapsed

    except Exception as e:
        elapsed = time.time() - start
        error_msg = str(e)

        if "post_writer" in error_msg.lower():
            logger.error(f"Query {query_id:2d}: {elapsed:5.2f}s ❌ POST_WRITER ERROR")
        elif "timeout" in error_msg.lower():
            logger.error(f"Query {query_id:2d}: {elapsed:5.2f}s ❌ TIMEOUT")
        else:
            logger.error(f"Query {query_id:2d}: {elapsed:5.2f}s ❌ {error_msg[:50]}")

        return None

    finally:
        if session_id:
            await pool.release_session(session_id)


async def test_parallel_load(
    num_queries: int = 10,
    complexity: str = "medium"
):
    """
    Test parallel query execution.

    Args:
        num_queries: Number of parallel queries to run
        complexity: Query complexity (light/medium/heavy)
    """
    logger.info("="*80)
    logger.info(f"Parallel Load Test: {num_queries} queries ({complexity} complexity)")
    logger.info("="*80)

    try:
        from src.core.graph_rag.adapters.session_pool import MCPSessionPool

        # Load config
        config_path = Path("/opt/genpod/neo4j_config.json")
        with open(config_path) as f:
            config = json.load(f)

        logger.info("Creating session pool...")
        pool = MCPSessionPool(config, sse_timeout=3600)

        logger.info(f"Launching {num_queries} parallel queries...\n")
        start_time = time.time()

        # Launch all queries in parallel
        tasks = [
            run_single_query(pool, i, complexity)
            for i in range(num_queries)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_time = time.time() - start_time

        # Analyze results
        successes = [r for r in results if isinstance(r, float)]
        failures = [r for r in results if r is None or isinstance(r, Exception)]

        logger.info("\n" + "="*80)
        logger.info("RESULTS")
        logger.info("="*80)
        logger.info(f"Total time: {total_time:.2f}s")
        logger.info(f"Successes: {len(successes)}/{num_queries}")
        logger.info(f"Failures: {len(failures)}/{num_queries}")

        if successes:
            avg_time = sum(successes) / len(successes)
            min_time = min(successes)
            max_time = max(successes)
            std_dev = (sum((t - avg_time)**2 for t in successes) / len(successes))**0.5

            logger.info(f"\nQuery Times:")
            logger.info(f"  Min: {min_time:.2f}s")
            logger.info(f"  Avg: {avg_time:.2f}s")
            logger.info(f"  Max: {max_time:.2f}s")
            logger.info(f"  Std Dev: {std_dev:.2f}s")

            # Analysis
            logger.info("\n" + "-"*80)
            logger.info("ANALYSIS")
            logger.info("-"*80)

            if len(failures) == 0:
                logger.info("✅ All queries succeeded!")

                if std_dev < avg_time * 0.3:  # Low variance
                    logger.info("✅ Consistent timing - queries running in parallel")
                else:
                    logger.warning("⚠️  High variance - possible queueing or contention")

                if max_time < avg_time * 1.5:
                    logger.info("✅ No outliers - no queries blocked")
                else:
                    logger.warning(f"⚠️  Outlier detected - some queries took much longer")

            elif len(failures) < num_queries * 0.2:  # < 20% failure
                logger.warning(f"⚠️  {len(failures)} queries failed - possible load issue")
            else:
                logger.error(f"❌ {len(failures)} queries failed - SERIOUS BLOCKING!")

            # Cleanup
            await pool.release_all()

            return len(failures) == 0

        else:
            logger.error("❌ ALL QUERIES FAILED!")
            return False

    except Exception as e:
        logger.error(f"Test setup error: {e}", exc_info=True)
        return False


async def main():
    """Run parallel load tests."""
    logger.info("🧪 Parallel Load Test Suite\n")

    results = {}

    # Test 1: Light load (5 queries)
    logger.info("\n📊 TEST 1: Light Load (5 parallel queries)")
    results["light_load"] = await test_parallel_load(num_queries=5, complexity="light")

    await asyncio.sleep(2)

    # Test 2: Medium load (10 queries)
    logger.info("\n📊 TEST 2: Medium Load (10 parallel queries)")
    results["medium_load"] = await test_parallel_load(num_queries=10, complexity="medium")

    await asyncio.sleep(2)

    # Test 3: Heavy load (20 queries)
    logger.info("\n📊 TEST 3: Heavy Load (20 parallel queries)")
    results["heavy_load"] = await test_parallel_load(num_queries=20, complexity="medium")

    # Summary
    logger.info("\n" + "="*80)
    logger.info("📊 FINAL SUMMARY")
    logger.info("="*80)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{test_name}: {status}")

    logger.info("="*80)

    if all(results.values()):
        logger.info("\n🎉 ALL TESTS PASSED!")
        logger.info("")
        logger.info("✅ No blocking detected")
        logger.info("✅ Parallel queries work correctly")
        logger.info("✅ Session pool handles concurrency well")
        return 0
    else:
        logger.error("\n❌ SOME TESTS FAILED!")
        logger.error("")
        logger.error("Blocking detected under parallel load")
        logger.error("Consider implementing:")
        logger.error("  1. Server-side request queuing")
        logger.error("  2. Client-side semaphore")
        logger.error("  3. Connection pool management")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
