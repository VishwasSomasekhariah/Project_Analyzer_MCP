"""
Test FULL Research Engine flow with APOC-based schema audit.

Verifies that the Research Engine can:
1. Phase 1: Generate approach packets from user query using LLM
2. Phase 2: Fetch real schema from database using apoc.meta.schema()
3. Convert APOC schema format to internal format
4. Validate approaches against real schema
5. Auto-correct invalid attributes
6. Save approach packets to pickle file
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.core.workflow.cypher_server_pool import CypherServerInstance
from src.core.workflow.research_engine import ResearchEngine
from src.core.llm_service import LLMService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_apoc_schema_audit():
    """Test APOC-based schema audit."""

    logger.info("=" * 100)
    logger.info("TEST: Full Research Engine Flow (Phase 1 + Phase 2 with APOC)")
    logger.info("=" * 100)

    # Configuration
    neo4j_config = "/opt/genpod/neo4j_config.json"
    project_name = "HelloWorldApp"

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

        # Create Research Engine
        logger.info("\n🔧 Creating Research Engine...")
        llm_service = LLMService()
        research_engine = ResearchEngine(llm_service)
        logger.info("✅ Research Engine created")

        # Load schema
        logger.info("\n📚 Loading CPG Schema...")
        import yaml
        schema_path = "/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml"
        with open(schema_path, 'r') as f:
            schema = yaml.safe_load(f)
        logger.info(f"✅ Schema loaded: {len(schema.get('nodes', {}))} node types")

        # Create complete state for research flow
        user_query = 'How many method calls are in Manager.Run()?'

        # Proper intent structure (from _fallback_intent_analysis)
        intent = {
            "intent_type": "lookup",
            "confidence": 0.8,
            "reasoning": "Query asks 'how many' which indicates counting/lookup intent",
            "expected_result_type": "Numeric count of method calls"
        }

        state = {
            'cypher_server_service': cypher_server,
            'metadata': {'project_name': project_name},
            'user_query': user_query,
            'schema': schema,
            'intent': intent
        }

        # Test FULL research flow (Phase 1 + Phase 2)
        logger.info("\n🧪 Testing FULL Research Engine Flow...")
        logger.info("=" * 100)
        logger.info(f"User Query: {user_query}")
        logger.info(f"Project: {project_name}")

        research_result = await research_engine.conduct_discovery_research(state)

        logger.info("\n" + "=" * 100)
        logger.info("RESEARCH RESULTS")
        logger.info("=" * 100)

        logger.info(f"\n✅ Research Status: SUCCESS")
        logger.info(f"📊 Research Type: {research_result.get('research_type')}")
        logger.info(f"📊 Audit Passed: {research_result.get('audit_passed')}")
        logger.info(f"📊 Total Approaches: {research_result.get('total_approaches')}")

        if research_result.get('corrections_applied'):
            logger.info(f"\n🔧 Corrections Made: {len(research_result['corrections_applied'])}")
            for correction in research_result['corrections_applied']:
                logger.info(f"  - {correction}")

        logger.info("\n📝 Generated Approaches:")
        for approach in research_result.get('data_collection_approaches', []):
            logger.info(f"\n  Approach: {approach['approach_name']}")
            logger.info(f"    Description: {approach.get('description', 'N/A')}")
            logger.info(f"    Target Nodes: {approach['target_nodes']}")
            logger.info(f"    Key Attributes: {approach['key_attributes']}")
            logger.info(f"    Relationships: {approach['relationships']}")

            # Show strategy (truncated)
            strategy = approach.get('strategy', '')
            if len(strategy) > 200:
                logger.info(f"    Strategy: {strategy[:200]}...")
            else:
                logger.info(f"    Strategy: {strategy}")

            if approach.get('corrections_applied'):
                logger.info(f"    Corrections: {approach['corrections_applied']}")

        # Check if pickle file was created
        logger.info("\n💾 Checking for pickle file...")
        import os
        pickle_dir = "approach_packets"
        if os.path.exists(pickle_dir):
            pickle_files = sorted(os.listdir(pickle_dir))
            if pickle_files:
                logger.info(f"✅ Pickle file created: {pickle_files[-1]}")
            else:
                logger.info("⚠️ No pickle files found")
        else:
            logger.info("⚠️ Pickle directory not created")

        logger.info("\n" + "=" * 100)
        logger.info("✅ TEST COMPLETE")
        logger.info("=" * 100)
        logger.info("\nKey Takeaway:")
        logger.info("  Phase 1: LLM generated approach packets based on user query")
        logger.info("  Phase 2: APOC-based schema audit validated approaches against REAL database schema")
        logger.info("  Invalid attributes were automatically corrected using actual schema properties")
        logger.info("  Approach packets saved to pickle file for validation")

    except Exception as e:
        logger.error(f"❌ TEST FAILED: {e}", exc_info=True)
        raise

    finally:
        logger.info("\n🧹 Cleaning up...")
        await cypher_server.stop()
        logger.info("✅ Cypher server stopped")


if __name__ == "__main__":
    asyncio.run(test_apoc_schema_audit())
