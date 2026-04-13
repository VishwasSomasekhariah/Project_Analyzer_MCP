#!/usr/bin/env python3
"""Quick test to verify DynamicSchemaManager schema loading."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.workflow.cypher_server_pool import CypherServerPool
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_schema_loading():
    """Test that schema manager can load APOC schema."""

    logger.info("="*60)
    logger.info("Testing DynamicSchemaManager Schema Loading")
    logger.info("="*60)

    # Initialize server pool
    pool = CypherServerPool(pool_size=2, neo4j_config="/opt/genpod/neo4j_config.json")
    await pool.initialize()

    # Acquire a server
    server = await pool.acquire()
    logger.info(f"✅ Acquired server from pool")

    # Create schema manager
    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_schema_cache.json",
        yaml_schema=None,
        embedding_model='all-MiniLM-L6-v2'
    )

    logger.info("🔧 Initializing schema manager...")

    # Run initialization
    await schema_manager.initialize_background()

    # Check if schema loaded
    if schema_manager._full_schema:
        logger.info("="*60)
        logger.info("✅ SUCCESS - Schema loaded!")
        logger.info(f"   Node types: {len(schema_manager._full_schema.get('nodes', {}))}")
        logger.info(f"   Relationship types: {len(schema_manager._full_schema.get('relationships', {}))}")
        logger.info("="*60)
        result = True
    else:
        logger.error("="*60)
        logger.error("❌ FAILED - Schema not loaded")
        logger.error("="*60)
        result = False

    # Cleanup
    await pool.shutdown()

    return result

if __name__ == "__main__":
    success = asyncio.run(test_schema_loading())
    sys.exit(0 if success else 1)
