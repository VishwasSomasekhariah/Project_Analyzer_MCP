#!/usr/bin/env python3
"""
Test Cypher queries for extracting file subtrees using CONTAINS relationships.

This demonstrates how to retrieve all symbols needed for LSP cross-reference resolution
without re-parsing files with tree-sitter.

Usage:
    python3 test_cypher_subtree_extraction.py
"""

import json
import subprocess
import sys


def run_cypher_query(query, mcp_config):
    """Execute a Cypher query using project-analyzer CLI."""
    result = subprocess.run(
        ['project-analyzer', '--config-file', mcp_config, 'query', '--cypher', query],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode == 0:
        return result.stdout
    else:
        print(f"❌ Query failed: {result.stderr}")
        return None


def main():
    mcp_config = "/opt/genpod/neo4j_config.json"

    print("="*80)
    print("TESTING CYPHER QUERIES FOR LSP SYMBOL EXTRACTION")
    print("="*80)

    # Test 1: Get all Type nodes in TestFile.cs
    print("\n" + "-"*80)
    print("Query 1: Get all Type nodes with properties for LSP calls")
    print("-"*80)

    query1 = """
    MATCH (f:File {name: 'TestFile.cs'})-[:CONTAINS*]->(t:Type)
    RETURN
      t.name as name,
      t.type_kind as type_kind,
      t.file_path as file_path,
      t.base_list as base_list,
      t.modifier as modifier,
      id(t) as node_id
    """

    print(f"\nQuery:\n{query1}")
    print("\nResults:")
    result = run_cypher_query(query1, mcp_config)
    if result:
        print(result)
        print("\n✅ This gives us all Type nodes without re-parsing!")
        print("   - Names for LSP lookups")
        print("   - base_list (JSON) shows what needs cross-file resolution")
        print("   - node_id for creating relationships later")

    # Test 2: Get complete subtree structure
    print("\n" + "-"*80)
    print("Query 2: Get complete file subtree with hierarchy")
    print("-"*80)

    query2 = """
    MATCH path = (f:File {name: 'TestFile.cs'})-[:CONTAINS*]->(n)
    RETURN
      f.name as file_name,
      labels(n) as node_type,
      n.name as node_name,
      length(path) as depth
    ORDER BY depth, node_name
    LIMIT 20
    """

    print(f"\nQuery:\n{query2}")
    print("\nResults:")
    result = run_cypher_query(query2, mcp_config)
    if result:
        print(result)
        print("\n✅ Shows the complete containment hierarchy!")
        print("   File -> Type -> Variable/Function")

    # Test 3: Get only types with inheritance/implementation (optimize for cross-file pass)
    print("\n" + "-"*80)
    print("Query 3: Get Type nodes that need cross-file resolution")
    print("-"*80)

    query3 = """
    MATCH (f:File {name: 'TestFile.cs'})-[:CONTAINS*]->(t:Type)
    WHERE t.base_list IS NOT NULL
    RETURN
      t.name as type_name,
      t.type_kind as type_kind,
      t.base_list as base_list,
      id(t) as node_id
    """

    print(f"\nQuery:\n{query3}")
    print("\nResults:")
    result = run_cypher_query(query3, mcp_config)
    if result:
        print(result)
        print("\n✅ Filters only types that need LSP cross-reference lookups!")
        print("   - Skips types with no base_list")
        print("   - base_list contains target type names for LSP")

    # Test 4: Deserialize JSON properties to demonstrate round-trip
    print("\n" + "-"*80)
    print("Query 4: Verify JSON deserialization works")
    print("-"*80)

    query4 = """
    MATCH (t:Type {name: 'MyTestClass'})
    RETURN
      t.name as name,
      t.base_list as base_list_json
    """

    print(f"\nQuery:\n{query4}")
    print("\nResults:")
    result = run_cypher_query(query4, mcp_config)
    if result:
        print(result)

        # Show how to deserialize
        print("\n📊 How to use in Python:")
        print("```python")
        print("import json")
        print("base_list_json = '[\"BaseClass\", \"IInterface1\", \"IInterface2\"]'")
        print("base_list = json.loads(base_list_json)")
        print("print(base_list)  # ['BaseClass', 'IInterface1', 'IInterface2']")
        print("")
        print("# Now use for LSP lookup:")
        print("for base_type_name in base_list:")
        print("    # Call LSP to find definition of base_type_name")
        print("    target = lsp_client.find_definition(base_type_name, file_path, position)")
        print("    if target:")
        print("        # Create INHERITS_FROM or IMPLEMENTS relationship")
        print("        create_relationship(t.node_id, target.node_id, 'INHERITS_FROM')")
        print("```")

    # Test 5: Get Variable nodes with metadata
    print("\n" + "-"*80)
    print("Query 5: Get Variable nodes with complex metadata")
    print("-"*80)

    query5 = """
    MATCH (f:File {name: 'TestFile.cs'})-[:CONTAINS*]->(v:Variable)
    WHERE v.metadata IS NOT NULL
    RETURN
      v.name as var_name,
      v.variable_type as var_type,
      v.metadata as metadata_json
    """

    print(f"\nQuery:\n{query5}")
    print("\nResults:")
    result = run_cypher_query(query5, mcp_config)
    if result:
        print(result)
        print("\n✅ Shows List[Dict] stored as JSON string!")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY: TWO-PASS ARCHITECTURE WITH GRAPH-BASED SYMBOL EXTRACTION")
    print("="*80)

    print("""
PASS 1: Intra-File Analysis
----------------------------
✅ Parse each file with tree-sitter
✅ Extract all nodes (File, Type, Function, Variable)
✅ Serialize complex properties (base_list, imports, symbols_location) to JSON
✅ Insert nodes into Neo4j via CLI
✅ Create CONTAINS relationships (File -> Type -> Variable/Function)
✅ Memory: One file at a time (streaming)

PASS 2: Cross-File Relationship Resolution (OPTIMIZED)
-------------------------------------------------------
For each file that needs cross-file resolution:

1️⃣  Query Neo4j for Type nodes (instead of re-parsing):

    MATCH (f:File {file_path: $file_path})-[:CONTAINS*]->(t:Type)
    WHERE t.base_list IS NOT NULL
    RETURN t.name, t.base_list, t.start_point, id(t)

2️⃣  Deserialize base_list JSON:

    base_list = json.loads(t.base_list)
    # ["BaseClass", "IInterface1", "IInterface2"]

3️⃣  For each base type name, call LSP to find definition:

    target_location = lsp_client.find_definition(
        base_type_name,
        file_path=t.file_path,
        position=t.start_point
    )

4️⃣  Query Neo4j to find target node:

    MATCH (target:Type {name: $base_type_name, file_path: $target_file})
    RETURN id(target)

5️⃣  Create cross-file relationship:

    MATCH (source:Type) WHERE id(source) = $source_id
    MATCH (target:Type) WHERE id(target) = $target_id
    CREATE (source)-[:INHERITS_FROM]->(target)

✅ NO RE-PARSING with tree-sitter!
✅ All data comes from Neo4j graph
✅ Memory: Only lightweight symbol cache + LSP client
✅ Scalable: Process files one-at-a-time or in batches

PERFORMANCE BENEFITS
--------------------
❌ OLD: Parse file -> Extract nodes -> Store in memory -> Resolve -> Insert
✅ NEW: Query nodes from Neo4j -> Deserialize -> Call LSP -> Create relationships

⚡ Faster: No redundant tree-sitter parsing
⚡ Memory: Bounded by batch size, not entire codebase
⚡ Reliable: Single source of truth (Neo4j graph)
⚡ Resumable: Can checkpoint and restart at any file
    """)

    print("\n" + "="*80)
    print("NEXT STEPS")
    print("="*80)
    print("""
1. Implement ScalableCrossFileResolver class
2. Add LSP client integration for find_definition
3. Test on real C# project with multiple files
4. Measure performance vs. old approach
5. Add progress tracking and checkpointing
    """)


if __name__ == "__main__":
    main()
