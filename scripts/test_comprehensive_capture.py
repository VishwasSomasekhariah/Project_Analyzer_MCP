#!/usr/bin/env python3
"""
Comprehensive test of ALL tree-sitter queries on a complete C# test file.
Tests both existing queries and new literal/block queries.
"""

import sys
import os
import json
from collections import defaultdict

sys.path.append('/opt/genpod/project_analyzer_cli')

from tree_sitter import Language, Parser
from project_analyzer.utils.path_utils import get_parser_path


# ============================================================================
# FIXED QUERIES - Enhanced to capture missing constructs
# ============================================================================

EXISTING_QUERIES = """
(using_directive
  (identifier)* @using.alias
  (qualified_name)* @using.name
  (identifier)* @using.name) @using.definition

(class_declaration
  name: (identifier) @class.name
  body: (declaration_list) @class.body
  (attribute_list)? @class.attribute
  (modifier)* @class.modifier
  (base_list)? @class.base
  (type_parameter_list)? @class.type_parameters
  (parameter_list)? @class.parameters
  (type_parameter_constraints_clause)* @class.constraints) @class.definition

(constructor_declaration
  name: (identifier) @constructor.name
  parameters: (parameter_list) @constructor.parameters
  (attribute_list)? @constructor.attribute
  (modifier)* @constructor.modifier
  (constructor_initializer)? @constructor.initializer
  body: (block) @constructor.body) @constructor.definition

; Methods with block body
(method_declaration
  name: (identifier) @method.name
  parameters: (parameter_list) @method.parameters
  (attribute_list)? @method.attribute
  (modifier)* @method.modifier
  (type_parameter_list)? @method.type_parameters
  (type_parameter_constraints_clause)* @method.constraints
  body: (block) @method.body) @method.definition

; FIXED: Expression-bodied methods
(method_declaration
  name: (identifier) @method.name
  parameters: (parameter_list) @method.parameters
  (attribute_list)? @method.attribute
  (modifier)* @method.modifier
  (type_parameter_list)? @method.type_parameters
  (type_parameter_constraints_clause)* @method.constraints
  body: (arrow_expression_clause) @method.arrow_body) @method.definition.expression_bodied

; ADDED: Local functions (C# 7+)
(local_function_statement
  name: (identifier) @local_function.name
  parameters: (parameter_list) @local_function.parameters
  (modifier)* @local_function.modifier
  body: (block) @local_function.body) @local_function.definition

(namespace_declaration
  name: (qualified_name) @namespace.name
  body: (declaration_list) @namespace.body
  (attribute_list)? @namespace.attribute) @namespace.definition

(file_scoped_namespace_declaration
    name: (qualified_name) @namespace.name
    (attribute_list)? @namespace.attribute) @file_scoped_namespace.definition

(interface_declaration
  name: (identifier) @interface.name
  body: (declaration_list) @interface.body
  (attribute_list)? @interface.attribute
  (modifier)* @interface.modifier
  (type_parameter_list)? @interface.type_parameters
  (type_parameter_constraints_clause)* @interface.constraints) @interface.definition

(enum_declaration
  name: (identifier) @enum.name
  body: (enum_member_declaration_list) @enum.body
  (attribute_list)? @enum.attribute
  (modifier)* @enum.modifier
  (base_list)? @enum.base) @enum.definition

(delegate_declaration
  type: (type) @delegate.return_type
  name: (identifier) @delegate.name
  parameters: (parameter_list) @delegate.parameters
  (attribute_list)? @delegate.attribute
  (modifier)* @delegate.modifier
  (type_parameter_list)? @delegate.type_parameters
  (type_parameter_constraints_clause)* @delegate.constraints) @delegate.definition

(struct_declaration
  name: (identifier) @struct.name
  body: (declaration_list) @struct.body
  (attribute_list)? @struct.attribute
  (modifier)* @struct.modifier
  (base_list)? @struct.base
  (type_parameter_list)? @struct.type_parameters
  (type_parameter_constraints_clause)* @struct.constraints) @struct.definition

; ADDED: Records (C# 9+)
(record_declaration
  name: (identifier) @record.name
  (parameter_list)? @record.parameters
  body: (declaration_list)? @record.body
  (attribute_list)? @record.attribute
  (modifier)* @record.modifier
  (base_list)? @record.base) @record.definition

(event_declaration
  type: (type) @event.type
  name: (identifier) @event.name
  (attribute_list)? @event.attribute
  (modifier)* @event.modifier
  (explicit_interface_specifier)? @event.explicit_interface
  (accessor_list)? @event.accessors) @event.definition

(property_declaration
  type: (type) @property.type
  name: (identifier) @property.name
  (attribute_list)? @property.attribute
  (modifier)* @property.modifier
  (explicit_interface_specifier)? @property.explicit_interface
  (accessor_list)? @property.accessors
  (arrow_expression_clause)? @property.arrow_clause
  (expression)? @property.value) @property.definition

; FIXED: Field declarations - accept any type node, capture initializer
(field_declaration
  (variable_declaration
    type: (_) @field.type
    (variable_declarator
      (identifier) @field.name
      (_)? @field.initializer))
  (modifier)* @field.modifier
  (attribute_list)? @field.attribute) @field.definition

; FIXED: Local variables - capture initializer
(local_declaration_statement
  (variable_declaration
    (variable_declarator
      (identifier) @local_variable.name
      (_)? @local_variable.initializer))
  (modifier)* @local_variable.modifier) @local_variable.definition

(parameter
  type: (type) @parameter.type
  name: (identifier) @parameter.name) @parameter.definition

; ADDED: Switch expressions (C# 8+)
(switch_expression) @expression.switch
"""


