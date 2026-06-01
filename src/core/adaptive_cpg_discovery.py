"""
Adaptive CPG Discovery Service
Implements fault-tolerant, schema-aware graph topology discovery with intelligent fallbacks
"""

import json
import yaml
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import asyncio

from src.core.paths import NEO4J_CONFIG, SCHEMA_PATH

logger = logging.getLogger(__name__)

@dataclass
class ProjectCapabilities:
    """Represents actual capabilities discovered in a project's CPG"""
    available_node_types: List[str]
    available_properties_by_type: Dict[str, List[str]]
    available_relationships: List[Dict[str, Any]]
    naming_patterns: Dict[str, str]  # discovered identifier patterns
    relationship_topology: Dict[str, List[Dict[str, Any]]]
    fault_patterns: List[Dict[str, Any]]  # discovered parsing quirks

@dataclass
class AdaptiveQuery:
    """Represents an adaptive query with fallbacks"""
    cypher: str
    purpose: str
    expected_properties: List[str]
    fallback_queries: List[str]
    validation_criteria: Dict[str, Any]

class AdaptiveCPGDiscovery:
    """
    Fault-tolerant CPG discovery that adapts to actual project topology
    instead of rigid schema assumptions
    """
    
    def __init__(self, schema_path: str = None, graph_executor=None):
        self.schema_path = schema_path or SCHEMA_PATH
        self.schema = self._load_schema()
        self.graph_executor = graph_executor
        self.project_capabilities_cache = {}
        
    def _load_schema(self) -> Dict[str, Any]:
        """Load the base schema as a guide, not gospel"""
        try:
            with open(self.schema_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"Schema loading failed: {e}, using minimal schema")
            return self._create_minimal_schema()
    
    def _create_minimal_schema(self) -> Dict[str, Any]:
        """Minimal fallback schema"""
        return {
            "nodes": {
                "Project": {"attributes": ["name", "project_path"]},
                "File": {"attributes": ["name", "file_path"]},
                "Type": {"attributes": ["name", "file_path", "body", "base_list"]},
                "Function": {"attributes": ["name", "file_path", "body", "parameters"]}
            },
            "relationships": {
                "CONTAINS": {"from": ["Project", "File", "Type"], "to": ["File", "Type", "Function"]},
                "CALLS": {"from": ["Function"], "to": ["Function"]},
                "IMPLEMENTS": {"from": ["Type"], "to": ["Type"]}
            }
        }

    async def discover_project_capabilities(self, project_name: str) -> ProjectCapabilities:
        """
        Phase 1: Discover what THIS project actually contains
        Returns real capabilities, not schema assumptions
        """
        if project_name in self.project_capabilities_cache:
            return self.project_capabilities_cache[project_name]
            
        logger.info(f"🔍 DISCOVERY: Starting adaptive discovery for {project_name}")
        
        # Multi-phase discovery
        capabilities = ProjectCapabilities(
            available_node_types=[],
            available_properties_by_type={},
            available_relationships=[],
            naming_patterns={},
            relationship_topology={},
            fault_patterns=[]
        )
        
        # Phase 1A: Discover actual node types and their properties
        node_discovery = await self._discover_actual_node_types(project_name)
        capabilities.available_node_types = node_discovery["node_types"]
        capabilities.available_properties_by_type = node_discovery["properties_by_type"]
        
        # Phase 1B: Discover actual relationships and topology
        relationship_discovery = await self._discover_relationship_topology(project_name)
        capabilities.available_relationships = relationship_discovery["relationships"]
        capabilities.relationship_topology = relationship_discovery["topology"]
        
        # Phase 1C: Discover naming patterns and fault handling
        pattern_discovery = await self._discover_naming_patterns(project_name)
        capabilities.naming_patterns = pattern_discovery["patterns"]
        capabilities.fault_patterns = pattern_discovery["faults"]
        
        # Cache for future use
        self.project_capabilities_cache[project_name] = capabilities
        
        logger.info(f"✅ DISCOVERY: Found {len(capabilities.available_node_types)} node types, "
                   f"{len(capabilities.available_relationships)} relationship patterns")
        
        return capabilities

    async def _discover_actual_node_types(self, project_name: str) -> Dict[str, Any]:
        """Discover what node types and properties actually exist"""
        discovery_query = f"""
        MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS*1..3]->(n)
        WITH labels(n)[0] AS node_type, n
        RETURN 
            node_type,
            count(*) AS node_count,
            collect(DISTINCT [key IN keys(n) WHERE n[key] IS NOT NULL]) AS available_properties_lists
        ORDER BY node_count DESC
        """
        
        try:
            from src.core.graph_query_executor import GraphQueryExecutor
            executor = self.graph_executor or GraphQueryExecutor()
            result = await executor._execute_single_query({
                "cypher": discovery_query,
                "type": "node_discovery",
                "purpose": "Discover actual node types and properties"
            }, NEO4J_CONFIG, "node_discovery")
            
            if result["status"] == "success":
                node_types = []
                properties_by_type = {}
                
                for item in result["results"]:
                    node_type = item["node_type"]
                    node_types.append(node_type)
                    
                    # Flatten and deduplicate property lists
                    all_props = set()
                    for prop_list in item["available_properties_lists"]:
                        all_props.update(prop_list)
                    
                    properties_by_type[node_type] = sorted(list(all_props))
                
                return {"node_types": node_types, "properties_by_type": properties_by_type}
            else:
                logger.warning(f"Node discovery failed: {result.get('error')}")
                return {"node_types": [], "properties_by_type": {}}
                
        except Exception as e:
            logger.error(f"Node discovery error: {e}")
            return {"node_types": [], "properties_by_type": {}}

    async def _discover_relationship_topology(self, project_name: str) -> Dict[str, Any]:
        """Discover actual relationship patterns and topology"""
        topology_query = f"""
        MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS*0..3]->(source)-[r]->(target)
        WHERE labels(source)[0] IN ['Project', 'File', 'Type', 'Function', 'Namespace', 'Variable']
        RETURN DISTINCT 
            labels(source)[0] AS source_type,
            type(r) AS relationship,
            labels(target)[0] AS target_type,
            count(*) AS frequency,
            collect(DISTINCT {{
                source_name: COALESCE(source.name, source.alias, "anonymous"),
                target_name: COALESCE(target.name, target.alias, "anonymous"),
                source_path: source.file_path,
                target_path: target.file_path
            }})[0..3] AS examples
        ORDER BY source_type, frequency DESC
        """
        
        try:
            from src.core.graph_query_executor import GraphQueryExecutor
            executor = self.graph_executor or GraphQueryExecutor()
            result = await executor._execute_single_query({
                "cypher": topology_query,
                "type": "topology_discovery", 
                "purpose": "Discover relationship topology"
            }, NEO4J_CONFIG, "topology_discovery")
            
            if result["status"] == "success":
                relationships = result["results"]
                
                # Build topology map
                topology = {}
                for rel in relationships:
                    source_type = rel["source_type"]
                    if source_type not in topology:
                        topology[source_type] = []
                    topology[source_type].append({
                        "relationship": rel["relationship"],
                        "target_type": rel["target_type"],
                        "frequency": rel["frequency"],
                        "examples": rel["examples"]
                    })
                
                return {"relationships": relationships, "topology": topology}
            else:
                logger.warning(f"Topology discovery failed: {result.get('error')}")
                return {"relationships": [], "topology": {}}
                
        except Exception as e:
            logger.error(f"Topology discovery error: {e}")
            return {"relationships": [], "topology": {}}

    async def _discover_naming_patterns(self, project_name: str) -> Dict[str, Any]:
        """Discover naming patterns and identify parsing quirks/faults"""
        pattern_query = f"""
        MATCH (p:Project {{name: '{project_name}'}})-[:CONTAINS*1..3]->(n)
        WHERE labels(n)[0] IN ['Variable', 'Function', 'Type']
        RETURN 
            labels(n)[0] AS node_type,
            n.type_kind AS semantic_type,
            CASE 
                WHEN n.name IS NOT NULL AND n.name <> "" THEN "has_name"
                WHEN n.alias IS NOT NULL AND n.alias <> "" THEN "uses_alias" 
                WHEN n.value IS NOT NULL AND n.value <> "" THEN "uses_value"
                ELSE "anonymous"
            END AS naming_pattern,
            COALESCE(n.name, n.alias, n.value, "NULL") AS effective_identifier,
            count(*) AS pattern_frequency
        ORDER BY node_type, semantic_type, pattern_frequency DESC
        """
        
        try:
            from src.core.graph_query_executor import GraphQueryExecutor
            executor = self.graph_executor or GraphQueryExecutor()
            result = await executor._execute_single_query({
                "cypher": pattern_query,
                "type": "pattern_discovery",
                "purpose": "Discover naming patterns and faults"
            }, NEO4J_CONFIG, "pattern_discovery")
            
            if result["status"] == "success":
                patterns = {}
                faults = []
                
                for item in result["results"]:
                    node_type = item["node_type"]
                    semantic_type = item.get("semantic_type", "unknown")
                    naming_pattern = item["naming_pattern"]
                    
                    # Build pattern map
                    key = f"{node_type}:{semantic_type}"
                    patterns[key] = naming_pattern
                    
                    # Identify potential faults
                    if naming_pattern in ["uses_alias", "anonymous"] and item["pattern_frequency"] > 1:
                        faults.append({
                            "node_type": node_type,
                            "semantic_type": semantic_type,
                            "fault_type": "naming_issue",
                            "pattern": naming_pattern,
                            "frequency": item["pattern_frequency"],
                            "suggestion": "Use alias/value field for identifier"
                        })
                
                return {"patterns": patterns, "faults": faults}
            else:
                return {"patterns": {}, "faults": []}
                
        except Exception as e:
            logger.error(f"Pattern discovery error: {e}")
            return {"patterns": {}, "faults": []}

    def generate_adaptive_queries(
        self, 
        user_query: str, 
        capabilities: ProjectCapabilities,
        intent: str = "architectural_analysis"
    ) -> List[AdaptiveQuery]:
        """
        Phase 2: Generate queries adapted to actual project capabilities
        """
        logger.info(f"🎯 ADAPTIVE QUERIES: Generating for intent '{intent}'")
        
        queries = []
        
        # Determine what the user needs
        query_requirements = self._analyze_query_requirements(user_query, intent)
        
        # Generate queries based on actual capabilities, not schema assumptions
        if intent == "architectural_analysis":
            queries.extend(self._generate_architectural_queries(capabilities, query_requirements))
        elif intent == "dependency_analysis":
            queries.extend(self._generate_dependency_queries(capabilities, query_requirements))
        elif intent == "implementation_details":
            queries.extend(self._generate_implementation_queries(capabilities, query_requirements))
        else:
            queries.extend(self._generate_general_queries(capabilities, query_requirements))
        
        logger.info(f"✅ Generated {len(queries)} adaptive queries")
        return queries

    def _analyze_query_requirements(self, user_query: str, intent: str) -> Dict[str, Any]:
        """Analyze what properties/relationships the query actually needs"""
        requirements = {
            "needs_implementation": any(word in user_query.lower() 
                                     for word in ["body", "code", "implementation", "how"]),
            "needs_structure": any(word in user_query.lower() 
                                 for word in ["structure", "architecture", "components", "classes"]),
            "needs_relationships": any(word in user_query.lower() 
                                    for word in ["calls", "uses", "depends", "inherits", "implements"]),
            "needs_locations": any(word in user_query.lower() 
                                 for word in ["where", "file", "location"]),
            "needs_metrics": any(word in user_query.lower() 
                               for word in ["count", "how many", "number"])
        }
        
        # Intent-based requirements
        if intent == "architectural_analysis":
            requirements.update({
                "needs_structure": True,
                "needs_relationships": True
            })
        elif intent == "implementation_details":
            requirements.update({
                "needs_implementation": True,
                "needs_locations": True
            })
        
        return requirements

    def _generate_architectural_queries(
        self, 
        capabilities: ProjectCapabilities, 
        requirements: Dict[str, Any]
    ) -> List[AdaptiveQuery]:
        """Generate architecture-focused queries adapted to actual capabilities"""
        queries = []
        
        # Project overview query - adapted to available node types
        available_types = capabilities.available_node_types
        type_filter = "', '".join([t for t in available_types if t in ['File', 'Type', 'Function', 'Namespace']])
        
        overview_query = f"""
        MATCH (p:Project)-[:CONTAINS*1..2]->(element)
        WHERE labels(element)[0] IN ['{type_filter}']
        RETURN 
            p.name AS project_name,
            labels(element)[0] AS element_type,
            COALESCE(element.name, element.alias, 'anonymous') AS element_name,
            element.file_path AS file_path,
            CASE labels(element)[0]
                WHEN 'Type' THEN element.base_list
                ELSE NULL 
            END AS inheritance_info
        ORDER BY element_type, file_path, element_name
        """
        
        queries.append(AdaptiveQuery(
            cypher=overview_query,
            purpose="Get project architectural overview",
            expected_properties=["name", "file_path", "base_list"],
            fallback_queries=[
                "MATCH (p:Project)-[:CONTAINS]->(f:File) RETURN p.name, f.name, f.file_path"
            ],
            validation_criteria={"min_results": 5, "required_types": ["File", "Type"]}
        ))
        
        # Relationship mapping - adapted to discovered topology
        if "Type" in available_types and capabilities.relationship_topology.get("Type"):
            type_relationships = capabilities.relationship_topology["Type"]
            relationship_types = [rel["relationship"] for rel in type_relationships 
                                if rel["relationship"] in ["IMPLEMENTS", "INHERITS_FROM", "CONTAINS"]]
            
            if relationship_types:
                rel_filter = "', '".join(relationship_types)
                relationship_query = f"""
                MATCH (t:Type)-[r]->(target)
                WHERE type(r) IN ['{rel_filter}']
                RETURN 
                    t.name AS source_class,
                    t.file_path AS source_file,
                    type(r) AS relationship_type,
                    COALESCE(target.name, target.alias) AS target_name,
                    target.file_path AS target_file,
                    labels(target)[0] AS target_type
                ORDER BY source_class, relationship_type
                """
                
                queries.append(AdaptiveQuery(
                    cypher=relationship_query,
                    purpose="Map class relationships and dependencies",
                    expected_properties=["name", "file_path"],
                    fallback_queries=[
                        "MATCH (t:Type) RETURN t.name, t.file_path, t.base_list"
                    ],
                    validation_criteria={"min_results": 1}
                ))
        
        return queries

    def _generate_dependency_queries(
        self, 
        capabilities: ProjectCapabilities, 
        requirements: Dict[str, Any]
    ) -> List[AdaptiveQuery]:
        """Generate dependency analysis queries"""
        queries = []
        
        # Function call dependencies - if available
        if "Function" in capabilities.available_node_types:
            call_query = """
            MATCH (caller:Function)-[:CALLS]->(callee:Function)
            RETURN 
                COALESCE(caller.name, 'anonymous') AS caller_name,
                caller.file_path AS caller_file,
                COALESCE(callee.name, 'anonymous') AS callee_name,
                callee.file_path AS callee_file
            ORDER BY caller_file, caller_name
            """
            
            queries.append(AdaptiveQuery(
                cypher=call_query,
                purpose="Map function call dependencies",
                expected_properties=["name", "file_path"],
                fallback_queries=["MATCH (f:Function) RETURN f.name, f.file_path"],
                validation_criteria={"min_results": 1}
            ))
        
        return queries

    def _generate_implementation_queries(
        self, 
        capabilities: ProjectCapabilities, 
        requirements: Dict[str, Any]
    ) -> List[AdaptiveQuery]:
        """Generate implementation detail queries"""
        queries = []
        
        # Only request body if it's actually available
        type_props = capabilities.available_properties_by_type.get("Type", [])
        function_props = capabilities.available_properties_by_type.get("Function", [])
        
        if "body" in type_props and requirements.get("needs_implementation"):
            implementation_query = """
            MATCH (t:Type)
            WHERE t.body IS NOT NULL AND t.body <> ""
            RETURN 
                COALESCE(t.name, t.alias) AS class_name,
                t.file_path AS file_path,
                LEFT(t.body, 200) AS implementation_preview,
                t.base_list AS inheritance
            ORDER BY class_name
            """
            
            queries.append(AdaptiveQuery(
                cypher=implementation_query,
                purpose="Get class implementation details",
                expected_properties=["name", "body", "file_path"],
                fallback_queries=[
                    "MATCH (t:Type) RETURN t.name, t.file_path, t.base_list"
                ],
                validation_criteria={"min_results": 1}
            ))
        
        return queries

    def _generate_general_queries(
        self, 
        capabilities: ProjectCapabilities, 
        requirements: Dict[str, Any]
    ) -> List[AdaptiveQuery]:
        """Generate general fallback queries"""
        queries = []
        
        # Basic project structure
        basic_query = """
        MATCH (p:Project)-[:CONTAINS]->(f:File)
        RETURN 
            p.name AS project_name,
            f.name AS file_name,
            f.file_path AS file_path
        ORDER BY file_path
        """
        
        queries.append(AdaptiveQuery(
            cypher=basic_query,
            purpose="Basic project structure",
            expected_properties=["name", "file_path"],
            fallback_queries=["MATCH (p:Project) RETURN p.name"],
            validation_criteria={"min_results": 1}
        ))
        
        return queries

    def extract_fault_tolerant_identifier(self, node_data: Dict, node_type: str) -> str:
        """
        Extract identifier using discovered patterns and schema guidance
        Implements the fault-tolerant identifier strategy we discussed
        """
        # Use discovered naming patterns
        capabilities = self.project_capabilities_cache.get("current_project")
        if capabilities:
            pattern_key = f"{node_type}:{node_data.get('type_kind', 'unknown')}"
            pattern = capabilities.naming_patterns.get(pattern_key, "has_name")
            
            if pattern == "uses_alias" and node_data.get("alias"):
                return node_data["alias"]
            elif pattern == "uses_value" and node_data.get("value"):
                return node_data["value"]
        
        # Schema-guided fallback chain
        for field in ["name", "alias", "value"]:
            if node_data.get(field) and node_data[field] != "":
                return node_data[field]
        
        # Semantic fallback
        if node_data.get("type_kind"):
            return f"anonymous_{node_data['type_kind']}"
        
        return f"anonymous_{node_type.lower()}"