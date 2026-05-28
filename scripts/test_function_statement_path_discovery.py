"""Test path discovery between Function and Statement nodes."""
import asyncio
import yaml
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager


async def main():
    print("=" * 80)
    print("Testing Path Discovery: Function → Statement")
    print("=" * 80)

    # Load YAML schema
    with open('src/schemas/project_knowledgebase_graph_schema.yaml', 'r') as f:
        yaml_schema = yaml.safe_load(f)

    # Create cypher server
    cypher_server = await create_cypher_server_service('neo4j_config.json')

    # Create DynamicSchemaManager
    schema_manager = DynamicSchemaManager(
        cypher_server=cypher_server,
        yaml_schema=yaml_schema
    )

    # Wait for schema to load
    await schema_manager._load_event.wait()

    print("\n1. Testing with NO relationship filter (should find all paths):")
    print("-" * 80)
    paths_no_filter = await schema_manager.get_paths_between(
        source='Function',
        target='Statement',
        relationship_types=None,  # No filter - find ALL paths
        max_depth=5
    )

    print(f"   Found {len(paths_no_filter)} paths:")
    for i, path in enumerate(paths_no_filter, 1):
        depth = path['depth']
        rels = path['rels']
        via = path.get('via', [])

        if depth == 1:
            print(f"      {i}. Direct: -[{rels[0]}]->")
        else:
            path_str = []
            for j, rel in enumerate(rels):
                if j < len(via):
                    path_str.append(f"-[{rel}]-> {via[j]}")
                else:
                    path_str.append(f"-[{rel}]->")
            print(f"      {i}. {depth}-hop: {' '.join(path_str)}")

    print("\n2. Testing with relationship filter (REFERENCES, CONTAINS, IMPLEMENTS, CALLS):")
    print("-" * 80)
    paths_with_filter = await schema_manager.get_paths_between(
        source='Function',
        target='Statement',
        relationship_types=['REFERENCES', 'CONTAINS', 'IMPLEMENTS', 'CALLS'],
        max_depth=5
    )

    print(f"   Found {len(paths_with_filter)} paths:")
    for i, path in enumerate(paths_with_filter, 1):
        depth = path['depth']
        rels = path['rels']
        via = path.get('via', [])

        if depth == 1:
            print(f"      {i}. Direct: -[{rels[0]}]->")
        else:
            path_str = []
            for j, rel in enumerate(rels):
                if j < len(via):
                    path_str.append(f"-[{rel}]-> {via[j]}")
                else:
                    path_str.append(f"-[{rel}]->")
            print(f"      {i}. {depth}-hop: {' '.join(path_str)}")

    print("\n3. Checking for specific CONTAINS path through Block:")
    print("-" * 80)
    contains_via_block = [
        p for p in paths_with_filter
        if 'CONTAINS' in p['rels'] and 'Block' in p.get('via', [])
    ]

    if contains_via_block:
        print(f"   ✅ FOUND {len(contains_via_block)} CONTAINS path(s) through Block:")
        for path in contains_via_block:
            print(f"      Rels: {path['rels']}, Via: {path['via']}, Depth: {path['depth']}")
    else:
        print("   ❌ NO CONTAINS path through Block found!")
        print("   This explains why validation feedback doesn't show it!")

    print("\n4. Checking what REFERENCES paths exist:")
    print("-" * 80)
    references_paths = [
        p for p in paths_with_filter
        if 'REFERENCES' in p['rels']
    ]

    print(f"   Found {len(references_paths)} REFERENCES path(s):")
    for path in references_paths:
        depth = path['depth']
        rels = path['rels']
        via = path.get('via', [])

        if depth == 1:
            print(f"      Direct: -[{rels[0]}]->")
        else:
            path_str = []
            for j, rel in enumerate(rels):
                if j < len(via):
                    path_str.append(f"-[{rel}]-> {via[j]}")
                else:
                    path_str.append(f"-[{rel}]->")
            print(f"      {depth}-hop: {' '.join(path_str)}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total paths found: {len(paths_with_filter)}")
    print(f"CONTAINS via Block: {len(contains_via_block)} {'✅ FOUND' if contains_via_block else '❌ MISSING'}")
    print(f"REFERENCES paths: {len(references_paths)}")

    if not contains_via_block:
        print("\n⚠️  BUG CONFIRMED: The Function→Block→Statement CONTAINS path is NOT being discovered!")
        print("   This explains why validation feedback shows only REFERENCES path.")

    # Cleanup
    await cypher_server.cleanup()
    print("\n✅ Test complete\n")


if __name__ == '__main__':
    asyncio.run(main())
