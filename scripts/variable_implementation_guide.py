#!/usr/bin/env python3
"""
Variable Implementation Guide: What C# queries to add and how to process captured nodes

SUMMARY:
- We only capture 3 variables (fields) but miss local variables and parameters
- Need to add 2 new tree-sitter queries to c-sharp-queries.scm
- Need to add 2 new mappings to universal_mapping_schema.yaml
- This will capture 7 additional variables from HelloWorldApp (233% increase)

TESTED RESULTS:
- Local Variables: manager, workers, msg (3 total)
- Parameters: args, message, notifier, notifier (4 total)
- Current: 3 field variables only
- After implementation: 10 total variables
"""

import sys
import os
sys.path.append('/opt/genpod/project_analyzer_cli')

from tree_sitter import Language, Parser
from project_analyzer.utils.path_utils import get_parser_path

# =============================================================================
# 1. NEW TREE-SITTER QUERIES TO ADD TO c-sharp-queries.scm
# =============================================================================

NEW_CSHARP_QUERIES = '''
# Add these queries to /opt/genpod/project_analyzer_cli/project_analyzer/final_queries/c-sharp-queries.scm

(local_declaration_statement
  (variable_declaration
    (variable_declarator
      (identifier) @local_variable.name))
  (modifier)* @local_variable.modifier) @local_variable.definition

(parameter
  type: (type) @parameter.type
  name: (identifier) @parameter.name) @parameter.definition
'''

# =============================================================================
# 2. NEW MAPPINGS TO ADD TO universal_mapping_schema.yaml
# =============================================================================

NEW_UNIVERSAL_MAPPINGS = '''
# Add these mappings to C# section in universal_mapping_schema.yaml

# Local variable captures
local_variable.definition: Variable
local_variable.name: Variable.attribute
local_variable.modifier: Variable.attribute

# Parameter captures
parameter.definition: Variable
parameter.name: Variable.attribute
parameter.type: Variable.attribute
'''

# =============================================================================
# 3. PROPERTY EXTRACTION LOGIC
# =============================================================================

def extract_variable_properties(capture_group, file_path, variable_type):
    """
    Extract Variable node properties from tree-sitter captures

    Args:
        capture_group: Dictionary of captures grouped by definition node
        file_path: Path to the source file
        variable_type: 'local_variable' or 'parameter'

    Returns:
        Dictionary of Variable node properties
    """

    properties = {}

    # ALWAYS EXTRACTABLE PROPERTIES
    definition_node = capture_group['definition']
    properties['start_byte'] = definition_node.start_byte
    properties['end_byte'] = definition_node.end_byte
    properties['file_path'] = file_path
    properties['type_kind'] = variable_type

    # NAME (always present)
    if f'{variable_type}.name' in capture_group:
        properties['name'] = capture_group[f'{variable_type}.name'][0].text.decode('utf8')

    # TYPE (for parameters, optional for local vars)
    if f'{variable_type}.type' in capture_group:
        properties['type'] = capture_group[f'{variable_type}.type'][0].text.decode('utf8')

    # MODIFIER (if present)
    if f'{variable_type}.modifier' in capture_group and capture_group[f'{variable_type}.modifier']:
        properties['modifier'] = [m.text.decode('utf8') for m in capture_group[f'{variable_type}.modifier']]
    else:
        properties['modifier'] = []

    # PROPERTIES SET TO NONE/EMPTY (not applicable to local vars/params)
    properties['alias'] = None
    properties['access_modifier'] = None
    properties['explicit_interface'] = None
    properties['accessors'] = None
    properties['arrow_clause'] = None
    properties['value'] = None  # Use initial_value instead
    properties['attribute'] = None
    properties['initial_value'] = None  # Could be enhanced later
    properties['symbols_location'] = None  # LSP-enriched later

    return properties

# =============================================================================
# 4. VALIDATION TEST
# =============================================================================

def validate_implementation():
    """Validate the new queries work on real HelloWorldApp files"""

    # Load C# parser
    parser_path = get_parser_path("tree_sitter_c_sharp")
    language = Language(parser_path, "c_sharp")
    parser = Parser()
    parser.set_language(language)

    # Test queries
    local_var_query = language.query("""
        (local_declaration_statement
          (variable_declaration
            (variable_declarator
              (identifier) @local_variable.name))
          (modifier)* @local_variable.modifier) @local_variable.definition
    """)

    parameter_query = language.query("""
        (parameter
          type: (type) @parameter.type
          name: (identifier) @parameter.name) @parameter.definition
    """)

    # Test files
    test_files = [
        "/opt/HelloWorldApp/HelloWorldApp/Program.cs",
        "/opt/HelloWorldApp/HelloWorldApp/Manager.cs",
        "/opt/HelloWorldApp/HelloWorldApp/WorkerA.cs",
        "/opt/HelloWorldApp/HelloWorldApp/WorkerFactory.cs"
    ]

    print("🧪 Variable Implementation Validation")
    print("=" * 50)

    total_local_vars = 0
    total_parameters = 0

    for file_path in test_files:
        if not os.path.exists(file_path):
            continue

        with open(file_path, 'r') as f:
            code = f.read()

        tree = parser.parse(bytes(code, 'utf8'))

        # Local variables
        local_captures = local_var_query.captures(tree.root_node)
        local_vars = [c[0].text.decode('utf8') for c in local_captures if c[1].endswith('.name')]

        # Parameters
        param_captures = parameter_query.captures(tree.root_node)
        parameters = [c[0].text.decode('utf8') for c in param_captures if c[1].endswith('.name')]

        if local_vars or parameters:
            print(f"\n📁 {os.path.basename(file_path)}")
            if local_vars:
                print(f"  ✅ Local Variables: {local_vars}")
                total_local_vars += len(local_vars)
            if parameters:
                print(f"  ✅ Parameters: {parameters}")
                total_parameters += len(parameters)

    print(f"\n🎯 SUMMARY")
    print(f"📊 Local Variables: {total_local_vars}")
    print(f"📊 Parameters: {total_parameters}")
    print(f"📊 New Variables: {total_local_vars + total_parameters}")
    print(f"📊 Current (fields only): 3")
    print(f"🚀 Total after implementation: {total_local_vars + total_parameters + 3}")
    print(f"📈 Improvement: {((total_local_vars + total_parameters + 3) / 3 * 100 - 100):.0f}% increase")

if __name__ == "__main__":
    print("📋 IMPLEMENTATION STEPS:")
    print("1. Add new queries to c-sharp-queries.scm:")
    print(NEW_CSHARP_QUERIES)
    print("\n2. Add new mappings to universal_mapping_schema.yaml:")
    print(NEW_UNIVERSAL_MAPPINGS)
    print("\n3. Processing logic already exists in project_analyzer.py")
    print("\n4. Validation:")
    validate_implementation()