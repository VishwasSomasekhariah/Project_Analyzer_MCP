"""
Research Engine for the Adaptive CPG Agent Workflow.

This module handles the intelligent discovery research process that replaced
the restrictive initial_discovery assumptions. It provides multi-step research
with schema analysis, hypothesis generation, strategy planning, and execution planning.
"""
import json
import yaml
import logging
from typing import List, Dict, Any, Optional
from pydantic import ValidationError

from .parallel_models import (
    SchemaAnalysis, 
    ExplorationHypothesis, 
    QueryStrategy, 
    ExecutionPlan,
    DiscoveryResearch,
    AgentState
)

logger = logging.getLogger(__name__)


class ResearchEngine:
    """
    Intelligent research engine for CPG discovery.
    
    Replaces blind query generation with systematic research that:
    1. Analyzes CPG schema for relevant node types and attributes
    2. Generates hypotheses about where data might be stored
    3. Plans query strategies based on hypotheses
    4. Creates execution plans with termination criteria
    """
    
    def __init__(self, llm_service):
        self.llm_service = llm_service

    async def conduct_discovery_research(self, state: AgentState) -> Dict[str, Any]:
        """
        Simplified research method with Phase 1 (approaches) + audit validation.
        
        Conducts research in 2 phases:
        1. Data Collection Approach Planning - List all ways to collect data from the graph
        2. Schema Correctness Audit - Validate approaches against actual schema (with retry loop)
        """
        logger.info("🔬 Starting SIMPLIFIED RESEARCH WITH AUDIT VALIDATION...")
        logger.info("✅ Schema validation: Complete schema loaded with all node types and attributes")
        
        max_research_cycles = 3  # Maximum attempts with audit feedback
        
        for research_cycle in range(max_research_cycles):
            try:
                # Phase 1: Data Collection Approach Planning
                complete_schema = state.get('schema', {})
                phase_1_feedback = state.get('audit_feedback') if research_cycle > 0 else None
                logger.info(f"🔬 Research Cycle {research_cycle + 1} - Starting Phase 1 (Approach Planning)")
                
                data_collection_approaches = await self._analyze_complete_schema_for_planning(state, complete_schema, phase_1_feedback)
                logger.info(f"📊 Phase 1 completed: identified {len(data_collection_approaches)} data collection approaches")
                
                # Phase 2: Schema Correctness Audit - validate approaches against schema
                logger.info(f"🔍 Research Cycle {research_cycle + 1} - Starting Phase 2 (Schema Audit)")
                audit_result = await self._audit_approaches_against_schema(state, data_collection_approaches, complete_schema)
                
                if audit_result["is_valid"]:
                    logger.info("✅ Schema correctness audit PASSED - approaches are valid")
                    
                    research_results = {
                        "data_collection_approaches": audit_result["validated_approaches"],
                        "total_approaches": len(audit_result["validated_approaches"]),
                        "research_type": "simplified_with_audit",
                        "audit_passed": True,
                        "corrections_applied": audit_result.get("corrections_made", [])
                    }
                    
                    logger.info("✅ SIMPLIFIED RESEARCH WITH AUDIT completed successfully")
                    return research_results
                else:
                    audit_errors = audit_result.get('audit_errors', [])
                    logger.warning(f"⚠️ Schema correctness audit FAILED (cycle {research_cycle + 1}): {audit_errors}")
                    
                    if research_cycle < max_research_cycles - 1:
                        logger.info("🔄 Retrying with audit feedback...")
                        state['audit_feedback'] = audit_errors
                        continue
                    else:
                        logger.error("❌ Max research cycles exceeded - using fallback")
                        break
            
            except Exception as e:
                logger.error(f"❌ Research cycle {research_cycle + 1} failed: {e}")
                if research_cycle < max_research_cycles - 1:
                    continue
                else:
                    break
        
        # Fallback if all attempts failed
        logger.error("❌ All research attempts failed - using fallback")
        return self._generate_fallback_research(state)

    async def _analyze_complete_schema_for_planning(self, state: AgentState, complete_schema: Optional[Dict[str, Any]] = None, validation_feedback: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Phase 1: Data Collection Approach Planning - List all ways to collect data from the graph.
        
        This method analyzes the schema and user query to identify comprehensive
        data collection approaches using O4 mini for better reasoning.
        """
        max_attempts = 3
        current_validation_feedback = validation_feedback
        
        for attempt in range(max_attempts):
            try:
                # Format complete schema with all detailed attributes
                detailed_schema_text = ""
                if complete_schema and 'nodes' in complete_schema:
                    detailed_schema_text = f"""
                **COMPLETE DETAILED CPG SCHEMA**:
                {json.dumps(complete_schema, indent=2)}
                """
                else:
                    # Fallback to basic schema format
                    detailed_schema_text = f"""
                **CPG SCHEMA**:
                **NODE TYPES**:
                {chr(10).join([f"- {node}: {', '.join(attrs.get('attributes', []))}" for node, attrs in state['schema'].get('nodes', {}).items()])}
                **RELATIONSHIPS**:
                {chr(10).join([f"- {rel}: {rel_def.get('from', 'Unknown')} → {rel_def.get('to', 'Unknown')}" for rel, rel_def in state['schema'].get('relationships', {}).items()])}
                """
                # Build validation feedback section
                feedback_section = ""
                if current_validation_feedback:
                    feedback_section = f"""
                **CRITICAL: PREVIOUS VALIDATION ERRORS TO FIX**:
                {chr(10).join([f"- {error}" for error in current_validation_feedback])}
                
                YOU MUST CORRECT THESE ERRORS in your attribute mapping. Use ONLY attributes that exist in the schema.
                """

                prompt = f"""
You are a CPG query planning expert. Given the user query and the complete graph schema, identify all the different ways to collect data from the graph that could help answer the question.

**USER QUERY**: {state['user_query']}
**QUERY INTENT**: {state['intent']}

{feedback_section}
{detailed_schema_text}

**YOUR TASK**: List all possible data collection approaches using the graph schema above. For each approach:

1. **Identify Target Nodes**: Which node types contain the data we need?
2. **Map Useful Attributes**: Which specific attributes from those nodes are relevant?
3. **Plan Navigation**: Which relationships help us find or connect the data?
4. **Consider All Paths**: Think about direct queries, traversals, filtering, etc.

**EXAMPLES OF DATA COLLECTION APPROACHES**:
- Direct node queries (e.g., find all Function nodes with specific names)
- File-based filtering (e.g., filter by file_path to specific files)
- Relationship traversals (e.g., Project→File→Function chains)
- Content searches (e.g., search in 'body', 'documentation', 'value' attributes)
- Location-based queries (e.g., using start_byte, end_byte for ordering)

**OUTPUT REQUIREMENTS**:
- Only use node types, attributes, and relationships that exist in the schema above
- Be comprehensive - list multiple ways to approach the query
- Focus on practical data collection strategies

**RESPONSE FORMAT** (JSON only):
{{
  "approaches": [
    {{
      "approach_name": "Approach 1 Name",
      "description": "What this approach does",
      "target_nodes": ["NodeType1", "NodeType2"],
      "key_attributes": ["attr1", "attr2"],
      "relationships": ["REL1", "REL2"],
      "strategy": "Brief explanation of how to execute this"
    }},
    {{
      "approach_name": "Approach 2 Name",
      "description": "What this approach does",
      "target_nodes": ["NodeType3"],
      "key_attributes": ["attr3"],
      "relationships": ["REL3"],
      "strategy": "Brief explanation of how to execute this"
    }}
  ]
}}
"""
                
                # Use O4 mini for better reasoning quality (temperature not applicable for O4)
                logger.info(f"Schema analysis attempt {attempt + 1} - Using O4 mini, Has validation feedback: {bool(current_validation_feedback)}")
                logger.debug(f"Complete Prompt for schema analysis (attempt {attempt + 1}): \n{prompt}")
                from src.core.llm_service import LLMModel
                result = await self.llm_service.generate_response(prompt, json_mode=True, model=LLMModel.O4_MINI, max_tokens=16000)
                logger.info(f"LLM response for schema analysis (attempt {attempt + 1}): {result.content if result else 'No response'}")
                if not result or result.error:
                    raise Exception(f"LLM service error: {result.error if result else 'No response'}")
                
                # Parse and validate JSON (clean O4 model formatting quirks)
                json_content = result.content.strip()
                
                # Clean O4 model JSON formatting issues
                json_content = self._clean_o4_json_formatting(json_content)
                
                analysis_data = json.loads(json_content)
                
                # Validate required fields for new format
                if "approaches" not in analysis_data:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Schema analysis missing 'approaches' field (attempt {attempt + 1})")
                        continue
                    else:
                        raise Exception(f"Missing 'approaches' field after {max_attempts} attempts")
                
                approaches = analysis_data["approaches"]
                if not approaches or len(approaches) == 0:
                    if attempt < max_attempts - 1:
                        logger.warning(f"⚠️ Schema analysis has empty approaches (attempt {attempt + 1})")
                        continue
                    else:
                        raise Exception(f"No approaches found after {max_attempts} attempts")
                
                # Validate each approach has required fields
                required_approach_fields = ["approach_name", "description", "target_nodes", "key_attributes", "relationships", "strategy"]
                for i, approach in enumerate(approaches):
                    missing_fields = [field for field in required_approach_fields if field not in approach]
                    if missing_fields:
                        if attempt < max_attempts - 1:
                            logger.warning(f"⚠️ Approach {i+1} missing fields (attempt {attempt + 1}): {missing_fields}")
                            break
                        else:
                            raise Exception(f"Approach {i+1} missing fields after {max_attempts} attempts: {missing_fields}")
                else:
                    # All approaches are valid, return the list
                    logger.info(f"✅ Phase 1 completed: found {len(approaches)} data collection approaches")
                    return approaches
                
            except json.JSONDecodeError as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Schema analysis JSON parse error (attempt {attempt + 1}): {e}")
                    continue
                else:
                    raise Exception(f"JSON parsing failed after {max_attempts} attempts: {e}")
            
            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"⚠️ Schema analysis error (attempt {attempt + 1}): {e}")
                    continue
                else:
                    raise Exception(f"Schema analysis failed after {max_attempts} attempts: {e}")
        
        # Should not reach here due to exception handling above
        raise Exception("Schema analysis failed unexpectedly")

    async def _audit_approaches_against_schema(self, state: AgentState, approaches: List[Dict[str, Any]], complete_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Programmatically audit data collection approaches against the actual schema.
        
        Uses direct schema validation like the Pydantic validator - no LLM involved.
        This eliminates false negatives from LLM-based audit.
        """
        logger.info("🔍 Starting programmatic schema validation...")
        
        validation_errors = []
        corrected_approaches = []
        corrections_made = []
        
        # Extract schema facts for validation
        schema_nodes = complete_schema.get('nodes', {})
        schema_relationships = complete_schema.get('relationships', {})
        
        logger.info(f"📊 Schema has {len(schema_nodes)} node types, {len(schema_relationships)} relationship types")
        
        for i, approach in enumerate(approaches):
            approach_name = approach.get('approach_name', f'Approach {i+1}')
            approach_errors = []
            corrections_for_approach = []
            
            # Validate target nodes
            target_nodes = approach.get('target_nodes', [])
            valid_target_nodes = []
            for node_type in target_nodes:
                if node_type in schema_nodes:
                    valid_target_nodes.append(node_type)
                else:
                    approach_errors.append(f"Node type '{node_type}' does not exist in schema")
                    logger.warning(f"⚠️ {approach_name}: Invalid node type '{node_type}'")
            
            # Sophisticated attribute validation and correction
            key_attributes = approach.get('key_attributes', [])
            corrected_attributes = []
            
            if len(valid_target_nodes) == 1:
                # Single target node: validate attributes directly for that node
                single_node = valid_target_nodes[0]
                node_attrs = schema_nodes[single_node].get('attributes', [])
                
                logger.info(f"📝 {approach_name}: Single target node '{single_node}', validating attributes directly")
                
                for attr in key_attributes:
                    # Remove node prefix if present (since we have single target)
                    base_attr = attr.split('.')[-1] if '.' in attr else attr
                    
                    if base_attr in node_attrs:
                        corrected_attributes.append(base_attr)
                    else:
                        approach_errors.append(f"Attribute '{base_attr}' not found in {single_node}")
                        logger.warning(f"⚠️ {approach_name}: Invalid attribute '{base_attr}' for {single_node}")
                
                # If we have invalid attributes, add ALL attributes for this node as correction
                if approach_errors:
                    logger.info(f"🔧 {approach_name}: Adding all attributes for {single_node} due to validation errors")
                    corrected_attributes = node_attrs.copy()  # Use all valid attributes
                    corrections_for_approach.append(f"Replaced invalid attributes with all {single_node} attributes: {node_attrs}")
                    
            elif len(valid_target_nodes) > 1:
                # Multiple target nodes: more complex validation
                logger.info(f"📝 {approach_name}: Multiple target nodes {valid_target_nodes}, checking format")
                
                # Check if attributes already follow node.attribute format
                qualified_format = all('.' in attr for attr in key_attributes)
                
                if not qualified_format:
                    # Step 1: Convert to qualified format (node.attribute for all combinations)
                    logger.info(f"🔧 {approach_name}: Converting to qualified format")
                    expanded_attributes = []
                    for node_type in valid_target_nodes:
                        for attr in key_attributes:
                            base_attr = attr.split('.')[-1] if '.' in attr else attr
                            expanded_attributes.append(f"{node_type}.{base_attr}")
                    
                    logger.info(f"📝 {approach_name}: Expanded to {len(expanded_attributes)} qualified attributes")
                    key_attributes = expanded_attributes
                
                # Step 2: Validate each qualified attribute
                nodes_to_correct = set()  # Track nodes that need full correction
                
                for attr in key_attributes:
                    if '.' not in attr:
                        approach_errors.append(f"Invalid format for multi-node attribute: '{attr}'")
                        continue
                        
                    node_type, base_attr = attr.split('.', 1)
                    
                    if node_type not in valid_target_nodes:
                        approach_errors.append(f"Node '{node_type}' not in target nodes for attribute '{attr}'")
                        continue
                    
                    node_attrs = schema_nodes[node_type].get('attributes', [])
                    if base_attr not in node_attrs:
                        logger.warning(f"⚠️ {approach_name}: Invalid attribute '{attr}' - {node_type} doesn't have '{base_attr}'")
                        nodes_to_correct.add(node_type)
                    else:
                        corrected_attributes.append(attr)
                
                # Step 3: For nodes with invalid attributes, replace with ALL their attributes
                for node_type in nodes_to_correct:
                    # Remove all invalid attributes for this node
                    corrected_attributes = [attr for attr in corrected_attributes if not attr.startswith(f"{node_type}.")]
                    
                    # Add all valid attributes for this node
                    node_attrs = schema_nodes[node_type].get('attributes', [])
                    for attr in node_attrs:
                        corrected_attributes.append(f"{node_type}.{attr}")
                    
                    logger.info(f"🔧 {approach_name}: Replaced all {node_type} attributes with schema attributes: {node_attrs}")
                    corrections_for_approach.append(f"Replaced invalid {node_type} attributes with all schema attributes: {node_attrs}")
                
                # If no valid target nodes, this is handled above in node validation
                if not valid_target_nodes:
                    approach_errors.append(f"No valid target nodes for attribute validation")
            else:
                # No valid target nodes
                approach_errors.append("No valid target nodes for attribute validation")
            
            # Validate relationships
            relationships = approach.get('relationships', [])
            valid_relationships = []
            for rel in relationships:
                if rel in schema_relationships:
                    valid_relationships.append(rel)
                else:
                    approach_errors.append(f"Relationship '{rel}' does not exist in schema")
                    logger.warning(f"⚠️ {approach_name}: Invalid relationship '{rel}'")
            
            # Create corrected approach
            corrected_approach = {
                "approach_name": approach_name,
                "description": approach.get('description', ''),
                "target_nodes": valid_target_nodes,
                "key_attributes": corrected_attributes,  # Use the corrected attributes
                "relationships": valid_relationships,
                "strategy": approach.get('strategy', ''),
                "corrections_applied": corrections_for_approach
            }
            
            # Only add if it has some valid content (nodes and attributes)
            if valid_target_nodes and corrected_attributes:
                corrected_approaches.append(corrected_approach)
                if corrections_for_approach:
                    corrections_made.extend(corrections_for_approach)
            else:
                validation_errors.append(f"{approach_name}: No valid nodes or attributes found")
        
        # Determine if validation passed
        is_valid = len(corrected_approaches) > 0 and len(validation_errors) == 0
        
        if validation_errors:
            logger.warning(f"⚠️ Validation errors found: {validation_errors}")
        
        logger.info(f"✅ Programmatic validation complete: {len(corrected_approaches)} valid approaches")
        
        return {
            "is_valid": is_valid,
            "audit_errors": validation_errors,
            "validated_approaches": corrected_approaches,
            "corrections_made": corrections_made,
            "schema_insights": [
                f"Schema contains {len(schema_nodes)} node types: {list(schema_nodes.keys())}",
                f"Available relationships: {list(schema_relationships.keys())}"
            ]
        }

    def _clean_o4_json_formatting(self, json_content: str) -> str:
        """Clean O4 model JSON formatting quirks"""
        import re
        
        # O4 models sometimes add standalone numbers in JSON arrays  
        cleaned = re.sub(r',\s*\d+\s*,', ',', json_content)
        cleaned = re.sub(r',\s*\d+\s*\]', ']', cleaned)
        
        # Remove stray whitespace and formatting issues
        cleaned = re.sub(r',\s*,', ',', cleaned)  # Remove double commas
        cleaned = re.sub(r'\[\s*,', '[', cleaned)  # Remove leading commas in arrays
        
        return cleaned

    def _format_complete_schema_for_audit(self, schema: dict) -> str:
        """Format the complete schema for audit prompt with clear node structure"""
        try:
            # Extract just the nodes and relationships sections for clarity
            audit_schema = {}
            
            if 'nodes' in schema:
                audit_schema['nodes'] = schema['nodes']
            
            if 'relationships' in schema:
                audit_schema['relationships'] = schema['relationships']
                
            return yaml.dump(audit_schema, default_flow_style=False, indent=2)
        except Exception as e:
            logger.warning(f"⚠️ Schema formatting error: {e}")
            return str(schema)

    def _generate_fallback_research(self, state: AgentState) -> Dict[str, Any]:
        """
        Generate minimal fallback research if the full research process fails.
        Uses actual schema attributes to avoid validation errors.
        """
        logger.warning("⚠️ Using fallback research due to research engine failure")
        
        try:
            # Get actual schema for safe fallback
            schema = state.get('schema', {})
            nodes = schema.get('nodes', {})
            
            # Create basic fallback approaches
            fallback_approaches = [
                {
                    "approach_name": "Basic File Search",
                    "description": "Search for files by name and examine their content",
                    "target_nodes": ["File"],
                    "key_attributes": ["name", "file_path"],
                    "relationships": ["CONTAINS"],
                    "strategy": "Direct file node queries with filtering"
                }
            ]
            
            # Add more approaches based on available schema
            if 'Function' in nodes:
                fallback_approaches.append({
                    "approach_name": "Function Analysis",
                    "description": "Examine function nodes for relevant information",
                    "target_nodes": ["Function"],
                    "key_attributes": ["name", "body"],
                    "relationships": ["DEFINED_IN"],
                    "strategy": "Function node traversal and content analysis"
                })
            
            return {
                "data_collection_approaches": fallback_approaches,
                "total_approaches": len(fallback_approaches),
                "research_type": "fallback",
                "audit_passed": False
            }
        except Exception as e:
            logger.error(f"❌ Fallback research failed: {e}")
            return {
                "data_collection_approaches": [],
                "total_approaches": 0,
                "research_type": "empty_fallback",
                "audit_passed": False
            }
