#!/usr/bin/env python3
"""
Test CPG database queries to understand actual schema and data structure
"""

import subprocess
import json
import sys
import os

def run_cpg_query(cypher_query):
    """Run a CPG query using the project-analyzer CLI tool."""
    try:
        # Use the project-analyzer CLI tool to run Cypher queries
        cmd = [
            "python3", "/opt/genpod/project_analyzer_cli/project_analyzer/main.py",
            "query",
            "--cypher-query", cypher_query,
            "--config", "/opt/genpod/neo4j_config.json",
            "--max-results", "10"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return {"success": True, "result": result.stdout}
        else:
            return {"success": False, "error": result.stderr}
            
    except Exception as e:
        return {"success": False, "error": str(e)}

def test_cpg_queries():
    """Test various CPG queries to understand database structure."""
    
    # Test queries to understand database structure
    test_queries = [
            {
                "name": "Find all node types",
                "query": "MATCH (n) RETURN DISTINCT labels(n) AS node_types LIMIT 10"
            },
            {
                "name": "Find all relationship types", 
                "query": "MATCH ()-[r]->() RETURN DISTINCT type(r) AS relationship_types LIMIT 10"
            },
            {
                "name": "Find all Type nodes",
                "query": "MATCH (t:Type) RETURN t.name, t.type_kind, t.file_path LIMIT 10"
            },
            {
                "name": "Find all File nodes",
                "query": "MATCH (f:File) RETURN f.name, f.file_path LIMIT 10"
            },
            {
                "name": "Find WorkerFactory specifically",
                "query": "MATCH (t:Type) WHERE t.name = 'WorkerFactory' RETURN t.name, t.file_path, t.type_kind"
            },
            {
                "name": "Find all Factory-related types",
                "query": "MATCH (t:Type) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, t.file_path LIMIT 10"
            },
            {
                "name": "Find Manager class",
                "query": "MATCH (t:Type) WHERE t.name = 'Manager' RETURN t.name, t.file_path, t.type_kind"
            },
            {
                "name": "Find all interfaces",
                "query": "MATCH (t:Type) WHERE t.type_kind = 'interface' RETURN t.name, t.file_path"
            },
            {
                "name": "Find all methods",
                "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 10"
            },
            {
                "name": "Find relationships between types",
                "query": "MATCH (t1:Type)-[r]->(t2:Type) RETURN t1.name, type(r), t2.name LIMIT 10"
            }
        ]
        
    print("Testing CPG Database Queries")
    print("=" * 80)
    
    for test in test_queries:
        print(f"\n🔍 {test['name']}:")
        print(f"Query: {test['query']}")
        
        result = run_cpg_query(test["query"])
        
        if result["success"]:
            print(f"✅ Result: {result['result']}")
        else:
            print(f"❌ Error: {result['error']}")
        
        print("-" * 40)

if __name__ == "__main__":
    test_cpg_queries()