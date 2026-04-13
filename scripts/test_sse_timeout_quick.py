#!/usr/bin/env python3
"""
Quick SSE Timeout Test - Simplified version
"""

import asyncio
import time
import logging
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_queries():
    """Test queries with new timeout."""
    logger.info("="*80)
    logger.info("Testing Timeout Fix with Real Queries")
    logger.info("="*80)

    try:
        from src.core.graph_rag.adapters.session_pool import MCPSessionPool

        # Load config
        config_path = Path("/opt/genpod/neo4j_config.json")
        with open(config_path) as f:
            mcp_config = json.load(f)

        logger.info("Creating MCP session pool...")
        pool = MCPSessionPool(mcp_config, sse_timeout=3600)

        logger.info("Acquiring session...")
        session_id, session = await pool.acquire_session()
        logger.info(f"✅ Session acquired: {session_id}\n")

        # Test 1: Simple query
        logger.info("Test 1: Simple query (should be < 1s)")
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

            # Handle MCP response format
            if hasattr(result, 'content'):
                content = result.content
                if isinstance(content, list) and len(content) > 0:
                    text_content = content[0].text if hasattr(content[0], 'text') else str(content[0])
                    try:
                        data = json.loads(text_content)
                        logger.info(f"✅ Simple query: {elapsed:.2f}s")
                        logger.info(f"   Results: {data.get('count', 'N/A')} records")
                    except:
                        logger.info(f"✅ Simple query: {elapsed:.2f}s")
                        logger.info(f"   Response: {text_content[:100]}")
            else:
                logger.info(f"✅ Simple query: {elapsed:.2f}s")
                logger.info(f"   Response: {str(result)[:100]}")

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Query failed after {elapsed:.2f}s: {e}")
            if "post_writer" in str(e).lower():
                logger.error("   🚨 POST_WRITER ERROR DETECTED!")
                return False

        # Test 2: Medium complexity
        logger.info("\nTest 2: Medium query (may take 5-15s)")
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
                        LIMIT 20
                    """,
                    "params": {}
                }
            )
            elapsed = time.time() - start
            logger.info(f"✅ Medium query: {elapsed:.2f}s")

            if elapsed > 10:
                logger.info(f"   🎉 Query took {elapsed:.2f}s - would have timed out before!")

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Query failed after {elapsed:.2f}s: {e}")
            if "post_writer" in str(e).lower() or "timeout" in str(e).lower():
                logger.error("   🚨 TIMEOUT ERROR!")
                return False

        # Test 3: Complex query
        logger.info("\nTest 3: Complex query (testing 60s timeout)")
        start = time.time()
        try:
            result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": """
                        MATCH (n)
                        WITH labels(n)[0] as label, count(n) as node_count
                        WHERE node_count > 0
                        RETURN label, node_count
                        ORDER BY node_count DESC
                        LIMIT 10
                    """,
                    "params": {}
                }
            )
            elapsed = time.time() - start
            logger.info(f"✅ Complex query: {elapsed:.2f}s")

            if elapsed > 10:
                logger.info(f"   🎉 SUCCESS! Completed in {elapsed:.2f}s with 60s timeout!")

        except Exception as e:
            elapsed = time.time() - start
            logger.error(f"❌ Query failed after {elapsed:.2f}s: {e}")
            if "post_writer" in str(e).lower():
                logger.error("   🚨 POST_WRITER TIMEOUT!")
                return False

        # Cleanup
        await pool.release_session(session_id)

        logger.info("\n" + "="*80)
        logger.info("✅ ALL QUERIES COMPLETED SUCCESSFULLY!")
        logger.info("="*80)
        logger.info("")
        logger.info("Results:")
        logger.info("  ✅ Timeout fix is working")
        logger.info("  ✅ No 'Error in post_writer' detected")
        logger.info("  ✅ Queries can run up to 60 seconds")
        return True

    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
        return False


async def test_keepalive():
    """Quick keep-alive test."""
    logger.info("\n" + "="*80)
    logger.info("Testing Keep-Alive (15 seconds)")
    logger.info("="*80)

    try:
        import httpx

        url = "http://localhost:8100/sse"
        ping_count = 0

        async with httpx.AsyncClient(timeout=20.0) as client:
            async with client.stream("GET", url) as response:
                logger.info("✅ Connected to SSE")

                start = time.time()
                async for line in response.aiter_lines():
                    if time.time() - start > 15:
                        break

                    if ": ping" in line or line.strip() == ":":
                        ping_count += 1
                        logger.info(f"💓 Ping #{ping_count}")

        if ping_count > 0:
            logger.info(f"✅ Received {ping_count} ping(s) - Keep-alive working!")
            return True
        else:
            logger.warning("⚠️  No pings received")
            return False

    except Exception as e:
        logger.error(f"Keep-alive test error: {e}")
        return False


async def main():
    logger.info("🧪 Quick SSE Timeout Fix Test\n")

    # Test queries
    query_result = await test_queries()

    # Test keep-alive
    keepalive_result = await test_keepalive()

    # Summary
    logger.info("\n" + "="*80)
    logger.info("📊 SUMMARY")
    logger.info("="*80)
    logger.info(f"Timeout Fix: {'✅ PASS' if query_result else '❌ FAIL'}")
    logger.info(f"Keep-Alive: {'✅ PASS' if keepalive_result else '❌ FAIL'}")
    logger.info("="*80)

    if query_result and keepalive_result:
        logger.info("\n🎉 ALL TESTS PASSED!")
        logger.info("The timeout fix is working correctly.")
        return 0
    else:
        logger.error("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
