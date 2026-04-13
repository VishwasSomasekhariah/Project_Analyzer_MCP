#!/usr/bin/env python3
"""
Test what suggestions the validator returned during the benchmark
"""
import sys
sys.path.insert(0, '/opt/genpod')

import pickle
from src.core.workflow.cypher_query_validator import CypherQueryValidator

# Load state from benchmark run
with open('/opt/genpod/STATE.pkl', 'rb') as f:
    state = pickle.load(f)

# Get the reconciled schema
schema_manager = state['schema_manager']
schema = schema_manager._reconciled_schema

print("=" * 80)
print("TESTING VALIDATOR SUGGESTIONS")
print("=" * 80)

# Test Query 1: Statement-[:CONTAINS]->Type
query1 = """
MATCH (stmt:Statement)-[:CONTAINS]->(t:Type)
WHERE stmt.type = 'assignment'
RETURN t.name
"""

print("\n### TEST 1: (Statement)-[:CONTAINS]->(Type)")
print(f"Query: {query1.strip()}")

validator = CypherQueryValidator(schema)
result = validator.validate(query1)

print(f"\nValid: {result.is_valid}")
print(f"Errors: {len(result.errors)}")

for issue in result.get_errors():
    print(f"\n❌ {issue.location}")
    print(f"   Message: {issue.message}")
    if issue.suggestion:
        print(f"   Suggestion: {issue.suggestion}")
    else:
        print(f"   Suggestion: (NONE - THIS IS THE PROBLEM!)")

# Test Query 2: Statement-[:REFERENCES]->Type
query2 = """
MATCH (stmt:Statement)-[:REFERENCES]->(t:Type)
RETURN t.name
"""

print("\n" + "=" * 80)
print("### TEST 2: (Statement)-[:REFERENCES]->(Type)")
print(f"Query: {query2.strip()}")

result2 = validator.validate(query2)

print(f"\nValid: {result2.is_valid}")
print(f"Errors: {len(result2.errors)}")

for issue in result2.get_errors():
    print(f"\n❌ {issue.location}")
    print(f"   Message: {issue.message}")
    if issue.suggestion:
        print(f"   Suggestion: {issue.suggestion}")
    else:
        print(f"   Suggestion: (NONE - THIS IS THE PROBLEM!)")

# Show what CONTAINS relationships actually exist
print("\n" + "=" * 80)
print("### VALID CONTAINS RELATIONSHIPS IN SCHEMA")
print("=" * 80)

contains_pairs = validator.valid_pairs.get('CONTAINS', set())
print(f"\nTotal CONTAINS pairs: {len(contains_pairs)}")

for source, target in sorted(contains_pairs):
    print(f"  ({source})-[:CONTAINS]->({target})")

# Check Statement relationships
print("\n" + "=" * 80)
print("### ALL STATEMENT RELATIONSHIPS IN SCHEMA")
print("=" * 80)

has_statement = False
for rel_type, pairs in validator.valid_pairs.items():
    for source, target in pairs:
        if 'Statement' in (source, target):
            print(f"  ({source})-[:{rel_type}]->({target})")
            has_statement = True

if not has_statement:
    print("  ⚠️  Statement nodes have NO relationships in the reconciled schema!")
    print("  This is why the validator couldn't suggest alternatives!")

print("\n" + "=" * 80)
print("### ANALYSIS")
print("=" * 80)

print("""
When the validator tried to suggest alternatives for (Statement)-[:CONTAINS]->(Type):
1. It looked for valid_targets: What can Statement CONTAINS-connect to?
   → Result: EMPTY (Statement has no outgoing CONTAINS relationships)

2. It looked for valid_sources: What can CONTAINS-connect to Type?
   → Result: File, Namespace, Function, etc. (but NOT Statement)

3. Because valid_targets was empty, it didn't add the "Valid patterns:" part
4. Because Statement wasn't in valid_sources, it SHOULD have added "To reach Type:" suggestions

Let's check what it actually generated...
""")

# Manually reproduce the suggestion logic
print("Reproducing validator suggestion logic:")
print("-" * 80)

rel_type = "CONTAINS"
from_label = "Statement"
to_label = "Type"

valid_pairs = validator.valid_pairs.get(rel_type, set())
valid_targets = sorted({t for s, t in valid_pairs if s == from_label})
valid_sources = sorted({s for s, t in valid_pairs if t == to_label})

print(f"Relationship: {rel_type}")
print(f"From: {from_label}")
print(f"To: {to_label}")
print(f"\nvalid_targets (what Statement can CONTAINS to): {valid_targets}")
print(f"valid_sources (what can CONTAINS to Type): {valid_sources}")

suggestion_parts = []

# Part 1: Show what this source CAN connect to
if valid_targets:
    examples = [f"({from_label})-[:{rel_type}]->({t})" for t in valid_targets[:3]]
    more = f" (+{len(valid_targets)-3} more)" if len(valid_targets) > 3 else ""
    part1 = f"Valid patterns: {', '.join(examples)}{more}"
    suggestion_parts.append(part1)
    print(f"\n✅ Part 1 added: {part1}")
else:
    print(f"\n❌ Part 1 NOT added (valid_targets is empty)")

# Part 2: Show what CAN connect to this target
if valid_sources and from_label not in valid_sources:
    examples = [f"({s})-[:{rel_type}]->({to_label})" for s in valid_sources[:3]]
    more = f" (+{len(valid_sources)-3} more)" if len(valid_sources) > 3 else ""
    part2 = f"To reach {to_label}: {', '.join(examples)}{more}"
    suggestion_parts.append(part2)
    print(f"✅ Part 2 added: {part2}")
else:
    print(f"❌ Part 2 NOT added")
    print(f"   Condition: valid_sources exists? {bool(valid_sources)}")
    print(f"   Condition: from_label NOT in valid_sources? {from_label not in valid_sources}")

final_suggestion = " | ".join(suggestion_parts) if suggestion_parts else f"Check schema for valid {rel_type} patterns"
print(f"\n🎯 Final suggestion: {final_suggestion}")
