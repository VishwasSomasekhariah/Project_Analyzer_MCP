#!/usr/bin/env python3
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the test scripts directory to the path
sys.path.insert(0, str(Path(__file__).parent / "test_results" / "test_scripts"))

from mcp_use import MCPClient

# Configure logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def main():
    # Use the same config as the comprehensive test suite
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    logger.info(f"Using config file: {config_file}")
    
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("project-analyzer-server")
    
    logger.info(f"✓ Connected to MCP server")
    logger.info(f"Available tools: {[tool.name for tool in session.tools]}")
    
    # Test query
    test_query = "Find all classes in the HelloWorldApp that implement specific design patterns like Factory, Observer, or Strategy patterns."
    
    logger.info(f"Executing test query: {test_query}")
    
    try:
        result = await session.call_tool(
            "comprehensive_code_analysis",
            {
                "user_query": test_query,
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-fresh-test",
                "max_vector_results": 15,
                "max_cpg_results": 20,
                "use_llm_filtering": True,
                "neo4j_config": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("✓ Tool call completed")
        
        # Parse response
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        if hasattr(result_content, 'text'):
            content_text = result_content.text
        else:
            content_text = str(result_content)
        
        logger.info(f"Raw response length: {len(content_text)}")
        logger.info(f"Raw response preview: {content_text[:500]}...")
        
        try:
            result_data = json.loads(content_text)
            logger.info("✓ JSON parsing successful")
            
            # Check steps - handle nested structure like the test suite
            results = result_data.get("results", {})
            steps = results.get("steps", {})
            logger.info(f"Available steps: {list(steps.keys())}")
            
            cypher_step = steps.get("3_cypher_generation", {})
            logger.info(f"Cypher step: {cypher_step}")
            
            # Check if queries field exists
            if "queries" in cypher_step:
                queries = cypher_step["queries"]
                logger.info(f"Found {len(queries)} queries: {queries}")
                
                # Count successful queries
                successful_queries = sum(1 for q in queries if q.get("status") == "success")
                logger.info(f"Successful queries: {successful_queries}/{len(queries)}")
            else:
                logger.warning("No 'queries' field found in cypher step")
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parsing failed: {e}")
            logger.error(f"Raw content: {content_text}")
            
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await session.close()

if __name__ == "__main__":
    asyncio.run(main())