#!/usr/bin/env python3
"""
Test the corrected field_declaration query
"""

import tree_sitter
import os

def test_field_query():
    # Load the C# parser
    parser_path = "/opt/genpod/project_analyzer_cli/project_analyzer/assets/tree_sitter_grammars_linux/tree_sitter_c_sharp/parser.so"
    language = tree_sitter.Language(parser_path, "c_sharp")
    parser = tree_sitter.Parser()
    parser.set_language(language)

    # Read WorkerA.cs
    with open("/opt/HelloWorldApp/HelloWorldApp/WorkerA.cs", 'r') as f:
        source_code = f.read()

    # Parse the source code
    tree = parser.parse(bytes(source_code, 'utf-8'))

    # Test our corrected field query (simplified)
    field_query = """
    (field_declaration
      (variable_declaration
        (identifier) @field.type
        (variable_declarator
          (identifier) @field.name))
      (modifier)* @field.modifier) @field.definition
    """

    # Execute the query
    query = language.query(field_query)
    captures = query.captures(tree.root_node)

    print(f"Query found {len(captures)} captures:")
    for node, capture_name in captures:
        text = source_code[node.start_byte:node.end_byte]
        print(f"  {capture_name}: '{text}' at {node.start_point}")

    if captures:
        print("\n✓ Field query is working!")
        return True
    else:
        print("\n✗ Field query found no matches")
        return False

if __name__ == "__main__":
    test_field_query()