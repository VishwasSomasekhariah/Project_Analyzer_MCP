#!/bin/bash
echo "=== Project ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Project) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== File ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:File) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Function ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Function) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Type ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Type) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Variable ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Variable) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Namespace ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Namespace) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Macro ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Macro) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Block ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Block) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Literal ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Literal) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
echo ""

echo "=== Statement ===" 
project-analyzer --config-file /opt/genpod/neo4j_config.json query --cypher "MATCH (n:Statement) RETURN keys(n) as properties LIMIT 1" 2>&1 | grep -A 3 "Results:"
