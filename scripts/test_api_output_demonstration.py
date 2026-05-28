#!/usr/bin/env python3
"""
Demonstrate what get_schema_for_subquery API returns.
Save complete output to JSON file.
"""
import asyncio
import yaml
import sys
import json
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("=" * 80)
    print("DEMONSTRATING get_schema_for_subquery API OUTPUT")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/demo_api_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing schema manager...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    # Test with actual subquery from approach packet
    subquery = "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"

    print(f"Subquery:")
    print(f"  {subquery}")
    print()

    # Call the API
    print("Calling get_schema_for_subquery()...")
    result = await schema_manager.get_schema_for_subquery(
        subquery_text=subquery,
        format='text',
        max_path_depth=5
    )
    print("✅ API call complete\n")

    # Save to JSON file
    output_file = "/tmp/api_output_demonstration.json"

    # Convert to JSON-serializable format (schema_text might be large, keep it)
    json_result = {
        'node_types': result['node_types'],
        'relationship_types': result['relationship_types'],
        'node_schemas': result['node_schemas'],
        'relationship_schemas': result['relationship_schemas'],
        'paths': result['paths'],
        'schema_text': result['schema_text'],
        'extraction_method': result['extraction_method'],
        'extraction_params': result['extraction_params'],
        'cache_stats': result['cache_stats']
    }

    with open(output_file, 'w') as f:
        json.dump(json_result, f, indent=2)

    print(f"📄 Full output saved to: {output_file}")
    print()

    # Show summary
    print("=" * 80)
    print("OUTPUT SUMMARY")
    print("=" * 80)
    print()

    print(f"1. Extracted Node Types ({len(result['node_types'])}):")
    for nt in result['node_types']:
        print(f"   • {nt}")
    print()

    print(f"2. Extracted Relationship Types ({len(result['relationship_types'])}):")
    for rt in result['relationship_types']:
        print(f"   • {rt}")
    print()

    print(f"3. Node Schemas ({len(result['node_schemas'])} schemas):")
    for node_type, schema in result['node_schemas'].items():
        print(f"   • {node_type}:")
        print(f"       Description: {schema.get('description', 'N/A')[:80]}...")
        print(f"       Properties: {', '.join(schema.get('properties', [])[:5])}")
    print()

    print(f"4. Relationship Schemas ({len(result['relationship_schemas'])} schemas):")
    for rel_type, schema in result['relationship_schemas'].items():
        print(f"   • {rel_type}:")
        print(f"       Description: {schema.get('description', 'N/A')[:80]}...")
        from_types = schema.get('from', [])
        to_types = schema.get('to', [])
        if from_types and to_types:
            print(f"       Cardinality: ({', '.join(from_types[:2])})-[{rel_type}]->({', '.join(to_types[:2])})")
    print()

    print(f"5. Discovered Paths ({len(result['paths'])} path patterns):")
    # Group by depth
    paths_by_depth = {}
    for path in result['paths']:
        depth = path['depth']
        if depth not in paths_by_depth:
            paths_by_depth[depth] = []
        paths_by_depth[depth].append(path)

    for depth in sorted(paths_by_depth.keys()):
        print(f"   Depth {depth} ({len(paths_by_depth[depth])} patterns):")
        for path in paths_by_depth[depth][:3]:  # Show first 3 per depth
            rels_str = " → ".join(path['rels'])
            via_str = f" (via {', '.join(path['via'])})" if path.get('via') else ""
            print(f"      • ({path['from']})-[{rels_str}]->({path['to']}){via_str}")
        if len(paths_by_depth[depth]) > 3:
            print(f"      ... and {len(paths_by_depth[depth]) - 3} more")
    print()

    print(f"6. Extraction Method: {result['extraction_method']}")
    print(f"   Parameters: {result['extraction_params']}")
    print()

    print(f"7. Cache Stats:")
    for key, value in result['cache_stats'].items():
        print(f"   • {key}: {value}")
    print()

    print(f"8. Schema Text Length: {len(result['schema_text'])} characters")
    print(f"   (Full LLM-ready formatted schema included in JSON)")
    print()

    print("=" * 80)
    print("JSON STRUCTURE")
    print("=" * 80)
    print()
    print("The JSON file contains:")
    print("  {")
    print("    'node_types': [...],              # List of extracted node type names")
    print("    'relationship_types': [...],      # List of extracted relationship type names")
    print("    'node_schemas': {                 # Full schema for each node type")
    print("      'NodeType': {")
    print("        'description': '...',         # Semantic description")
    print("        'properties': [...],          # Available properties")
    print("        'indexed_properties': [...]   # Indexed properties (for WHERE)")
    print("      }")
    print("    },")
    print("    'relationship_schemas': {         # Full schema for each relationship")
    print("      'REL_TYPE': {")
    print("        'description': '...',         # Semantic description")
    print("        'from': [...],                # Source node types")
    print("        'to': [...],                  # Target node types")
    print("        'properties': [...]           # Available properties")
    print("      }")
    print("    },")
    print("    'paths': [                        # All discovered path patterns")
    print("      {")
    print("        'from': 'SourceType',")
    print("        'to': 'TargetType',")
    print("        'rels': ['REL1', 'REL2'],     # Relationship sequence")
    print("        'via': ['IntermediateType'],  # Intermediate node types")
    print("        'depth': 2,                   # Path length")
    print("        'count': 42                   # Number of instances")
    print("      }")
    print("    ],")
    print("    'schema_text': '...',             # LLM-ready formatted text")
    print("    'extraction_method': 'hybrid',")
    print("    'extraction_params': {...},")
    print("    'cache_stats': {...}")
    print("  }")
    print()

    print("=" * 80)
    print(f"✅ Complete output saved to: {output_file}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
