#!/usr/bin/env python3
"""
Debug script to investigate schema alignment issues between expected schema
and actual Neo4j database using APOC procedures.
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


async def debug_schema_alignment():
    """Debug schema alignment using APOC procedures."""
    logger.info("Starting schema alignment debugging...")
    
    # Connect to MCP server
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("project-analyzer-server")
    
    logger.info("✓ Connected to MCP server")
    
    try:
        # Test 1: Get actual database schema using APOC
        logger.info("=== Testing APOC meta.schema() ===")
        
        schema_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "CALL apoc.meta.schema() YIELD value RETURN value",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("APOC schema result:")
        logger.info(str(schema_result.content))
        
        # Test 2: Get node type statistics
        logger.info("\n=== Testing Node Type Stats ===")
        
        stats_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "CALL apoc.meta.stats() YIELD labels, relTypes RETURN labels, relTypes",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Node and relationship stats:")
        logger.info(str(stats_result.content))
        
        # Test 3: Get actual node labels that exist
        logger.info("\n=== Testing Actual Node Labels ===")
        
        labels_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "CALL db.labels() YIELD label RETURN label ORDER BY label",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Actual node labels in database:")
        logger.info(str(labels_result.content))
        
        # Test 4: Get actual relationship types
        logger.info("\n=== Testing Actual Relationship Types ===")
        
        rels_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Actual relationship types in database:")
        logger.info(str(rels_result.content))
        
        # Test 5: Sample some actual nodes to see their properties
        logger.info("\n=== Testing Sample Node Properties ===")
        
        sample_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "MATCH (n) RETURN labels(n) as nodeLabels, keys(n) as properties LIMIT 10",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Sample node properties:")
        logger.info(str(sample_result.content))
        
        # Test 6: Try a simple query that should work according to schema
        logger.info("\n=== Testing Schema-Based Query ===")
        
        test_query_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "MATCH (f:Function) RETURN f.name LIMIT 5",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Function nodes query result:")
        logger.info(str(test_query_result.content))
        
        # Test 7: Try another schema-based query
        logger.info("\n=== Testing File-Function Relationship ===")
        
        rel_test_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "MATCH (file:File)-[:CONTAINS]->(func:Function) RETURN file.name, func.name LIMIT 5",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("File-Function relationship test:")
        logger.info(str(rel_test_result.content))
        
        # Test 8: Count all nodes and relationships
        logger.info("\n=== Testing Database Size ===")
        
        count_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "MATCH (n) RETURN count(n) as total_nodes",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Node count:")
        logger.info(str(count_result.content))
        
        rel_count_result = await session.call_tool(
            "query_cpg_only",
            {
                "cypher_query": "MATCH ()-[r]->() RETURN count(r) as total_relationships",
                "config_path": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("Relationship count:")
        logger.info(str(rel_count_result.content))
        
        logger.info("✅ Schema alignment debugging completed")
        
    except Exception as e:
        logger.error(f"❌ Schema debugging failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("project-analyzer-server")
        logger.info("✓ MCP session closed")


if __name__ == "__main__":
    asyncio.run(debug_schema_alignment())