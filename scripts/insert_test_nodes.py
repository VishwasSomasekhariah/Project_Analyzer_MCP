#!/usr/bin/env python3
"""
Insert a few test nodes with complex properties to demonstrate JSON serialization.
"""

import json
import subprocess
import sys

def insert_node_via_cli(node_type, properties, mcp_config):
    """Insert a single node into Neo4j via CLI."""

    # Build property string for Cypher
    prop_parts = []
    for key, value in properties.items():
        if isinstance(value, str):
            # Escape quotes and backslashes
            escaped = value.replace('\\', '\\\\').replace("'", "\\'")
            prop_parts.append(f"{key}: '{escaped}'")
        elif isinstance(value, (int, float)):
            prop_parts.append(f"{key}: {value}")
        elif isinstance(value, bool):
            prop_parts.append(f"{key}: {str(value).lower()}")

    props_str = ", ".join(prop_parts)

    # Create Cypher query
    query = f"CREATE (n:{node_type} {{{props_str}}}) RETURN id(n) as node_id, n.name as name"

    print(f"\nInserting {node_type} node: {properties.get('name', 'unnamed')}...")
    print(f"Query: {query[:100]}...")

    # Execute via CLI using --config-file and --cypher options
    result = subprocess.run(
        ['project-analyzer', '--config-file', mcp_config, 'query', '--cypher', query],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode == 0:
        print(f"✅ Success: {result.stdout.strip()}")
        return True
    else:
        print(f"❌ Failed: {result.stderr}")
        return False


def create_relationship(from_type, from_prop, rel_type, to_type, to_prop, mcp_config):
    """Create a relationship between two nodes."""
    query = f"""MATCH (from:{from_type} {{{from_prop}}}) MATCH (to:{to_type} {{{to_prop}}}) CREATE (from)-[r:{rel_type}]->(to) RETURN type(r) as rel_type"""

    result = subprocess.run(
        ['project-analyzer', '--config-file', mcp_config, 'query', '--cypher', query],
        capture_output=True,
        text=True,
        timeout=30
    )

    if result.returncode == 0:
        print(f"   ✅ Created {rel_type} relationship")
        return True
    else:
        print(f"   ❌ Failed to create relationship: {result.stderr}")
        return False


def main():
    mcp_config = "/opt/genpod/neo4j_config.json"

    print("="*80)
    print("INSERTING TEST NODES WITH COMPLEX PROPERTIES")
    print("="*80)

    # Test Node 1: File with imports and import_aliases
    file_node = {
        "name": "TestFile.cs",
        "file_path": "/opt/genpod/TestFile.cs",
        "file_checksum": "test123",
        "imports": json.dumps(["System", "System.Collections.Generic", "System.Linq"]),
        "import_aliases": json.dumps({"Collections": "System.Collections.Generic", "IO": "System.IO"})
    }

    print("\n" + "-"*80)
    print("Node 1: File with imports (list) and import_aliases (dict)")
    print("-"*80)
    print(f"imports (Python list): ['System', 'System.Collections.Generic', 'System.Linq']")
    print(f"imports (JSON string): {file_node['imports']}")
    print(f"import_aliases (Python dict): {{'Collections': 'System.Collections.Generic', 'IO': 'System.IO'}}")
    print(f"import_aliases (JSON string): {file_node['import_aliases']}")

    insert_node_via_cli("File", file_node, mcp_config)

    # Test Node 2: Type with base_list
    type_node = {
        "name": "MyTestClass",
        "type_kind": "class",
        "file_path": "/opt/genpod/TestFile.cs",
        "modifier": "public",
        "base_list": json.dumps(["BaseClass", "IInterface1", "IInterface2"])
    }

    print("\n" + "-"*80)
    print("Node 2: Type with base_list (list)")
    print("-"*80)
    print(f"base_list (Python list): ['BaseClass', 'IInterface1', 'IInterface2']")
    print(f"base_list (JSON string): {type_node['base_list']}")

    insert_node_via_cli("Type", type_node, mcp_config)

    # Create CONTAINS relationship: File -> Type
    print("\nCreating CONTAINS relationship: File -> MyTestClass")
    create_relationship(
        "File", "name: 'TestFile.cs'",
        "CONTAINS",
        "Type", "name: 'MyTestClass'",
        mcp_config
    )

    # Test Node 3: Type with symbols_location (nested structure)
    symbols_loc = {
        "symbols": [
            {"text": "MyTestClass", "start_byte": 100, "end_byte": 111, "start_point": [5, 6], "end_point": [5, 17]},
            {"text": "BaseClass", "start_byte": 113, "end_byte": 122, "start_point": [5, 19], "end_point": [5, 28]}
        ]
    }

    type_node2 = {
        "name": "AnotherTestClass",
        "type_kind": "class",
        "file_path": "/opt/genpod/TestFile.cs",
        "modifier": "public",
        "symbols_location": json.dumps(symbols_loc)
    }

    print("\n" + "-"*80)
    print("Node 3: Type with symbols_location (nested dict with list of dicts)")
    print("-"*80)
    print(f"symbols_location (Python): {symbols_loc}")
    print(f"symbols_location (JSON string): {type_node2['symbols_location']}")

    insert_node_via_cli("Type", type_node2, mcp_config)

    # Create CONTAINS relationship: File -> Type
    print("\nCreating CONTAINS relationship: File -> AnotherTestClass")
    create_relationship(
        "File", "name: 'TestFile.cs'",
        "CONTAINS",
        "Type", "name: 'AnotherTestClass'",
        mcp_config
    )

    # Test Node 4: Variable with List[Dict] structure
    field_metadata = [
        {"annotation": "NotNull", "value": True},
        {"annotation": "MaxLength", "value": 255},
        {"annotation": "DefaultValue", "value": "test"}
    ]

    var_node = {
        "name": "_testField",
        "type_kind": "field",
        "variable_type": "string",
        "file_path": "/opt/genpod/TestFile.cs",
        "metadata": json.dumps(field_metadata)
    }

    print("\n" + "-"*80)
    print("Node 4: Variable with metadata (List[Dict])")
    print("-"*80)
    print(f"metadata (Python): {field_metadata}")
    print(f"metadata (JSON string): {var_node['metadata']}")

    insert_node_via_cli("Variable", var_node, mcp_config)

    # Create CONTAINS relationship: Type -> Variable
    print("\nCreating CONTAINS relationship: MyTestClass -> _testField")
    create_relationship(
        "Type", "name: 'MyTestClass'",
        "CONTAINS",
        "Variable", "name: '_testField'",
        mcp_config
    )

    print("\n" + "="*80)
    print("INSERTION COMPLETE")
    print("="*80)

    print("\n📊 Now query the database to see how they're stored:")
    print("\n# Query 1: File node with complex properties")
    print("project-analyzer query --mcp-config /opt/genpod/neo4j_config.json \\")
    print('  "MATCH (f:File {name: \'TestFile.cs\'}) RETURN f.name, f.imports, f.import_aliases"')

    print("\n# Query 2: Type nodes with base_list")
    print("project-analyzer query --mcp-config /opt/genpod/neo4j_config.json \\")
    print('  "MATCH (t:Type {name: \'MyTestClass\'}) RETURN t.name, t.base_list"')

    print("\n# Query 3: Type with nested symbols_location")
    print("project-analyzer query --mcp-config /opt/genpod/neo4j_config.json \\")
    print('  "MATCH (t:Type {name: \'AnotherTestClass\'}) RETURN t.name, t.symbols_location"')

    print("\n# Query 4: Variable with List[Dict] metadata")
    print("project-analyzer query --mcp-config /opt/genpod/neo4j_config.json \\")
    print('  "MATCH (v:Variable {name: \'_testField\'}) RETURN v.name, v.metadata"')

    print("\n🗑️  To delete test nodes later (via CONTAINS relationship):")
    print("project-analyzer query --mcp-config /opt/genpod/neo4j_config.json \\")
    print('  "MATCH (f:File {name: \'TestFile.cs\'})-[r:CONTAINS*0..]->(n) DETACH DELETE f, n"')


if __name__ == "__main__":
    main()
