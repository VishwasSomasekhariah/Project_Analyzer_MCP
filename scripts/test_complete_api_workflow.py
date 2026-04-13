#!/usr/bin/env python3
"""
Complete API Workflow Test - Shows FULL output including:
1. Type extraction (nodes + relationships)
2. Filtered schema subset (only extracted types)
3. Path discovery (from cache)

This is what get_schema_for_subquery() would return to the LLM.
"""
import asyncio
import json
import yaml
import sys

sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


SUBQUERIES = {
    "SQ1": {
        "query": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
        "description": "Find function by name within a specific type"
    },
    "SQ2": {
        "query": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
        "description": "Find constructor calls and their declaring types"
    },
    "SQ3": {
        "query": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
        "description": "Find return statements with new instantiations"
    },
    "SQ4": {
        "query": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
        "description": "Find variable declarations with new instantiations"
    }
}


async def main():
    print("=" * 100)
    print("COMPLETE API WORKFLOW - FULL OUTPUT")
    print("=" * 100)
    print()
    print("This shows what get_schema_for_subquery() returns:")
    print("  1. Extracted node types")
    print("  2. Extracted relationship types")
    print("  3. Filtered schema (only extracted types)")
    print("  4. Paths between node types (from cache)")
    print()
    print("Configuration: alpha=0.15, threshold=0.60")
    print()
    print("=" * 100)
    print()

    # Initialize
    print("Initializing DynamicSchemaManager...")
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/complete_api_workflow_cache.json",
        yaml_schema=yaml_schema,
        embedding_model='all-MiniLM-L6-v2'
    )

    await schema_manager.initialize_background()
    print("✅ Initialized")
    print()

    all_results = {}

    for sq_id, sq_data in SUBQUERIES.items():
        print("=" * 100)
        print(f"{sq_id}: {sq_data['description']}")
        print("=" * 100)
        print()
        print(f"Query: {sq_data['query']}")
        print()
        print("-" * 100)

        # Call the COMPLETE API method
        result = await schema_manager.get_schema_for_subquery(
            subquery_text=sq_data['query']
        )

        print()
        print("API RESPONSE:")
        print("-" * 100)
        print()

        # 1. Extracted Types
        print("1️⃣  EXTRACTED TYPES:")
        print()
        print(f"   Node Types ({len(result['node_types'])}):")
        for nt in result['node_types']:
            print(f"     • {nt}")
        print()
        print(f"   Relationship Types ({len(result['relationship_types'])}):")
        if result['relationship_types']:
            for rt in result['relationship_types']:
                print(f"     • {rt}")
        else:
            print("     (none)")
        print()

        # 2. Filtered Schema
        print("2️⃣  FILTERED SCHEMA SUBSET:")
        print()
        print(f"   Node Definitions ({len(result['node_schemas'])}):")
        for node_type, node_def in result['node_schemas'].items():
            print(f"     • {node_type}:")
            print(f"         Description: {node_def['description'][:100]}...")
            print(f"         Properties: {', '.join(node_def['properties'][:5])}{'...' if len(node_def['properties']) > 5 else ''}")
            print(f"         Count: {node_def['count']}")
        print()

        print(f"   Relationship Definitions ({len(result['relationship_schemas'])}):")
        if result['relationship_schemas']:
            for rel_type, rel_def in result['relationship_schemas'].items():
                print(f"     • {rel_type}:")
                print(f"         Description: {rel_def['description'][:100]}...")
                print(f"         Cardinality pairs: {len(rel_def['cardinality'])}")
                print(f"         Count: {rel_def['count']}")
        else:
            print("     (none)")
        print()

        # 3. Paths
        print("3️⃣  DISCOVERED PATHS:")
        print()
        if result['paths']:
            for path in result['paths']:
                via_str = ' → '.join(path.get('via', []))
                rels_str = ', '.join(path['rels'])
                print(f"     • {path['from']} → {path['to']}")
                print(f"         Via: {via_str if via_str else '(direct)'}")
                print(f"         Relationships: {rels_str}")
                print(f"         Depth: {path['depth']} hops")
        else:
            print("     (none)")
        print()

        # Save detailed result for this subquery
        all_results[sq_id] = {
            'query': sq_data['query'],
            'description': sq_data['description'],
            'api_response': result
        }

        print()

    # Save complete results including reconciled schema
    output_path = "/tmp/complete_api_workflow_results.json"
    full_output = {
        'reconciled_schema': schema_manager._reconciled_schema,
        'subquery_results': all_results
    }
    with open(output_path, 'w') as f:
        json.dump(full_output, f, indent=2)

    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print()
    print(f"Tested {len(SUBQUERIES)} subqueries with complete API workflow")
    print()
    print("Output Components:")
    print("  ✅ Type extraction (nodes + relationships)")
    print("  ✅ Filtered schema subset")
    print("  ✅ Path discovery from cache")
    print()
    print(f"Detailed results saved to: {output_path}")
    print()
    print("This is the complete information provided to the LLM for Cypher generation!")
    print()


if __name__ == "__main__":
    asyncio.run(main())
