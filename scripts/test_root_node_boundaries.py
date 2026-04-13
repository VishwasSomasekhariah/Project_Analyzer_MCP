#!/usr/bin/env python3
"""
Test script to verify tree-sitter root node boundaries are accurate.
"""

import tree_sitter
import os
import sys

def get_parser_path(parser_name):
    """Get the path to tree-sitter parser."""
    base_path = "/opt/genpod/project_analyzer_cli/project_analyzer/assets/tree_sitter_grammars_linux"
    return os.path.join(base_path, parser_name, "parser.so")

def test_root_node_boundaries():
    """Test tree-sitter root node boundaries against actual file content."""

    # Test files
    test_files = [
        "/opt/HelloWorldApp/HelloWorldApp/Manager.cs",
        "/opt/HelloWorldApp/HelloWorldApp/TestAliases.cs",
        "/opt/HelloWorldApp/HelloWorldApp/Program.cs",
        "/opt/HelloWorldApp/HelloWorldApp/INotifier.cs"
    ]

    # Setup C# parser
    parser = tree_sitter.Parser()
    try:
        language = tree_sitter.Language(get_parser_path("tree_sitter_c_sharp"), "c_sharp")
        parser.set_language(language)
    except Exception as e:
        print(f"Failed to load C# parser: {e}")
        return

    print("Testing tree-sitter root node boundaries vs actual file content:")
    print("=" * 80)

    for file_path in test_files:
        if not os.path.exists(file_path):
            print(f"⚠️  File not found: {file_path}")
            continue

        print(f"\n📁 Testing: {os.path.basename(file_path)}")
        print("-" * 40)

        # Read file content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"❌ Failed to read file: {e}")
            continue

        # Get actual file stats
        actual_byte_size = len(content.encode('utf-8'))
        actual_lines = content.split('\n')
        actual_line_count = len(actual_lines)
        actual_last_line_length = len(actual_lines[-1]) if actual_lines else 0

        print(f"📊 Actual file stats:")
        print(f"   • Byte size: {actual_byte_size}")
        print(f"   • Line count: {actual_line_count}")
        print(f"   • Last line length: {actual_last_line_length}")
        print(f"   • Expected end_point: ({actual_line_count - 1}, {actual_last_line_length})")

        # Parse with tree-sitter
        try:
            tree = parser.parse(bytes(content, "utf8"))
            root_node = tree.root_node
        except Exception as e:
            print(f"❌ Failed to parse with tree-sitter: {e}")
            continue

        # Get root node boundaries
        root_start_point = root_node.start_point
        root_end_point = root_node.end_point
        root_start_byte = root_node.start_byte
        root_end_byte = root_node.end_byte

        print(f"🌳 Tree-sitter root node:")
        print(f"   • start_point: {root_start_point}")
        print(f"   • end_point: {root_end_point}")
        print(f"   • start_byte: {root_start_byte}")
        print(f"   • end_byte: {root_end_byte}")

        # Compare and validate
        print(f"✅ Validation:")

        # Check start points (should be (0,0) and 0)
        start_point_ok = root_start_point == (0, 0)
        start_byte_ok = root_start_byte == 0
        print(f"   • Start point: {'✅ CORRECT' if start_point_ok else '❌ WRONG'} ({root_start_point})")
        print(f"   • Start byte: {'✅ CORRECT' if start_byte_ok else '❌ WRONG'} ({root_start_byte})")

        # Check end points
        expected_end_point = (actual_line_count - 1, actual_last_line_length)
        end_point_ok = root_end_point == expected_end_point

        # Byte count (may have small differences due to encoding/line endings)
        byte_diff = abs(root_end_byte - actual_byte_size)
        byte_ok = byte_diff <= 5  # Allow small difference for line endings

        print(f"   • End point: {'✅ CORRECT' if end_point_ok else '❌ WRONG'}")
        print(f"     Expected: {expected_end_point}, Got: {root_end_point}")
        print(f"   • End byte: {'✅ CLOSE' if byte_ok else '❌ WRONG'}")
        print(f"     Expected: {actual_byte_size}, Got: {root_end_byte}, Diff: {byte_diff}")

        # Overall assessment
        overall_ok = start_point_ok and start_byte_ok and end_point_ok and byte_ok
        status = "✅ PASSED" if overall_ok else "❌ FAILED"
        print(f"   • Overall: {status}")

        # Debug info for failures
        if not overall_ok:
            print(f"🔍 Debug info:")
            print(f"   • File content preview (first 100 chars): {repr(content[:100])}")
            print(f"   • File content preview (last 100 chars): {repr(content[-100:])}")
            print(f"   • Root node type: {root_node.type}")
            print(f"   • Root node text preview: {repr(root_node.text[:100].decode('utf-8', errors='ignore'))}")

if __name__ == "__main__":
    test_root_node_boundaries()