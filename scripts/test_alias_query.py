#!/usr/bin/env python3
"""
Test the alias query to understand what captures we're getting
"""

import tree_sitter
import os

def test_alias_query():
    # Load the C# parser
    parser_path = "/opt/genpod/project_analyzer_cli/project_analyzer/assets/tree_sitter_grammars_linux/tree_sitter_c_sharp/parser.so"
    language = tree_sitter.Language(parser_path, "c_sharp")
    parser = tree_sitter.Parser()
    parser.set_language(language)

    # Read TestAliases.cs
    with open("/opt/HelloWorldApp/HelloWorldApp/TestAliases.cs", 'r') as f:
        source_code = f.read()

    # Parse the source code
    tree = parser.parse(bytes(source_code, 'utf-8'))

    # Test our using query
    using_query = """
    (using_directive
      (identifier)* @using.alias
      (qualified_name)* @using.name
      (identifier)* @using.name) @using.definition
    """

    # Execute the query
    query = language.query(using_query)
    captures = query.captures(tree.root_node)

    print(f"Query found {len(captures)} captures:")
    for node, capture_name in captures:
        text = source_code[node.start_byte:node.end_byte]
        print(f"  {capture_name}: '{text}' at {node.start_point}")

    print(f"\nFull source code:")
    print(source_code)

if __name__ == "__main__":
    test_alias_query()