# ============================================================================
# NEW LITERAL QUERIES
# ============================================================================

LITERAL_QUERY = """
; String literals
(string_literal) @literal.string

; Interpolated strings
(interpolated_string_expression) @literal.string.interpolated

; Verbatim strings
(verbatim_string_literal) @literal.string.verbatim

; Integer literals
(integer_literal) @literal.number.integer

; Real/float literals
(real_literal) @literal.number.real

; Boolean literals
(boolean_literal) @literal.boolean

; Null literal
(null_literal) @literal.null

; Character literals
(character_literal) @literal.character

; Comments
(comment) @literal.comment
"""


# ============================================================================
# NEW BLOCK QUERIES
# ============================================================================

BLOCK_QUERY = """
; Method body blocks
(method_declaration
  body: (block) @block.method)

; Constructor body blocks
(constructor_declaration
  body: (block) @block.constructor)

; Property accessor blocks (get/set)
(accessor_declaration
  body: (block) @block.accessor)

; If statement blocks
(if_statement
  (block) @block.if)

; For loop blocks
(for_statement
  (block) @block.for)

; Foreach loop blocks
(foreach_statement
  (block) @block.foreach)

; While loop blocks
(while_statement
  (block) @block.while)

; Do-while loop blocks
(do_statement
  (block) @block.do)

; Try block
(try_statement
  (block) @block.try)

; Catch block
(catch_clause
  (block) @block.catch)

; Finally block
(finally_clause
  (block) @block.finally)

; Lambda expression blocks
(lambda_expression
  (block) @block.lambda)

; Using statement blocks
(using_statement
  (block) @block.using)

; Lock statement blocks
(lock_statement
  (block) @block.lock)

; Switch statement (has block structure)
(switch_statement
  (switch_body) @block.switch)
"""


# ============================================================================
# NEW STATEMENT QUERIES
# ============================================================================

STATEMENT_QUERY = """
; Expression statements (method calls, assignments, etc.)
(expression_statement) @statement.expression

; Local variable declarations
(local_declaration_statement) @statement.declaration

; Return statements
(return_statement) @statement.return

; Throw statements
(throw_statement) @statement.throw

; If statements
(if_statement) @statement.if

; For loop statements
(for_statement) @statement.for

; Foreach loop statements
(foreach_statement) @statement.foreach

; While loop statements
(while_statement) @statement.while

; Do-while loop statements
(do_statement) @statement.do

; Switch statements
(switch_statement) @statement.switch

; Try statements
(try_statement) @statement.try

; Break statements
(break_statement) @statement.break

; Continue statements
(continue_statement) @statement.continue

; Yield return statements
(yield_statement) @statement.yield

; Lock statements
(lock_statement) @statement.lock

; Using statements
(using_statement) @statement.using

; Checked statements
(checked_statement) @statement.checked

; Fixed statements (unsafe code)
(fixed_statement) @statement.fixed

; Goto statements
(goto_statement) @statement.goto

; Labeled statements
(labeled_statement) @statement.labeled

; Empty statements
(empty_statement) @statement.empty
"""


