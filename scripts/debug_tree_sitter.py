#!/usr/bin/env python3
"""
Debug script to test tree-sitter parsing on WorkerA.cs
"""

import tree_sitter
import os

def test_tree_sitter_parsing():
    # Load the C# parser
    parser_path = "/opt/genpod/project_analyzer_cli/project_analyzer/assets/tree_sitter_grammars_linux/tree_sitter_c_sharp/parser.so"

    if not os.path.exists(parser_path):
        print(f"Parser not found at: {parser_path}")
        return

    # Initialize parser
    try:
        language = tree_sitter.Language(parser_path, "c_sharp")
        parser = tree_sitter.Parser()
        parser.set_language(language)
        print("✓ C# parser loaded successfully")
    except Exception as e:
        print(f"✗ Failed to load parser: {e}")
        return

    # Read WorkerA.cs
    file_path = "/opt/HelloWorldApp/HelloWorldApp/WorkerA.cs"
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source_code = f.read()
        print(f"✓ Read source file: {file_path}")
        print(f"Source content:\n{source_code}")
        print("-" * 50)
    except Exception as e:
        print(f"✗ Failed to read file: {e}")
        return

    # Parse the source code
    try:
        tree = parser.parse(bytes(source_code, 'utf-8'))
        root_node = tree.root_node
        print(f"✓ Parsed successfully, root node type: {root_node.type}")
    except Exception as e:
        print(f"✗ Failed to parse: {e}")
        return

    # Recursively traverse and find all nodes
    def traverse_node(node, depth=0):
        indent = "  " * depth
        print(f"{indent}{node.type} [{node.start_point}:{node.end_point}]")

        # Look specifically for field_declaration
        if node.type == 'field_declaration':
            print(f"{indent}  >>> FOUND FIELD_DECLARATION!")
            print(f"{indent}  >>> Text: {source_code[node.start_byte:node.end_byte]}")

            # Look at child nodes
            for child in node.children:
                print(f"{indent}    Child: {child.type} = {source_code[child.start_byte:child.end_byte]}")

        # Recurse through children
        for child in node.children:
            traverse_node(child, depth + 1)

    print("\nFull AST traversal:")
    print("=" * 60)
    traverse_node(root_node)

    # Specifically search for field-related nodes
    print("\n" + "=" * 60)
    print("SEARCHING FOR FIELD-RELATED NODES:")
    print("=" * 60)

    def find_nodes_by_type(node, target_types):
        results = []
        if node.type in target_types:
            results.append(node)
        for child in node.children:
            results.extend(find_nodes_by_type(child, target_types))
        return results

    # Search for various node types
    field_types = ['field_declaration', 'variable_declarator', 'variable_declaration']
    found_nodes = find_nodes_by_type(root_node, field_types)

    if found_nodes:
        for node in found_nodes:
            print(f"Found {node.type}: {source_code[node.start_byte:node.end_byte]}")
    else:
        print("No field-related nodes found!")

    # Let's also check what actual node types exist in the class
    print("\n" + "=" * 60)
    print("ALL NODE TYPES IN THE FILE:")
    print("=" * 60)

    def collect_all_node_types(node):
        types = {node.type}
        for child in node.children:
            types.update(collect_all_node_types(child))
        return types

    all_types = collect_all_node_types(root_node)
    for node_type in sorted(all_types):
        print(f"  - {node_type}")

if __name__ == "__main__":
    test_tree_sitter_parsing()