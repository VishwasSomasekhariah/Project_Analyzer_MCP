#!/usr/bin/env python3
"""
Audit all node types in Neo4j to check for schema violations.
"""
import sys
sys.path.insert(0, '/opt/genpod/project_analyzer_cli')

import yaml
import asyncio
from project_analyzer.utils.neo4j_call_tool import Neo4jToolCaller
import logging

logging.basicConfig(level=logging.WARNING)  # Suppress debug logs

async def audit_all_nodes():
    # Load schema
    with open('/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/project_knowledgebase_graph_schema.yaml', 'r') as f:
        schema = yaml.safe_load(f)
    
    neo4j_caller = Neo4jToolCaller('/opt/genpod/neo4j_config.json')
    await neo4j_caller.connect()
    
    node_types = list(schema['nodes'].keys())
    
    print("=" * 80)
    print("NODE TYPE PROPERTY AUDIT")
    print("=" * 80)
    
    for node_type in node_types:
        schema_attrs = set(schema['nodes'][node_type]['attributes'])
        
        # Query Neo4j for actual properties
        query = f"MATCH (n:{node_type}) RETURN properties(n) as props LIMIT 5"
        result = await neo4j_caller.execute_cypher_query(query)
        
        if not result.get('success') or not result.get('results'):
            print(f"\n{node_type}: No nodes found in database")
            continue
        
        # Collect all actual properties across sample nodes
        actual_props = set()
        for record in result['results']:
            props = record.get('props', {})
            actual_props.update(props.keys())
        
        # Find violations
        extra_props = actual_props - schema_attrs
        missing_props = schema_attrs - actual_props
        
        if extra_props or missing_props:
            print(f"\n{node_type}:")
            print(f"  Schema defines: {sorted(schema_attrs)}")
            print(f"  Actual has: {sorted(actual_props)}")
            
            if extra_props:
                print(f"  ❌ EXTRA properties (not in schema): {sorted(extra_props)}")
            
            if missing_props:
                # Check if missing props are truly missing (all NULL) or just not sampled
                for prop in sorted(missing_props):
                    check_query = f"MATCH (n:{node_type}) WHERE n.{prop} IS NOT NULL RETURN count(*) as count"
                    check_result = await neo4j_caller.execute_cypher_query(check_query)
                    count = check_result.get('results', [{}])[0].get('count', 0) if check_result.get('success') else 0
                    
                    if count == 0:
                        # Check total nodes
                        total_query = f"MATCH (n:{node_type}) RETURN count(*) as total"
                        total_result = await neo4j_caller.execute_cypher_query(total_query)
                        total = total_result.get('results', [{}])[0].get('total', 0) if total_result.get('success') else 0
                        
                        print(f"  ⚠️  MISSING property '{prop}': 0/{total} nodes have it (100% NULL)")
                    else:
                        print(f"  ✓  Property '{prop}' exists on {count} nodes")
        else:
            print(f"\n{node_type}: ✅ All properties match schema")
    
    await neo4j_caller.disconnect()

if __name__ == "__main__":
    asyncio.run(audit_all_nodes())
