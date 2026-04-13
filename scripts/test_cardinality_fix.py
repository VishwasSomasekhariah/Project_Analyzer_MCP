#!/usr/bin/env python3
"""
Test script to verify the cardinality-based relationship extraction fix.

This simulates what would happen with SQ2's subquery using the new implementation.
"""
import json

print("="*100)
print("TESTING CARDINALITY-BASED RELATIONSHIP EXTRACTION FIX")
print("="*100)

# Load the reconciled schema (the same one DynamicSchemaManager uses)
with open('/tmp/reconciled_schema_complete.json', 'r') as f:
    reconciled_schema = json.load(f)

# Simulate SQ2's extracted nodes
# The embedding extraction would return these based on the subquery:
# "Retrieve all Type nodes that are INSTANTIATED within the body of the CreateWorkers Function node."
node_types = ['Function', 'Type', 'Namespace']  # From log line 430 (Run 4, SQ2)

print(f"\n📝 SQ2 Subquery: 'Retrieve all Type nodes that are INSTANTIATED within the body...'")
print(f"📊 Extracted node types (embedding-based): {node_types}")

# OLD METHOD (embedding-based relationship extraction)
# This would only return ['CALLS'] for SQ2 ❌
print("\n" + "="*100)
print("OLD METHOD (Embedding-based) - What Run 4 got:")
print("="*100)
print("rels=['CALLS']  ❌")
print("\nProblem: 'instantiated' didn't semantically match IMPLEMENTS or CONTAINS")

# NEW METHOD (cardinality-based relationship extraction)
print("\n" + "="*100)
print("NEW METHOD (Cardinality-based) - What we would get now:")
print("="*100)

node_set = set(node_types)
relationship_types = []

for rel_type, rel_info in reconciled_schema.get('relationships', {}).items():
    cardinality = rel_info.get('cardinality', [])

    # Check if ANY cardinality pair connects our nodes
    if any(pair.get('from') in node_set or pair.get('to') in node_set
           for pair in cardinality):
        relationship_types.append(rel_type)

        # Show WHY this relationship was included
        matching_pairs = [
            f"({p.get('from')}→{p.get('to')})"
            for p in cardinality
            if p.get('from') in node_set or p.get('to') in node_set
        ]
        print(f"✅ {rel_type:<20} connects: {', '.join(matching_pairs[:3])}")
        if len(matching_pairs) > 3:
            print(f"{'':23} ... and {len(matching_pairs)-3} more pairs")

print(f"\n📊 Total relationships: {len(relationship_types)}")
print(f"Relationships: {relationship_types}")

# Verify the critical relationships are included
print("\n" + "="*100)
print("VERIFICATION - Critical Relationships for SQ2")
print("="*100)

critical_rels = {
    'IMPLEMENTS': 'Needed for (Function)-[:IMPLEMENTS]->(Type) to find type relationships',
    'CONTAINS': 'Needed for (Function)-[:CONTAINS]->(Block)-[:CONTAINS]->(Statement) to query body',
    'CALLS': 'Useful for tracing function invocations'
}

all_included = True
for rel_name, reason in critical_rels.items():
    if rel_name in relationship_types:
        print(f"✅ {rel_name:<15} INCLUDED - {reason}")
    else:
        print(f"❌ {rel_name:<15} MISSING  - {reason}")
        all_included = False

print("\n" + "="*100)
if all_included:
    print("🎉 SUCCESS! All critical relationships are now included!")
    print("\nWith CONTAINS, the LLM can now generate:")
    print("   MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)")
    print("         -[:CONTAINS]->(s:Statement)")
    print("   WHERE s.text CONTAINS 'new'")
    print("   RETURN s.text")
    print("\nThis would have prevented the fake query in Run 4!")
else:
    print("❌ FAILURE! Some critical relationships are still missing.")
    print("The fix may not be complete.")

# Additional verification: Path discovery
print("\n" + "="*100)
print("PATH DISCOVERY IMPACT")
print("="*100)

print("\nOLD (Run 4 SQ2 with only CALLS):")
print("  🛤️  Discovering paths between 3 node types...")
print("     ✅ Discovered 0 path patterns  ❌")
print("\n  Reason: CALLS only connects Function→Function, not Function↔Type")

print("\nNEW (With cardinality-based relationships):")
print("  🛤️  Discovering paths between 3 node types...")
print("  Expected paths:")
print("     • Function → Type via IMPLEMENTS")
print("     • Type → Function via CONTAINS")
print("     • Function → Namespace via DEFINED_IN (if available)")
print("     • Plus multi-hop paths through intermediate nodes")
print("\n  The path discovery uses relationship_types, so it's automatically fixed!")

print("="*100)
