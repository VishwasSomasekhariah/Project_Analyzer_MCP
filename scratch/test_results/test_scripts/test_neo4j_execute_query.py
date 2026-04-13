#!/usr/bin/env python3
"""
Test the new neo4j_execute_query tool directly
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def test_neo4j_execute_query():
    """Test the neo4j_execute_query tool directly."""
    logger.info("Testing neo4j_execute_query tool...")
    
    # Connect to Neo4j MCP server directly
    client = MCPClient.from_config_file("/opt/genpod/neo4j_config.json")
    session = await client.create_session("neo4j_memory")
    
    logger.info("✓ Connected to Neo4j MCP server")
    logger.info(f"Available tools: {[tool.name for tool in session.tools]}")
    
    try:
        # Test 1: Simple count query
        logger.info("=== Test 1: Count all nodes ===")
        
        result = await session.call_tool("neo4j_execute_query", {
            "query": "MATCH (n) RETURN count(n) as total_nodes",
            "limit": 10
        })
        
        logger.info("Result:")
        logger.info(str(result.content))
        
        # Test 2: Get node labels
        logger.info("\n=== Test 2: Get node labels ===")
        
        result = await session.call_tool("neo4j_execute_query", {
            "query": "CALL db.labels() YIELD label RETURN label ORDER BY label",
            "limit": 10
        })
        
        logger.info("Result:")
        logger.info(str(result.content))
        
        # Test 3: Sample nodes
        logger.info("\n=== Test 3: Sample nodes ===")
        
        result = await session.call_tool("neo4j_execute_query", {
            "query": "MATCH (n) RETURN labels(n) as nodeLabels, keys(n) as properties LIMIT 5",
            "limit": 5
        })
        
        logger.info("Result:")
        logger.info(str(result.content))
        
        # Test 4: Try to find functions specifically
        logger.info("\n=== Test 4: Find functions ===")
        
        result = await session.call_tool("neo4j_execute_query", {
            "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 5",
            "limit": 5
        })
        
        logger.info("Result:")
        logger.info(str(result.content))
        
        logger.info("✅ Direct neo4j_execute_query test completed")
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("neo4j_memory")
        logger.info("✓ Neo4j MCP session closed")


if __name__ == "__main__":
    asyncio.run(test_neo4j_execute_query())