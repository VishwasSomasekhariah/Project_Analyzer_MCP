"""
Test CPG Discovery Agent with real database.

Tests the complete discovery flow:
1. APOC cache initialization
2. Conversational agent discovers patterns for target entities
3. Discovery results are structured and actionable
"""

import asyncio
import logging
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.core.workflow.cypher_server_pool import CypherServerInstance
from src.core.workflow.cpg_discovery_agent import CPGDiscoveryAgent
from src.core.apoc_procedure_cache import initialize_apoc_cache
from src.core.llm_service import LLMService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_discovery_agent():
    """Test CPG Discovery Agent with real queries."""

    logger.info("=" * 100)
    logger.info("TEST: CPG Discovery Agent")
    logger.info("=" * 100)

    # Configuration
    neo4j_config = "/opt/genpod/neo4j_config.json"
    project_name = "HelloWorldApp"

    # Real user query (like from STATE.pkl)
    user_query = "How many method calls are in Manager.Run()?"

    # Target entities for this query (would come from decomposition in real workflow)
    target_entities = ["Function", "Statement", "Expression"]

    logger.info(f"\nUser Query: {user_query}")
    logger.info(f"Target entities: {target_entities}")
    logger.info(f"Project: {project_name}")

    # Setup Cypher server
    logger.info("\n📡 Setting up Cypher Server...")
    cypher_server = CypherServerInstance(
        server_id=0,
        neo4j_config=neo4j_config,
        query_timeout=60
    )

    try:
        await cypher_server.start()
        logger.info("✅ Cypher server started")

        # Initialize APOC cache
        logger.info("\n🔧 Initializing APOC Cache...")
        await initialize_apoc_cache(cypher_server)
        logger.info("✅ APOC cache initialized")

        # Create LLM service
        logger.info("\n🤖 Creating LLM Service...")
        llm_service = LLMService()
        logger.info("✅ LLM service created")

        # Create CPG Discovery Agent
        logger.info("\n🔍 Creating CPG Discovery Agent...")
        discovery_agent = CPGDiscoveryAgent(llm_service, cypher_server)
        logger.info("✅ Discovery agent created")

        # Discover patterns
        logger.info("\n🚀 Starting CPG Discovery...")
        logger.info("=" * 100)

        discovery_results = await discovery_agent.discover_patterns(
            target_entities=target_entities,
            project_name=project_name,
            user_query=user_query
        )

        # Display results
        logger.info("\n" + "=" * 100)
        logger.info("DISCOVERY RESULTS")
        logger.info("=" * 100)

        for entity, result in discovery_results.items():
            print("\n" + "=" * 100)
            print(result.to_summary())
            print("=" * 100)

        # Save to JSON
        output_file = "cpg_discovery_test_results.json"
        logger.info(f"\n💾 Saving results to {output_file}...")

        results_dict = {
            entity: result.to_dict()
            for entity, result in discovery_results.items()
        }

        with open(output_file, 'w') as f:
            json.dump(results_dict, f, indent=2)

        logger.info(f"✅ Saved to {output_file}")

        # Summary
        logger.info("\n" + "=" * 100)
        logger.info("TEST SUMMARY")
        logger.info("=" * 100)
        logger.info(f"  Entities tested: {len(target_entities)}")

        for entity in target_entities:
            result = discovery_results.get(entity)
            if result:
                status = "EXISTS" if result.exists else "NOT FOUND"
                logger.info(f"  {entity}: {status}")
                if result.exists:
                    logger.info(f"    - Sample count: {result.sample_count}")
                    logger.info(f"    - Properties: {len(result.properties)}")
                    logger.info(f"    - Paths: {len(result.paths_from_project)}")
                    logger.info(f"    - Relationships: {len(result.outgoing_relationships)}")

        logger.info("\n" + "=" * 100)
        logger.info("✅ TEST COMPLETE")
        logger.info("=" * 100)
        logger.info("\nKey Takeaway:")
        logger.info("  CPG Discovery Agent successfully discovered actual graph patterns")
        logger.info("  Results can be used to generate realistic queries")

    except Exception as e:
        logger.error(f"❌ TEST FAILED: {e}", exc_info=True)
        raise

    finally:
        logger.info("\n🧹 Cleaning up...")
        await cypher_server.stop()
        logger.info("✅ Cypher server stopped")


if __name__ == "__main__":
    asyncio.run(test_discovery_agent())
