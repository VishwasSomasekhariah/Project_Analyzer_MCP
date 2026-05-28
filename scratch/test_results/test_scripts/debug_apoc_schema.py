#!/usr/bin/env python3
"""
Debug script for APOC schema alignment using the working neo4j_execute_query tool.
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


async def debug_apoc_schema():
    """Debug schema alignment using APOC procedures."""
    logger.info("Starting APOC schema alignment debugging...")
    
    # Connect to Neo4j MCP server
    client = MCPClient.from_config_file("/opt/genpod/neo4j_config.json")
    session = await client.create_session("neo4j_memory")
    
    logger.info("✓ Connected to Neo4j MCP server")
    
    try:
        # Test 1: Get actual database schema using APOC
        logger.info("=== Test 1: APOC meta.schema() ===")
        
        try:
            schema_result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": "CALL apoc.meta.schema() YIELD value RETURN value",
                    "limit": 100
                }
            )
            
            logger.info("APOC schema result:")
            logger.info(str(schema_result.content))
        except Exception as e:
            logger.warning(f"APOC meta.schema() failed: {e}")
        
        # Test 2: Get node type statistics
        logger.info("\n=== Test 2: APOC meta.stats() ===")
        
        try:
            stats_result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": "CALL apoc.meta.stats() YIELD labels, relTypes RETURN labels, relTypes",
                    "limit": 100
                }
            )
            
            logger.info("APOC stats result:")
            logger.info(str(stats_result.content))
        except Exception as e:
            logger.warning(f"APOC meta.stats() failed: {e}")
        
        # Test 3: Get relationship types
        logger.info("\n=== Test 3: Relationship Types ===")
        
        rel_types_result = await session.call_tool(
            "neo4j_execute_query",
            {
                "query": "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType",
                "limit": 100
            }
        )
        
        logger.info("Relationship types:")
        logger.info(str(rel_types_result.content))
        
        # Test 4: Sample relationships
        logger.info("\n=== Test 4: Sample Relationships ===")
        
        sample_rels_result = await session.call_tool(
            "neo4j_execute_query",
            {
                "query": "MATCH (a)-[r]->(b) RETURN labels(a) as fromLabels, type(r) as relationshipType, labels(b) as toLabels LIMIT 10",
                "limit": 100
            }
        )
        
        logger.info("Sample relationships:")
        logger.info(str(sample_rels_result.content))
        
        # Test 5: Check for specific schema patterns
        logger.info("\n=== Test 5: Schema Pattern Check ===")
        
        # Check File -> Function relationships
        file_func_result = await session.call_tool(
            "neo4j_execute_query",
            {
                "query": "MATCH (file:File)-[r]->(func:Function) RETURN file.name, type(r) as relationship, func.name LIMIT 5",
                "limit": 100
            }
        )
        
        logger.info("File-Function relationships:")
        logger.info(str(file_func_result.content))
        
        # Test 6: Get property distribution
        logger.info("\n=== Test 6: Property Distribution ===")
        
        prop_dist_result = await session.call_tool(
            "neo4j_execute_query",
            {
                "query": """
                MATCH (n) 
                WITH labels(n) as nodeLabels, keys(n) as properties
                UNWIND nodeLabels as label
                UNWIND properties as prop
                RETURN label, prop, count(*) as frequency
                ORDER BY label, frequency DESC
                """,
                "limit": 100
            }
        )
        
        logger.info("Property distribution:")
        logger.info(str(prop_dist_result.content))
        
        # Test 7: Try APOC procedures to analyze graph structure
        logger.info("\n=== Test 7: APOC Graph Analysis ===")
        
        try:
            graph_analysis_result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": "CALL apoc.meta.graph() YIELD nodes, relationships RETURN nodes, relationships",
                    "limit": 100
                }
            )
            
            logger.info("APOC graph analysis:")
            logger.info(str(graph_analysis_result.content))
        except Exception as e:
            logger.warning(f"APOC meta.graph() failed: {e}")
        
        logger.info("✅ APOC schema alignment debugging completed")
        
    except Exception as e:
        logger.error(f"❌ APOC schema debugging failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("neo4j_memory")
        logger.info("✓ Neo4j MCP session closed")


if __name__ == "__main__":
    asyncio.run(debug_apoc_schema())