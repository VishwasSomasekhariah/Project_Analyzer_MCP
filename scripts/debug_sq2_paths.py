"""Debug script to check what paths are discovered for SQ2 scenario."""
import asyncio
import sys
sys.path.insert(0, '/opt/genpod')

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager

async def main():
    # Initialize schema manager
    manager = DynamicSchemaManager(
        cypher_config_path='neo4j_config.json',
        yaml_schema_path='src/schemas/cpg_ontology_schema.yaml'
    )

    await manager.initialize()

    # Simulate SQ2 query from Run 1:
    # "Retrieve all Statement nodes contained within the Block nodes of the 'CreateWorkers' Function node that instantiate Type nodes."
    subquery_text = "Retrieve all Statement nodes contained within the Block nodes of the 'CreateWorkers' Function node that instantiate Type nodes."

    print(f"Testing SQ2 scenario...")
    print(f"Query: {subquery_text}\n")

    # Get filtered schema (this is what happens in Run 1 SQ2)
    schema_result = await manager.filter_schema_for_subquery(
        subquery_text=subquery_text,
        available_premises=[],
        format='dict'
    )

    print(f"✅ Nodes extracted: {schema_result.get('node_types', [])}")
    print(f"✅ Relationships extracted: {schema_result.get('relationship_types', [])}")
    print(f"✅ Total paths discovered: {len(schema_result.get('paths', []))}\n")

    # Now check specifically for Function → Statement paths
    paths = schema_result.get('paths', [])
    function_to_statement = [p for p in paths if p.get('from') == 'Function' and p.get('to') == 'Statement']

    print(f"=== Function → Statement paths: {len(function_to_statement)} found ===")
    for i, path in enumerate(function_to_statement, 1):
        depth = path.get('depth')
        rels = path.get('rels', [])
        via = path.get('via', [])

        if depth == 1:
            print(f"  {i}. Direct: -[{rels[0]}]->")
        else:
            path_str = []
            for j, rel in enumerate(rels):
                if j < len(via):
                    path_str.append(f"-[{rel}]-> {via[j]}")
                else:
                    path_str.append(f"-[{rel}]->")
            print(f"  {i}. {depth}-hop: {' '.join(path_str)}")

    # Also check Function → Type paths
    function_to_type = [p for p in paths if p.get('from') == 'Function' and p.get('to') == 'Type']
    print(f"\n=== Function → Type paths: {len(function_to_type)} found ===")
    for i, path in enumerate(function_to_type, 1):
        depth = path.get('depth')
        rels = path.get('rels', [])
        via = path.get('via', [])

        if depth == 1:
            print(f"  {i}. Direct: -[{rels[0]}]->")
        else:
            path_str = []
            for j, rel in enumerate(rels):
                if j < len(via):
                    path_str.append(f"-[{rel}]-> {via[j]}")
                else:
                    path_str.append(f"-[{rel}]->")
            print(f"  {i}. {depth}-hop: {' '.join(path_str)}")

    # Check Statement → Type paths
    statement_to_type = [p for p in paths if p.get('from') == 'Statement' and p.get('to') == 'Type']
    print(f"\n=== Statement → Type paths: {len(statement_to_type)} found ===")
    if statement_to_type:
        for i, path in enumerate(statement_to_type, 1):
            depth = path.get('depth')
            rels = path.get('rels', [])
            via = path.get('via', [])

            if depth == 1:
                print(f"  {i}. Direct: -[{rels[0]}]->")
            else:
                path_str = []
                for j, rel in enumerate(rels):
                    if j < len(via):
                        path_str.append(f"-[{rel}]-> {via[j]}")
                    else:
                        path_str.append(f"-[{rel}]->")
                print(f"  {i}. {depth}-hop: {' '.join(path_str)}")
    else:
        print("  NO PATH EXISTS")

    await manager.cypher_server.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
