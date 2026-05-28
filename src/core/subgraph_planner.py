"""
Subgraph Planning Engine for Advanced Graph RAG
Plans multi-seed point retrieval strategies based on extracted entities and query intent
"""

import os
import yaml
from typing import Dict, List, Any, Optional, Tuple


class SubgraphPlanner:
    """Plan multi-seed point retrieval strategies for graph RAG"""
    
    def __init__(self, schema_path: str = None):
        self.schema_path = schema_path or self._get_default_schema_path()
        self.schema = self._load_schema()
        
        # Query templates for different entity types and intents
        self.query_templates = {
            "file_seed": {
                "exact_match": "MATCH (f:File) WHERE f.name = '{entity}' OR f.file_path ENDS WITH '{entity}'",
                "partial_match": "MATCH (f:File) WHERE f.name CONTAINS '{entity}' OR f.file_path CONTAINS '{entity}'"
            },
            "type_seed": {
                "exact_match": "MATCH (t:Type) WHERE t.name = '{entity}'",
                "partial_match": "MATCH (t:Type) WHERE t.name CONTAINS '{entity}'"
            },
            "function_seed": {
                "exact_match": "MATCH (func:Function) WHERE func.name = '{entity}'",
                "partial_match": "MATCH (func:Function) WHERE func.name CONTAINS '{entity}'"
            },
            "project_seed": {
                "exact_match": "MATCH (p:Project) WHERE p.name = '{entity}'",
                "partial_match": "MATCH (p:Project) WHERE p.name CONTAINS '{entity}'"
            }
        }
        
        # Property sets for different analysis intents
        self.intent_properties = {
            "count_analysis": {
                "essential": ["body", "symbols_location", "start_point", "end_point"],
                "useful": ["name", "file_path", "type_kind"]
            },
            "structural_analysis": {
                "essential": ["symbols_location", "fields", "parameters", "return_type", "base_list"],
                "useful": ["name", "file_path", "type_kind", "modifier", "body"]
            },
            "relationship_analysis": {
                "essential": ["base_list", "type_kind", "modifier"],
                "useful": ["name", "file_path", "body", "fields"]
            },
            "locational_analysis": {
                "essential": ["file_path", "start_point", "end_point"],
                "useful": ["name", "type_kind", "body"]
            },
            "comparative_analysis": {
                "essential": ["name", "type_kind", "body", "base_list", "fields"],
                "useful": ["file_path", "modifier", "parameters", "return_type"]
            },
            "behavioral_analysis": {
                "essential": ["body", "parameters", "return_type"],
                "useful": ["name", "file_path", "symbols_location", "type_kind"]
            },
            "project_architectural_analysis": {
                "essential": ["name", "project_path", "version", "type_kind", "base_list"],
                "useful": ["project_checksum", "created_at", "modified_at", "body", "fields", "file_path"]
            }
        }
    
    async def plan_retrieval(self, entities: Dict[str, Any], user_query: str) -> Dict[str, Any]:
        """
        Create multi-seed point retrieval plan based on entities and intent
        
        Args:
            entities: Extracted entities from EntityExtractionService
            user_query: Original user query for context
            
        Returns:
            {
                "seed_queries": [
                    {"type": "file_seed", "cypher": "...", "purpose": "...", "priority": 1.0},
                    {"type": "type_seed", "cypher": "...", "purpose": "...", "priority": 0.8}
                ],
                "expansion_queries": [
                    {"hops": 1, "cypher": "...", "purpose": "...", "depends_on": "file_seed"},
                    {"hops": 2, "cypher": "...", "purpose": "...", "depends_on": "type_seed"}
                ],
                "target_properties": ["body", "symbols_location", ...],
                "strategy": "content_focused",
                "expected_analysis": "comment_counting",
                "query_complexity": "medium",
                "estimated_nodes": 50
            }
        """
        intent = entities.get("intent", "unknown")
        confidence = entities.get("confidence", 0.5)
        
        # Generate seed queries based on extracted entities
        seed_queries = self._generate_seed_queries(entities)
        
        # Generate expansion queries based on intent and relationships
        expansion_queries = self._generate_expansion_queries(entities, seed_queries)
        
        # Determine target properties based on intent
        target_properties = self._determine_target_properties(entities, intent)
        
        # Determine retrieval strategy
        strategy = self._determine_strategy(entities, intent, confidence)
        
        # Estimate query complexity and expected results
        complexity_info = self._estimate_query_complexity(seed_queries, expansion_queries)
        
        return {
            "seed_queries": seed_queries,
            "expansion_queries": expansion_queries,
            "target_properties": target_properties,
            "strategy": strategy,
            "expected_analysis": self._determine_expected_analysis(entities, intent),
            "query_complexity": complexity_info["complexity"],
            "estimated_nodes": complexity_info["estimated_nodes"],
            "planning_metadata": {
                "entities_processed": entities,
                "intent": intent,
                "confidence": confidence,
                "total_queries": len(seed_queries) + len(expansion_queries)
            }
        }
    
    def _generate_seed_queries(self, entities: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate seed queries for initial entity retrieval"""
        seed_queries = []
        
        # Project-based seeds (highest priority for architectural analysis)
        for project_entity in entities.get("projects", []):
            query = self._create_project_seed_query(project_entity)
            if query:
                seed_queries.append({
                    "type": "project_seed",
                    "entity": project_entity,
                    "cypher": query,
                    "purpose": f"Get project structure and hierarchy for {project_entity}",
                    "priority": 1.0,
                    "match_type": "exact"
                })
        
        # File-based seeds (high priority for specific files)
        for file_entity in entities.get("files", []):
            query = self._create_file_seed_query(file_entity)
            if query:
                seed_queries.append({
                    "type": "file_seed",
                    "entity": file_entity,
                    "cypher": query,
                    "purpose": f"Get file node and contained elements for {file_entity}",
                    "priority": 0.9,
                    "match_type": "exact"
                })
        
        # Type-based seeds (medium priority for classes/interfaces)
        for type_entity in entities.get("types", []):
            query = self._create_type_seed_query(type_entity)
            if query:
                seed_queries.append({
                    "type": "type_seed",
                    "entity": type_entity,
                    "cypher": query,
                    "purpose": f"Get type definition and structure for {type_entity}",
                    "priority": 0.9,
                    "match_type": "exact"
                })
        
        # Function-based seeds (medium priority)
        for func_entity in entities.get("functions", []):
            query = self._create_function_seed_query(func_entity)
            if query:
                seed_queries.append({
                    "type": "function_seed", 
                    "entity": func_entity,
                    "cypher": query,
                    "purpose": f"Get function definition and calls for {func_entity}",
                    "priority": 0.7,
                    "match_type": "exact"
                })
        
        # Sort by priority (highest first)
        seed_queries.sort(key=lambda x: x["priority"], reverse=True)
        
        return seed_queries
    
    def _generate_expansion_queries(self, entities: Dict[str, Any], seed_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generate expansion queries for multi-hop traversal"""
        expansion_queries = []
        intent = entities.get("intent", "unknown")
        
        # 1-hop expansion: Get direct relationships
        if seed_queries:
            expansion_queries.extend(self._create_1hop_expansions(entities, seed_queries, intent))
        
        # 2-hop expansion: Get related entities (for relationship analysis)
        if intent in ["relationship_analysis", "comparative_analysis"]:
            expansion_queries.extend(self._create_2hop_expansions(entities, seed_queries, intent))
        
        # Cross-file expansion: Get related files (for comprehensive analysis)
        if intent in ["structural_analysis", "behavioral_analysis"]:
            expansion_queries.extend(self._create_cross_file_expansions(entities, seed_queries))
        
        return expansion_queries
    
    def _create_file_seed_query(self, file_entity: str) -> str:
        """Create optimized file seed query with rich property retrieval"""
        # Clean file entity (remove quotes, normalize)
        clean_file = file_entity.strip('\'"')
        
        return f"""
        MATCH (f:File) 
        WHERE f.name = '{clean_file}' OR f.file_path ENDS WITH '{clean_file}'
        RETURN f.name, f.file_path, f.file_checksum, f.start_point, f.end_point
        """
    
    def _create_type_seed_query(self, type_entity: str) -> str:
        """Create optimized type seed query with rich content retrieval"""
        clean_type = type_entity.strip('\'"')
        
        return f"""
        MATCH (t:Type) 
        WHERE t.name = '{clean_type}'
        RETURN t.name, t.type_kind, t.file_path, t.body, t.symbols_location, 
               t.fields, t.base_list, t.modifier, t.start_point, t.end_point,
               t.start_byte, t.end_byte
        """
    
    def _create_function_seed_query(self, func_entity: str) -> str:
        """Create optimized function seed query"""
        clean_func = func_entity.strip('\'"')
        
        return f"""
        MATCH (func:Function)
        WHERE func.name = '{clean_func}'
        RETURN func.name, func.type_kind, func.file_path, func.body, func.parameters,
               func.return_type, func.modifier, func.start_point, func.end_point,
               func.symbols_location
        """
    
    def _create_project_seed_query(self, project_entity: str) -> str:
        """Create optimized project seed query for architectural analysis"""
        clean_project = project_entity.strip('\'"')
        
        return f"""
        MATCH (p:Project) 
        WHERE p.name = '{clean_project}'
        RETURN p.name, p.project_path, p.project_checksum, p.version, p.type,
               p.created_at, p.modified_at
        """
    
    def _create_1hop_expansions(self, entities: Dict[str, Any], seed_queries: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
        """Create 1-hop expansion queries from seed entities"""
        expansions = []
        
        # File -> Contents expansion (most common and valuable)
        if any(sq["type"] == "file_seed" for sq in seed_queries):
            file_expansion = {
                "hops": 1,
                "cypher": """
                MATCH (f:File)-[:CONTAINS]->(contained)
                WHERE f.name = '{file_entity}' OR f.file_path ENDS WITH '{file_entity}'
                RETURN contained.name, contained.type_kind, contained.file_path, 
                       contained.body, contained.symbols_location, contained.fields,
                       contained.base_list, contained.parameters, contained.return_type,
                       contained.start_point, contained.end_point, labels(contained) as node_type
                """,
                "purpose": "Get all elements contained in target file",
                "depends_on": "file_seed",
                "priority": 0.9
            }
            
            # Customize query based on available file entities
            file_entities = entities.get("files", [])
            if file_entities:
                file_expansion["cypher"] = file_expansion["cypher"].format(
                    file_entity=file_entities[0].strip('\'"')
                )
                expansions.append(file_expansion)
        
        # Type -> Members expansion
        if any(sq["type"] == "type_seed" for sq in seed_queries):
            type_entities = entities.get("types", [])
            if type_entities:
                type_expansion = {
                    "hops": 1,
                    "cypher": f"""
                    MATCH (t:Type)-[:CONTAINS]->(member)
                    WHERE t.name = '{type_entities[0].strip('\'"')}'
                    RETURN member.name, member.type_kind, member.body, member.parameters,
                           member.return_type, member.modifier, member.symbols_location,
                           labels(member) as node_type
                    """,
                    "purpose": f"Get members of {type_entities[0]} class/interface",
                    "depends_on": "type_seed",
                    "priority": 0.8
                }
                expansions.append(type_expansion)
        
        # Project -> Files expansion (for architectural analysis)
        if any(sq["type"] == "project_seed" for sq in seed_queries) and intent == "project_architectural_analysis":
            project_entities = entities.get("projects", [])
            if project_entities:
                project_expansion = {
                    "hops": 1,
                    "cypher": f"""
                    MATCH (p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(element)
                    WHERE p.name = '{project_entities[0].strip('\'"')}'
                    RETURN DISTINCT f.name, f.file_path, element.name, element.type_kind,
                           element.body, element.base_list, element.fields, element.parameters,
                           element.return_type, element.modifier, labels(element) as node_type
                    """,
                    "purpose": f"Get project structure and main components for {project_entities[0]}",
                    "depends_on": "project_seed",
                    "priority": 0.9
                }
                expansions.append(project_expansion)
        
        # Function -> Calls expansion (for behavioral analysis)
        if intent in ["behavioral_analysis", "relationship_analysis"]:
            func_entities = entities.get("functions", [])
            if func_entities:
                calls_expansion = {
                    "hops": 1,
                    "cypher": f"""
                    MATCH (func:Function)-[:CALLS]->(called:Function)
                    WHERE func.name = '{func_entities[0].strip('\'"')}'
                    RETURN called.name, called.file_path, called.body, called.parameters,
                           called.return_type, called.type_kind
                    """,
                    "purpose": f"Get functions called by {func_entities[0]}",
                    "depends_on": "function_seed",
                    "priority": 0.7
                }
                expansions.append(calls_expansion)
        
        return expansions
    
    def _create_2hop_expansions(self, entities: Dict[str, Any], seed_queries: List[Dict[str, Any]], intent: str) -> List[Dict[str, Any]]:
        """Create 2-hop expansion queries for deeper relationship analysis"""
        expansions = []
        
        # Type inheritance chains
        type_entities = entities.get("types", [])
        if type_entities and intent == "relationship_analysis":
            inheritance_expansion = {
                "hops": 2,
                "cypher": f"""
                MATCH (t:Type)-[:INHERITS_FROM|IMPLEMENTS*1..2]->(related:Type)
                WHERE t.name = '{type_entities[0].strip('\'"')}'
                RETURN related.name, related.type_kind, related.file_path, related.body,
                       related.base_list, related.fields, related.modifier
                """,
                "purpose": f"Get inheritance hierarchy for {type_entities[0]}",
                "depends_on": "type_seed",
                "priority": 0.6
            }
            expansions.append(inheritance_expansion)
        
        # Cross-file type relationships
        if intent == "comparative_analysis":
            cross_file_expansion = {
                "hops": 2,
                "cypher": """
                MATCH (f:File)-[:CONTAINS]->(t1:Type)-[:INHERITS_FROM|IMPLEMENTS]->(t2:Type)<-[:CONTAINS]-(f2:File)
                WHERE f.name = '{file_entity}'
                RETURN t2.name, t2.type_kind, t2.file_path, t2.body, f2.name as related_file
                """,
                "purpose": "Get cross-file type relationships",
                "depends_on": "file_seed",
                "priority": 0.5
            }
            
            file_entities = entities.get("files", [])
            if file_entities:
                cross_file_expansion["cypher"] = cross_file_expansion["cypher"].format(
                    file_entity=file_entities[0].strip('\'"')
                )
                expansions.append(cross_file_expansion)
        
        return expansions
    
    def _create_cross_file_expansions(self, entities: Dict[str, Any], seed_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Create cross-file expansion queries for comprehensive analysis"""
        expansions = []
        
        # Related files through type relationships
        if entities.get("types"):
            related_files_expansion = {
                "hops": 2,
                "cypher": """
                MATCH (t:Type)-[:INHERITS_FROM|IMPLEMENTS]->(related:Type)-[:DEFINED_IN]->(f:File)
                WHERE t.name IN {type_list}
                RETURN DISTINCT f.name, f.file_path, related.name as related_type,
                       related.type_kind, related.body
                """,
                "purpose": "Get files containing related types",
                "depends_on": "type_seed",
                "priority": 0.4
            }
            
            # Format type list for Cypher query  
            type_list = [f"'{t.strip('\"')}'" for t in entities.get("types", [])]
            related_files_expansion["cypher"] = related_files_expansion["cypher"].format(
                type_list=f"[{', '.join(type_list)}]"
            )
            expansions.append(related_files_expansion)
        
        return expansions
    
    def _determine_target_properties(self, entities: Dict[str, Any], intent: str) -> List[str]:
        """Determine target properties based on intent and entities"""
        base_properties = ["name", "file_path", "type_kind"]
        
        if intent in self.intent_properties:
            essential = self.intent_properties[intent]["essential"]
            useful = self.intent_properties[intent]["useful"]
            return list(set(base_properties + essential + useful))
        
        # Default property set
        return base_properties + ["body", "symbols_location", "start_point", "end_point"]
    
    def _determine_strategy(self, entities: Dict[str, Any], intent: str, confidence: float) -> str:
        """Determine optimal retrieval strategy"""
        if confidence >= 0.8 and entities.get("files"):
            return "targeted_file_analysis"
        elif intent == "count_analysis":
            return "content_focused"
        elif intent in ["relationship_analysis", "comparative_analysis"]:
            return "relationship_traversal"
        elif intent == "structural_analysis":
            return "structural_mapping"
        else:
            return "comprehensive_exploration"
    
    def _determine_expected_analysis(self, entities: Dict[str, Any], intent: str) -> str:
        """Determine expected analysis type based on entities and intent"""
        concepts = entities.get("concepts", [])
        
        if "comment lines" in concepts:
            return "comment_counting"
        elif "method calls" in concepts:
            return "call_analysis"
        elif "inheritance" in concepts:
            return "inheritance_analysis"
        elif intent == "count_analysis":
            return "quantitative_analysis"
        elif intent == "structural_analysis":
            return "structural_analysis"
        elif intent == "relationship_analysis":
            return "relationship_mapping"
        else:
            return "general_code_analysis"
    
    def _estimate_query_complexity(self, seed_queries: List[Dict[str, Any]], expansion_queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Estimate query complexity and expected result size"""
        total_queries = len(seed_queries) + len(expansion_queries)
        max_hops = max([eq.get("hops", 1) for eq in expansion_queries] + [1])
        
        # Complexity estimation
        if total_queries <= 2 and max_hops <= 1:
            complexity = "low"
            estimated_nodes = 10
        elif total_queries <= 5 and max_hops <= 2:
            complexity = "medium"
            estimated_nodes = 50
        else:
            complexity = "high"
            estimated_nodes = 100
        
        return {
            "complexity": complexity,
            "estimated_nodes": estimated_nodes,
            "total_queries": total_queries,
            "max_hops": max_hops
        }
    
    def _get_default_schema_path(self) -> str:
        """Get default path to graph schema file"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(current_dir, "..", "schemas", "project_knowledgebase_graph_schema.yaml")
    
    def _load_schema(self) -> Dict[str, Any]:
        """Load the graph schema from YAML file"""
        try:
            if os.path.exists(self.schema_path):
                with open(self.schema_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Could not load schema from {self.schema_path}: {e}")
        
        # Return minimal schema if loading fails
        return {
            "nodes": {
                "File": {"attributes": ["name", "file_path"]},
                "Type": {"attributes": ["name", "type_kind", "body"]},
                "Function": {"attributes": ["name", "body", "parameters"]}
            }
        }