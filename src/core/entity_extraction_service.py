"""
Entity Extraction Service for Advanced Graph RAG
Extracts key entities from user queries using schema-aware LLM analysis
"""

import json
import os
import yaml
from typing import Dict, List, Any, Optional
import re

from src.core.paths import NEO4J_CONFIG


class EntityExtractionService:
    """Extract entities from user queries using schema-aware analysis"""
    
    def __init__(self, llm_service, schema_path: str = None, graph_executor=None):
        self.llm_service = llm_service
        self.schema_path = schema_path or self._get_default_schema_path()
        self.schema = self._load_schema()
        self.graph_executor = graph_executor
        self._project_cache = None  # Cache for existing projects
        
        # Common entity patterns for quick extraction
        self.entity_patterns = {
            "files": [
                r'(\w+\.(?:cs|py|js|ts|java|cpp|c|h))',  # File extensions
                r'in\s+([A-Z]\w*\.cs)',  # "in WorkerA.cs"
                r'file\s+([A-Z]\w*\.cs)'  # "file WorkerA.cs"
            ],
            "types": [
                r'\b([A-Z][a-zA-Z0-9]*)\s+class',  # "WorkerA class"
                r'class\s+([A-Z][a-zA-Z0-9]*)',    # "class WorkerA"
                r'interface\s+([A-Z][a-zA-Z0-9]*)',  # "interface IWorker"
                r'\b([A-Z][a-zA-Z0-9]*)\s+(?:implement|inherit)',  # "WorkerA implements"
            ],
            "functions": [
                r'method\s+([a-zA-Z_][a-zA-Z0-9_]*)',  # "method Process"
                r'function\s+([a-zA-Z_][a-zA-Z0-9_]*)',  # "function Process"
                r'([a-zA-Z_][a-zA-Z0-9_]*)\(\)',  # "Process()"
                r'calls?\s+([a-zA-Z_][a-zA-Z0-9_]*)',  # "calls Process"
            ]
        }
        
        # Concept keywords for analysis intent
        self.concept_keywords = {
            "comment lines": ["comment", "comments", "comment lines", "commented"],
            "method calls": ["method calls", "calls", "calling", "invokes", "invocation"],
            "foreach loops": ["foreach", "for each", "loops", "iteration"],
            "inheritance": ["inherits", "inheritance", "extends", "base class"],
            "implementations": ["implements", "implementation", "interface"],
            "variables": ["variables", "fields", "properties", "members"],
            "overall architecture": ["overall architecture", "main components", "architecture", "project structure", "system design", "how components interact"]
        }
    
    async def extract_entities(self, user_query: str) -> Dict[str, Any]:
        """
        Extract key entities and classify intent from user query
        
        Args:
            user_query: User's natural language query
            
        Returns:
            {
                "files": ["WorkerA.cs"],
                "types": ["WorkerA"], 
                "functions": ["Process"],
                "concepts": ["comment lines"],
                "intent": "count_analysis",
                "target_properties": ["body", "symbols_location"],
                "confidence": 0.85,
                "extraction_method": "pattern_matching" | "llm_enhanced"
            }
        """
        # Primary: Pattern-based extraction (fast)
        pattern_entities = await self._extract_with_patterns(user_query)
        
        # Enhance with LLM if pattern matching has low confidence
        if pattern_entities["confidence"] < 0.6:
            try:
                llm_entities = await self._extract_with_llm(user_query, pattern_entities)
                # Merge pattern and LLM results
                final_entities = self._merge_extraction_results(pattern_entities, llm_entities)
                final_entities["extraction_method"] = "llm_enhanced"
            except Exception as e:
                # Fallback to pattern-only results
                final_entities = pattern_entities
                final_entities["extraction_method"] = "pattern_fallback"
                final_entities["llm_error"] = str(e)
        else:
            final_entities = pattern_entities
            final_entities["extraction_method"] = "pattern_matching"
        
        # Determine target properties based on extracted entities and intent
        final_entities["target_properties"] = self._determine_target_properties(final_entities)
        
        return final_entities
    
    async def _extract_with_patterns(self, user_query: str) -> Dict[str, Any]:
        """Extract entities using regex patterns and dynamic classification"""
        query_lower = user_query.lower()
        entities = {
            "files": [],
            "types": [],
            "functions": [],
            "projects": [],  # Add projects field
            "concepts": [],
            "intent": "unknown",
            "confidence": 0.0
        }
        
        # Extract files
        for pattern in self.entity_patterns["files"]:
            matches = re.findall(pattern, user_query, re.IGNORECASE)
            entities["files"].extend(matches)
        
        # Extract types
        for pattern in self.entity_patterns["types"]:
            matches = re.findall(pattern, user_query, re.IGNORECASE)
            entities["types"].extend(matches)
        
        # Extract functions
        for pattern in self.entity_patterns["functions"]:
            matches = re.findall(pattern, user_query, re.IGNORECASE)
            entities["functions"].extend(matches)
        
        # Extract concepts
        for concept, keywords in self.concept_keywords.items():
            if any(keyword in query_lower for keyword in keywords):
                entities["concepts"].append(concept)
        
        # Dynamic project extraction - check for capitalized words that might be project names
        potential_entities = re.findall(r'\b([A-Z][a-zA-Z0-9]*(?:App|Project|System|Service)?)\b', user_query)
        print(f"🔍 DEBUG - Potential entities found: {potential_entities}")
        for entity in potential_entities:
            classification = await self._classify_entity_dynamically(entity, user_query)
            print(f"🔍 DEBUG - Entity '{entity}' classified as: {classification}")
            if classification == "project":
                entities["projects"].append(entity)
                # Remove from types if it was already added there
                if entity in entities["types"]:
                    entities["types"].remove(entity)
            elif classification == "type" and entity not in entities["types"]:
                entities["types"].append(entity)
        
        # Remove duplicates
        for key in ["files", "types", "functions", "projects", "concepts"]:
            entities[key] = list(set(entities[key]))
        
        # Classify intent based on query patterns
        entities["intent"] = self._classify_intent_from_patterns(user_query)
        
        # Calculate confidence based on extractions
        entities["confidence"] = self._calculate_pattern_confidence(entities, user_query)
        
        return entities
    
    def _classify_intent_from_patterns(self, user_query: str) -> str:
        """Classify query intent using pattern matching"""
        query_lower = user_query.lower()
        
        # Architectural patterns (high priority for project-level analysis)
        if any(keyword in query_lower for keyword in ["overall architecture", "main components", "architecture", "project structure", "system design", "how components interact"]):
            return "project_architectural_analysis"
        
        # Quantitative patterns
        elif any(keyword in query_lower for keyword in ["how many", "count", "total", "number of"]):
            return "count_analysis"
        
        # Structural patterns
        elif any(keyword in query_lower for keyword in ["what methods", "which functions", "show me", "list"]):
            return "structural_analysis"
        
        # Relational patterns
        elif any(keyword in query_lower for keyword in ["calls", "depends on", "implements", "inherits"]):
            return "relationship_analysis"
        
        # Locational patterns
        elif any(keyword in query_lower for keyword in ["where is", "find", "locate", "in which file"]):
            return "locational_analysis"
        
        # Comparative patterns
        elif any(keyword in query_lower for keyword in ["difference", "compare", "similar", "versus"]):
            return "comparative_analysis"
        
        # Behavioral patterns
        elif any(keyword in query_lower for keyword in ["how does", "what happens", "process", "workflow"]):
            return "behavioral_analysis"
        
        return "unknown"
    
    def _calculate_pattern_confidence(self, entities: Dict[str, Any], user_query: str) -> float:
        """Calculate confidence score for pattern-based extraction"""
        confidence = 0.0
        
        # Base confidence from extracted entities
        entity_count = sum(len(entities[key]) for key in ["files", "types", "functions", "projects", "concepts"])
        if entity_count > 0:
            confidence += min(entity_count * 0.2, 0.6)  # Max 0.6 from entity count
            
        # Boost confidence for project-level architectural queries
        if entities["intent"] == "project_architectural_analysis" and len(entities["projects"]) > 0:
            confidence += 0.3  # High confidence for project architectural analysis
        
        # Intent classification confidence
        if entities["intent"] != "unknown":
            confidence += 0.3
        
        # Query specificity bonus
        query_words = len(user_query.split())
        if query_words >= 5:  # Detailed queries get bonus
            confidence += 0.1
        
        return min(confidence, 1.0)
    
    async def _extract_with_llm(self, user_query: str, pattern_entities: Dict[str, Any]) -> Dict[str, Any]:
        """Extract entities using LLM with schema context"""
        
        system_prompt = f"""You are an expert at extracting code-related entities from natural language queries.

GRAPH SCHEMA CONTEXT:
{self._format_schema_for_prompt()}

PATTERN EXTRACTION RESULTS (for reference):
{json.dumps(pattern_entities, indent=2)}

Extract entities from this code analysis query: "{user_query}"

Return JSON with:
- files: List of file names mentioned (e.g., ["WorkerA.cs", "Manager.cs"])
- types: List of class/interface/type names (e.g., ["WorkerA", "IWorker"]) 
- functions: List of method/function names (e.g., ["Process", "Run"])
- concepts: List of analysis concepts (e.g., ["comment lines", "method calls", "inheritance"])
- intent: One of [count_analysis, structural_analysis, relationship_analysis, locational_analysis, comparative_analysis, behavioral_analysis]
- confidence: Float 0.0-1.0 indicating extraction confidence
- reasoning: Brief explanation of extraction decisions

Focus on entities that are relevant for graph database queries and code analysis."""

        try:
            response = await self.llm_service.generate_response(system_prompt)
            
            # Parse LLM response
            content = response.content.strip()
            
            # Handle JSON extraction from LLM response
            if content.startswith("```json"):
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    content = content[json_start:].strip()
            elif content.startswith("```"):
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
                else:
                    content = content[json_start:].strip()
            
            llm_entities = json.loads(content)
            
            # Validate LLM response structure
            required_keys = ["files", "types", "functions", "concepts", "intent", "confidence"]
            for key in required_keys:
                if key not in llm_entities:
                    llm_entities[key] = pattern_entities.get(key, [] if key != "confidence" else 0.5)
            
            return llm_entities
            
        except (json.JSONDecodeError, KeyError, Exception) as e:
            # Return enhanced pattern results on LLM failure
            enhanced_pattern = pattern_entities.copy()
            enhanced_pattern["llm_extraction_error"] = str(e)
            enhanced_pattern["confidence"] = max(pattern_entities.get("confidence", 0.3), 0.3)
            return enhanced_pattern
    
    def _merge_extraction_results(self, pattern_entities: Dict[str, Any], llm_entities: Dict[str, Any]) -> Dict[str, Any]:
        """Merge pattern and LLM extraction results intelligently"""
        merged = {
            "files": list(set(pattern_entities.get("files", []) + llm_entities.get("files", []))),
            "types": list(set(pattern_entities.get("types", []) + llm_entities.get("types", []))),
            "functions": list(set(pattern_entities.get("functions", []) + llm_entities.get("functions", []))),
            "projects": list(set(pattern_entities.get("projects", []) + llm_entities.get("projects", []))),
            "concepts": list(set(pattern_entities.get("concepts", []) + llm_entities.get("concepts", []))),
            "intent": llm_entities.get("intent", pattern_entities.get("intent", "unknown")),
            "confidence": max(pattern_entities.get("confidence", 0.0), llm_entities.get("confidence", 0.0)),
            "pattern_entities": pattern_entities,
            "llm_entities": llm_entities
        }
        
        return merged
    
    def _determine_target_properties(self, entities: Dict[str, Any]) -> List[str]:
        """Determine which graph node properties to retrieve based on entities and intent"""
        target_props = ["name", "file_path"]  # Always include basic properties
        
        intent = entities.get("intent", "unknown")
        concepts = entities.get("concepts", [])
        
        # Intent-based property selection
        if intent == "count_analysis":
            target_props.extend(["body", "symbols_location", "start_point", "end_point"])
        elif intent == "structural_analysis":
            target_props.extend(["symbols_location", "fields", "parameters", "return_type", "base_list"])
        elif intent == "relationship_analysis":
            target_props.extend(["base_list", "type_kind", "modifier", "fields"])
        elif intent == "project_architectural_analysis":
            # For project-level analysis, include project metadata and hierarchy properties
            target_props.extend(["project_path", "project_checksum", "version", "type_kind", "body", "base_list"])
        
        # Concept-based property selection
        if "comment lines" in concepts:
            target_props.extend(["body", "symbols_location"])
        if "method calls" in concepts:
            target_props.extend(["body", "parameters", "return_type"])
        if "inheritance" in concepts:
            target_props.extend(["base_list", "type_kind"])
        
        return list(set(target_props))  # Remove duplicates
    
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
                "Type": {"attributes": ["name", "type_kind", "body", "symbols_location"]},
                "Function": {"attributes": ["name", "body", "parameters", "return_type"]}
            }
        }
    
    def _format_schema_for_prompt(self) -> str:
        """Format schema for LLM prompt"""
        if not self.schema:
            return "Schema not available"
        
        schema_text = "Available Node Types:\n"
        for node_type, details in self.schema.get('nodes', {}).items():
            attributes = details.get('attributes', [])
            schema_text += f"- {node_type}: {', '.join(attributes[:8])}...\n"  # Limit attributes for prompt size
        
        return schema_text

    async def _get_existing_projects(self) -> List[str]:
        """Query Neo4j to get list of existing project names"""
        if self._project_cache is not None:
            return self._project_cache
            
        if not self.graph_executor:
            return []
            
        try:
            # Query all projects in the database using single query execution
            query_info = {
                "cypher": "MATCH (p:Project) RETURN p.name as project_name",
                "purpose": "Get existing project names for entity classification",
                "priority": 1.0
            }
            config_path = NEO4J_CONFIG  # Default config path
            result = await self.graph_executor._execute_single_query(query_info, config_path, "project_lookup")
            
            project_names = []
            # The result structure from _execute_single_query includes parsed results
            if result.get("status") == "success" and "results" in result:
                results = result["results"]
                if isinstance(results, list):
                    for record in results:
                        if isinstance(record, dict) and 'project_name' in record and record['project_name']:
                            project_names.append(record['project_name'])
                print(f"🔍 DEBUG - Parsed project names: {project_names}")
            
            # Cache the results
            self._project_cache = project_names
            return project_names
            
        except Exception as e:
            print(f"Warning: Could not query existing projects: {e}")
            import traceback
            traceback.print_exc()
            return []

    async def _classify_entity_dynamically(self, entity_name: str, query_context: str) -> str:
        """Dynamically classify entity by checking what exists in the graph"""
        # Check if it's an existing project
        existing_projects = await self._get_existing_projects()
        print(f"🔍 DEBUG - Existing projects from DB: {existing_projects}")
        if entity_name in existing_projects:
            print(f"🔍 DEBUG - '{entity_name}' found in existing projects!")
            return "project"
        
        # Check if it's a file pattern
        if any(ext in entity_name.lower() for ext in ['.cs', '.py', '.js', '.ts', '.java', '.cpp', '.c', '.h']):
            return "file"
            
        # Check if query context suggests architectural analysis
        architectural_keywords = ["overall architecture", "main components", "architecture", "project structure", "how components interact"]
        if any(keyword in query_context.lower() for keyword in architectural_keywords):
            # For architectural queries, prioritize project-level entities
            if entity_name in existing_projects or any(proj.lower() in entity_name.lower() for proj in existing_projects):
                return "project"
                
        # Default classification logic (existing pattern-based)
        if entity_name[0].isupper() and not '.' in entity_name:
            return "type"
        else:
            return "unknown"