def init_parser():
    """Initialize C# parser."""
    parser_path = get_parser_path("tree_sitter_c_sharp")
    CS_LANGUAGE = Language(parser_path, "c_sharp")
    parser = Parser()
    parser.set_language(CS_LANGUAGE)
    return parser, CS_LANGUAGE


def read_file(filepath):
    """Read file content as bytes."""
    with open(filepath, 'rb') as f:
        return f.read()


def run_query(parser, language, source_code, query_string, query_name):
    """Run a tree-sitter query and collect captures."""
    tree = parser.parse(source_code)
    query = language.query(query_string)
    captures = query.captures(tree.root_node)

    capture_stats = defaultdict(int)
    capture_examples = defaultdict(list)

    for node, capture_name in captures:
        capture_stats[capture_name] += 1

        # Keep first 3 examples of each capture type
        if len(capture_examples[capture_name]) < 3:
            text = source_code[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
            # Truncate long text
            display_text = text[:80] + '...' if len(text) > 80 else text
            capture_examples[capture_name].append({
                'line': node.start_point[0] + 1,
                'text': display_text,
                'node_type': node.type
            })

    return {
        'query_name': query_name,
        'total_captures': len(captures),
        'capture_counts': dict(capture_stats),
        'examples': dict(capture_examples)
    }


def main():
    """Test comprehensive C# file with all queries."""
    import sys

    # Allow command-line argument for different test files
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        filepath = "/opt/genpod/ComprehensiveTestFile.cs"

    if not os.path.exists(filepath):
        print(f"ERROR: Test file not found: {filepath}")
        return

    print("=" * 100)
    print("COMPREHENSIVE C# TREE-SITTER QUERY TEST")
    print("=" * 100)
    print(f"\nTest File: {filepath}")

    # Count lines in file
    with open(filepath, 'r') as f:
        lines = f.readlines()
    print(f"Total Lines: {len(lines)}")

    parser, language = init_parser()
    source = read_file(filepath)

    print("\n" + "=" * 100)
    print("RUNNING ALL QUERIES")
    print("=" * 100)

    # Run all query sets
    results = {}

    print("\n[1/4] Running EXISTING queries (nodes, types, declarations)...")
    results['existing'] = run_query(parser, language, source, EXISTING_QUERIES, 'Existing Queries')

    print("[2/4] Running NEW LITERAL queries...")
    results['literals'] = run_query(parser, language, source, LITERAL_QUERY, 'Literal Queries')

    print("[3/4] Running NEW BLOCK queries...")
    results['blocks'] = run_query(parser, language, source, BLOCK_QUERY, 'Block Queries')

    print("[4/4] Running NEW STATEMENT queries...")
    results['statements'] = run_query(parser, language, source, STATEMENT_QUERY, 'Statement Queries')

    # Print detailed results
    print("\n" + "=" * 100)
    print("DETAILED RESULTS")
    print("=" * 100)

    for category, result in results.items():
        print(f"\n{'─' * 100}")
        print(f"CATEGORY: {result['query_name']}")
        print(f"{'─' * 100}")
        print(f"Total Captures: {result['total_captures']}")
        print(f"\nCapture Breakdown ({len(result['capture_counts'])} unique capture types):")

        # Sort by count descending
        sorted_captures = sorted(result['capture_counts'].items(), key=lambda x: x[1], reverse=True)

        for capture_name, count in sorted_captures:
            print(f"\n  {capture_name}: {count} captures")

            # Show examples
            if capture_name in result['examples']:
                for idx, example in enumerate(result['examples'][capture_name], 1):
                    print(f"    Example {idx} (Line {example['line']}, {example['node_type']}): {example['text']!r}")

    # Overall summary
    print("\n" + "=" * 100)
    print("OVERALL SUMMARY")
    print("=" * 100)

    total_captures = sum(r['total_captures'] for r in results.values())
    print(f"\nTotal Captures Across All Queries: {total_captures}")

    print("\nBreakdown by Category:")
    print(f"  Existing Queries:  {results['existing']['total_captures']:5d} captures ({len(results['existing']['capture_counts'])} types)")
    print(f"  Literal Queries:   {results['literals']['total_captures']:5d} captures ({len(results['literals']['capture_counts'])} types)")
    print(f"  Block Queries:     {results['blocks']['total_captures']:5d} captures ({len(results['blocks']['capture_counts'])} types)")
    print(f"  Statement Queries: {results['statements']['total_captures']:5d} captures ({len(results['statements']['capture_counts'])} types)")

    # Check for potential missing captures
    print("\n" + "=" * 100)
    print("COVERAGE ANALYSIS")
    print("=" * 100)

    # Expected constructs in the test file
    expected_constructs = {
        'Literals': {
            'literal.string': 'Regular strings',
            'literal.string.interpolated': 'Interpolated strings ($"...")',
            'literal.string.verbatim': 'Verbatim strings (@"...")',
            'literal.number.integer': 'Integer literals',
            'literal.number.real': 'Float/double literals',
            'literal.boolean': 'true/false',
            'literal.null': 'null',
            'literal.character': 'Character literals',
            'literal.comment': 'Comments'
        },
        'Blocks': {
            'block.method': 'Method bodies',
            'block.constructor': 'Constructor bodies',
            'block.accessor': 'Property get/set',
            'block.if': 'If statement blocks',
            'block.else': 'Else blocks',
            'block.for': 'For loop blocks',
            'block.foreach': 'Foreach loop blocks',
            'block.while': 'While loop blocks',
            'block.do': 'Do-while blocks',
            'block.try': 'Try blocks',
            'block.catch': 'Catch blocks',
            'block.finally': 'Finally blocks',
            'block.lambda': 'Lambda blocks',
            'block.using': 'Using statement blocks',
            'block.lock': 'Lock blocks',
            'block.switch': 'Switch blocks'
        },
        'Types': {
            'class.definition': 'Classes',
            'interface.definition': 'Interfaces',
            'struct.definition': 'Structs',
            'enum.definition': 'Enums',
            'delegate.definition': 'Delegates'
        },
        'Members': {
            'method.definition': 'Methods',
            'constructor.definition': 'Constructors',
            'property.definition': 'Properties',
            'field.definition': 'Fields',
            'event.definition': 'Events'
        }
    }

    all_captures = {}
    for result in results.values():
        all_captures.update(result['capture_counts'])

    print("\n✅ CAPTURED (constructs found in test file):")
    print("─" * 100)

    for category, constructs in expected_constructs.items():
        print(f"\n{category}:")
        captured_in_category = []
        for capture_name, description in constructs.items():
            if capture_name in all_captures:
                count = all_captures[capture_name]
                captured_in_category.append(f"  ✅ {description:40s} ({capture_name:30s}): {count:3d} found")

        if captured_in_category:
            for line in captured_in_category:
                print(line)

    print("\n⚠️  EXPECTED BUT NOT CAPTURED:")
    print("─" * 100)

    missing = []
    for category, constructs in expected_constructs.items():
        for capture_name, description in constructs.items():
            if capture_name not in all_captures:
                missing.append(f"  ❌ {description:40s} ({capture_name})")

    if missing:
        for line in missing:
            print(line)
    else:
        print("  None! All expected constructs were captured. ✅")

    # Save detailed JSON report
    output_file = '/opt/genpod/comprehensive_test_output.json'
    with open(output_file, 'w') as f:
        json.dump({
            'test_file': filepath,
            'total_lines': len(lines),
            'results': results,
            'summary': {
                'total_captures': total_captures,
                'by_category': {
                    'existing': results['existing']['total_captures'],
                    'literals': results['literals']['total_captures'],
                    'blocks': results['blocks']['total_captures']
                }
            }
        }, f, indent=2)

    print(f"\n\nDetailed JSON report saved to: {output_file}")

    print("\n" + "=" * 100)
    print("TEST COMPLETE")
    print("=" * 100)


if __name__ == "__main__":
    main()
