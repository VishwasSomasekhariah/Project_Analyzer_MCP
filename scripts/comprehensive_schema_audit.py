#!/usr/bin/env python3
"""
Comprehensive audit of ALL node types:
For each node type, compare ALL schema-defined properties vs actual Neo4j properties
"""
import yaml

# Load schema
with open('/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/project_knowledgebase_graph_schema.yaml', 'r') as f:
    schema = yaml.safe_load(f)

print("=" * 100)
print("COMPREHENSIVE NODE PROPERTY AUDIT")
print("Comparing Schema Definition vs Neo4j Reality")
print("=" * 100)

node_types = list(schema['nodes'].keys())

# Output queries to run
queries = []
for node_type in node_types:
    query = f'project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:{node_type}) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 5 "Cypher query results"'
    queries.append((node_type, query))

# Print schema first
print("\n" + "=" * 100)
print("SCHEMA DEFINITIONS:")
print("=" * 100)
for node_type in node_types:
    attrs = schema['nodes'][node_type]['attributes']
    print(f"\n{node_type}:")
    print(f"  Expected attributes: {attrs}")

print("\n" + "=" * 100)
print("Run these queries to get actual Neo4j properties:")
print("=" * 100)
for node_type, _ in queries:
    print(f'\necho "=== {node_type} ===" && project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:{node_type}) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"')

