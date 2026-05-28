#!/usr/bin/env python3
"""
Test SSE Timeout Fix

This script tests:
1. Client timeout increase (10s -> 60s)
2. Long-running queries complete successfully
3. No "Error in post_writer" errors
4. SSE keep-alive is working
"""

import asyncio
import time
import logging
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_timeout_fix():
    """Test that increased timeout allows long queries to complete."""
    logger.info("="*80)
    logger.info("TEST 1: Client Timeout Fix")
    logger.info("="*80)

    try:
        from src.core.graph_rag.adapters.session_pool import MCPSessionPool
        import json

        # Load Neo4j MCP config
        config_path = Path("/opt/genpod/neo4j_config.json")
        if not config_path.exists():
            logger.error(f"Config not found: {config_path}")
            return False

        with open(config_path) as f:
            mcp_config = json.load(f)

        logger.info("Creating MCP session pool...")
        pool = MCPSessionPool(mcp_config, sse_timeout=3600)

        logger.info("Acquiring MCP session...")
        session_id, session = await pool.acquire_session()

        logger.info(f"Session acquired: {session_id}")
        logger.info("Testing with progressively complex queries...\n")

        # Test 1: Simple fast query (should take < 1s)
        logger.info("Test 1a: Simple query (< 1s)")
        start = time.time()
        try:
            result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": "MATCH (n) RETURN count(n) as total_nodes LIMIT 1",
                    "params": {}
                }
            )
            elapsed = time.time() - start
            success = result.get("success", False)

            if success:
                logger.info(f"✅ Simple query: {elapsed:.2f}s - {result.get('count', 0)} results")
            else:
                logger.error(f"❌ Simple query failed: {result.get('error')}")
                return False
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Simple query error after {elapsed:.2f}s: {e}")
            return False

        # Test 2: Medium query (should take 5-15s)
        logger.info("\nTest 1b: Medium complexity query (5-15s)")
        start = time.time()
        try:
            result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": """
                        MATCH (n:Function)
                        OPTIONAL MATCH (n)-[r:CALLS]->(m:Function)
                        RETURN n.name as function, count(r) as calls
                        ORDER BY calls DESC
                        LIMIT 50
                    """,
                    "params": {}
                }
            )
            elapsed = time.time() - start
            success = result.get("success", False)

            if success:
                logger.info(f"✅ Medium query: {elapsed:.2f}s - {result.get('count', 0)} results")
                if elapsed > 10:
                    logger.info(f"   ⚠️  Query took {elapsed:.2f}s - would have timed out with 10s timeout!")
            else:
                logger.error(f"❌ Medium query failed: {result.get('error')}")
                return False
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Medium query error after {elapsed:.2f}s: {e}")
            if "post_writer" in str(e).lower() or "timeout" in str(e).lower():
                logger.error("   🚨 TIMEOUT ERROR DETECTED - Fix may not be applied!")
            return False

        # Test 3: Complex query (should take 15-30s)
        logger.info("\nTest 1c: Complex query (15-30s) - testing 60s timeout")
        start = time.time()
        try:
            result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": """
                        MATCH (n)
                        OPTIONAL MATCH (n)-[r]-(m)
                        WITH n, count(DISTINCT r) as rel_count, count(DISTINCT m) as neighbor_count
                        RETURN
                            labels(n)[0] as node_type,
                            count(n) as node_count,
                            avg(rel_count) as avg_relationships,
                            avg(neighbor_count) as avg_neighbors
                        ORDER BY node_count DESC
                        LIMIT 20
                    """,
                    "params": {}
                }
            )
            elapsed = time.time() - start
            success = result.get("success", False)

            if success:
                logger.info(f"✅ Complex query: {elapsed:.2f}s - {result.get('count', 0)} results")
                if elapsed > 10:
                    logger.info(f"   🎉 SUCCESS! Query took {elapsed:.2f}s - worked with 60s timeout!")
            else:
                logger.error(f"❌ Complex query failed: {result.get('error')}")
                return False
        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Complex query error after {elapsed:.2f}s: {e}")
            if "post_writer" in str(e).lower() or "timeout" in str(e).lower():
                logger.error("   🚨 TIMEOUT ERROR - Timeout may still be too short!")
            return False

        # Cleanup
        logger.info("\nCleaning up session...")
        await pool.release_session(session_id)

        logger.info("\n" + "="*80)
        logger.info("✅ ALL TIMEOUT TESTS PASSED!")
        logger.info("="*80)
        return True

    except Exception as e:
        logger.error(f"Test setup error: {e}", exc_info=True)
        return False


async def test_keepalive_monitoring():
    """Monitor SSE connection to verify keep-alive pings."""
    logger.info("\n" + "="*80)
    logger.info("TEST 2: Keep-Alive Monitoring")
    logger.info("="*80)
    logger.info("Monitoring SSE connection for 45 seconds...")
    logger.info("Should see ping events every ~15 seconds\n")

    try:
        import httpx
        from datetime import datetime

        url = "http://localhost:8100/sse"
        ping_count = 0
        last_ping = None

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    logger.error(f"Failed to connect: HTTP {response.status_code}")
                    return False

                logger.info("✅ Connected to SSE endpoint")

                start_time = time.time()
                async for line in response.aiter_lines():
                    elapsed = time.time() - start_time

                    if elapsed > 45:  # Monitor for 45 seconds
                        break

                    if line.strip():
                        timestamp = datetime.now().strftime("%H:%M:%S")

                        if line.startswith(": ping") or line.strip() == ":":
                            ping_count += 1
                            if last_ping:
                                interval = time.time() - last_ping
                                logger.info(f"[{timestamp}] 💓 Ping #{ping_count} (interval: {interval:.1f}s)")
                            else:
                                logger.info(f"[{timestamp}] 💓 Ping #{ping_count}")
                            last_ping = time.time()

                        elif line.startswith("event:"):
                            logger.info(f"[{timestamp}] 📡 {line}")

                        elif line.startswith("data:"):
                            data = line[5:].strip()
                            if len(data) < 100:
                                logger.info(f"[{timestamp}] 📨 {line}")

        logger.info(f"\n✅ Monitoring complete!")
        logger.info(f"   Received {ping_count} ping events in 45 seconds")

        if ping_count >= 2:  # Should get at least 2-3 pings in 45 seconds
            logger.info(f"   🎉 Keep-alive is WORKING!")
            return True
        else:
            logger.warning(f"   ⚠️  Expected 2-3 pings, got {ping_count}")
            return False

    except httpx.ConnectError:
        logger.error("❌ Cannot connect to Neo4j MCP server at localhost:8100")
        logger.error("   Make sure the server is running:")
        logger.error("   cd neo4j-mcp-server && python -m neo4j_mcp_server.server")
        return False
    except Exception as e:
        logger.error(f"Keep-alive test error: {e}", exc_info=True)
        return False


async def main():
    """Run all tests."""
    logger.info("🧪 SSE Timeout Fix Test Suite")
    logger.info("="*80)
    logger.info("This will test:")
    logger.info("1. Client timeout increased from 10s to 60s")
    logger.info("2. Long-running queries complete successfully")
    logger.info("3. SSE keep-alive pings every 15 seconds")
    logger.info("="*80)

    results = {}

    # Test 1: Timeout fix
    logger.info("\nStarting Test 1: Client Timeout Fix")
    results["timeout_fix"] = await test_timeout_fix()

    # Small delay between tests
    await asyncio.sleep(2)

    # Test 2: Keep-alive
    logger.info("\nStarting Test 2: Keep-Alive Monitoring")
    results["keepalive"] = await test_keepalive_monitoring()

    # Summary
    logger.info("\n" + "="*80)
    logger.info("📊 TEST SUMMARY")
    logger.info("="*80)

    all_passed = all(results.values())

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{test_name}: {status}")

    logger.info("="*80)

    if all_passed:
        logger.info("🎉 ALL TESTS PASSED!")
        logger.info("")
        logger.info("✅ Timeout fix is working")
        logger.info("✅ Keep-alive is working")
        logger.info("✅ No more 'Error in post_writer' expected!")
        return 0
    else:
        logger.error("❌ SOME TESTS FAILED")
        logger.error("")
        if not results.get("timeout_fix"):
            logger.error("Timeout fix may not be properly applied")
            logger.error("Check: src/core/graph_rag/adapters/session_pool.py line 59")
        if not results.get("keepalive"):
            logger.error("Keep-alive issues detected")
            logger.error("Check: Neo4j MCP server is running on port 8100")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
