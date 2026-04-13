#!/usr/bin/env python3
"""
Debug the comprehensive analysis response to see what's actually returned
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


async def debug_comprehensive_response():
    """Debug the comprehensive analysis response."""
    logger.info("Debugging comprehensive analysis response...")
    
    # Connect to main MCP server (port 9000)
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    client = MCPClient.from_config_file(config_file)
    session = await client.create_session("project-analyzer-server")
    
    logger.info("✓ Connected to main MCP server")
    
    try:
        # Test the comprehensive analysis
        logger.info("=== Testing Comprehensive Analysis ===")
        
        result = await session.call_tool(
            "comprehensive_code_analysis",
            {
                "user_query": "Find all functions that handle errors or exceptions in the codebase",
                "project_path": "/opt/HelloWorldApp",
                "collection_name": "helloworldapp-fresh-test",
                "max_vector_results": 10,
                "max_cpg_results": 15,
                "use_llm_filtering": True,
                "neo4j_config": "/opt/genpod/neo4j_config.json"
            }
        )
        
        logger.info("✅ Comprehensive analysis completed")
        
        # Log the raw result
        logger.info("=== Raw Result ===")
        logger.info(f"Result type: {type(result)}")
        logger.info(f"Result content type: {type(result.content)}")
        
        if hasattr(result, 'content'):
            if isinstance(result.content, list):
                logger.info(f"Content is a list with {len(result.content)} items")
                for i, item in enumerate(result.content):
                    logger.info(f"Item {i} type: {type(item)}")
                    if hasattr(item, 'text'):
                        logger.info(f"Item {i} text preview: {item.text[:200]}...")
                    else:
                        logger.info(f"Item {i} value: {str(item)[:200]}...")
            else:
                logger.info(f"Content: {str(result.content)[:500]}...")
        
        # Try to extract the actual text
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        
        if hasattr(result_content, 'text'):
            content_text = result_content.text
        else:
            content_text = str(result_content)
        
        logger.info("=== Full Response Text ===")
        logger.info(content_text)
        
        # Try to parse as JSON
        try:
            result_data = json.loads(content_text)
            logger.info("✅ Successfully parsed as JSON")
            
            # Show the structure
            logger.info("=== JSON Structure ===")
            if isinstance(result_data, dict):
                logger.info(f"Top-level keys: {list(result_data.keys())}")
                
                if "steps" in result_data:
                    steps = result_data["steps"]
                    logger.info(f"Steps available: {list(steps.keys())}")
                    
                    for step_name, step_data in steps.items():
                        logger.info(f"Step {step_name}:")
                        if isinstance(step_data, dict):
                            logger.info(f"  Keys: {list(step_data.keys())}")
                            if "status" in step_data:
                                logger.info(f"  Status: {step_data['status']}")
                        else:
                            logger.info(f"  Data: {str(step_data)[:100]}...")
                
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse as JSON: {e}")
            logger.info("Raw content (first 1000 chars):")
            logger.info(content_text[:1000])
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
    finally:
        await client.close_session("project-analyzer-server")
        logger.info("✓ MCP session closed")


if __name__ == "__main__":
    asyncio.run(debug_comprehensive_response())