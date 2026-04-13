#!/usr/bin/env python3
"""
Verify that EnrichmentDescription is being used for semantic matching.
"""
import asyncio
import yaml
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("=" * 100)
    print("TESTING ENRICHMENT DESCRIPTION USAGE")
    print("=" * 100)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_enrichment_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    # Check what descriptions are extracted
    print("EXTRACTED DESCRIPTIONS FOR EMBEDDING:")
    print("-" * 100)
    print()

    # Test node descriptions
    print("Node Type Descriptions:")
    print()
    for node_type in ['Type', 'Function', 'Variable', 'Statement']:
        desc = schema_manager._extract_node_description(node_type)
        print(f"{node_type}:")
        print(f"  {desc[:200]}...")
        print()

        # Verify it's using EnrichmentDescription
        enrichment = yaml_schema['NodeDefinitions'][node_type]['Creation'].get('EnrichmentDescription', '')
        technical = yaml_schema['NodeDefinitions'][node_type]['Creation'].get('Description', '')

        if desc.startswith(enrichment[:50]):
            print(f"  ✅ Using EnrichmentDescription")
        elif desc.startswith(technical[:50]):
            print(f"  ⚠️  Using technical Description (EnrichmentDescription not found?)")
        else:
            print(f"  ❓ Using fallback description")
        print()

    # Test relationship descriptions
    print()
    print("Relationship Type Descriptions:")
    print()
    for rel_type in ['CONTAINS', 'CALLS', 'REFERENCES']:
        desc = schema_manager._extract_relationship_description(rel_type)
        print(f"{rel_type}:")
        print(f"  {desc[:200]}...")
        print()

        # Verify it's using EnrichmentDescription
        if rel_type in yaml_schema.get('EdgeDefinitions', {}):
            enrichment = yaml_schema['EdgeDefinitions'][rel_type]['Creation'].get('EnrichmentDescription', '')
            technical = yaml_schema['EdgeDefinitions'][rel_type]['Creation'].get('Description', '')

            if desc.startswith(enrichment[:50]):
                print(f"  ✅ Using EnrichmentDescription")
            elif desc.startswith(technical[:50]):
                print(f"  ⚠️  Using technical Description")
            else:
                print(f"  ❓ Using fallback description")
        else:
            print(f"  ⚠️  No EdgeDefinition found, using fallback")
        print()

    print("=" * 100)
    print("VERIFICATION COMPLETE")
    print("=" * 100)
    print()
    print("If all types show ✅, then EnrichmentDescription is being used correctly!")
    print()


if __name__ == "__main__":
    asyncio.run(main())
