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

from .models import (
    SchemaAnalysis,
    ExplorationHypothesis,
    QueryStrategy,
    ExecutionPlan,
    DiscoveryResearch,
    AgentState,
    DependencyAnalysis,
    EnhancedPremise,
    EnhancedSubquery,
    ApproachPacket,
    ApproachPacketCollection,
    EmbeddedPremise,
    LogicalQueryDecomposition
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

    def _build_decomposition_prompt(
        self,
        user_query: str,
        intent: Dict[str, Any],
        schema: Dict[str, Any],
        error_feedback: str = ""
    ) -> str:
        """
        Build Phase 0 decomposition prompt with optional error feedback for retries.

        Args:
            user_query: User's question
            intent: Intent analysis result
            schema: CPG schema dictionary (reconciled from Neo4j)
            error_feedback: Error feedback from previous attempt (for retries)

        Returns:
            Complete prompt string
        """
        # Format schema with valid pairs emphasis
        schema_text = ""
        if schema:
            schema_yaml = yaml.dump(schema, default_flow_style=False)
            schema_text = f"""
**RECONCILED SCHEMA** (validated from actual Neo4j data):
```yaml
{schema_yaml}
```

**CRITICAL - Valid Node Pair Rules**:
- Each relationship has a 'valid_pairs' list showing EXACTLY which node pairs can connect
- Example: If REFERENCES valid_pairs shows [{{from: Variable, to: Type}}], then ONLY Variable→Type exists
- If a pair is NOT in the valid_pairs list, that path DOES NOT EXIST in the graph
- Do NOT generate subqueries for non-existent paths
"""
        else:
            schema_text = "**No schema provided**"

        # Extract intent details
        intent_type = intent.get('intent_type', 'lookup')
        intent_confidence = intent.get('confidence', 0.5)
        intent_reasoning = intent.get('reasoning', 'No reasoning provided')
        expected_result_type = intent.get('expected_result_type', 'Unknown')

        # Base prompt - intent-aware and valid pair-respecting
        base_prompt = f"""
SYSTEM PROMPT — CPG QUERY DECOMPOSITION (VALIDATED SCHEMA)

You are a query decomposition specialist for Code Property Graphs (CPG).

Your job is to break down a user's question into targeted retrieval subqueries
based on their intent and a VALIDATED schema from actual Neo4j data.

---

## 🧩 INPUTS

1. **User Question**: {user_query}

2. **Intent**:
{{
  "intent_type": "{intent_type}",
  "confidence": {intent_confidence},
  "reasoning": "{intent_reasoning}",
  "expected_result_type": "{expected_result_type}"
}}

3. **Schema Content** (validated from Neo4j):
{schema_text}

---

## 🧠 YOUR TASK

Generate a focused decomposition with retrieval subqueries that directly address the user's question.

**Key Principles**:

1. **Intent-Driven Scope**

   **Lookup Queries** ("Which classes...", "Where is function X?"):
   - Goal: Find specific entities
   - Subqueries: 2-3 precise lookups
   - Example: [1] Locate entity X, [2] Get related entities, [3] Filter by criteria

   **Architectural Queries** ("How does X work?", "What's the structure?", "Explain the architecture"):
   - Goal: Understand structure, patterns, and relationships
   - Subqueries: 4-6 comprehensive explorations covering:
     - Component structure (types, functions, modules)
     - Relationships and dependencies (calls, references, contains)
     - Patterns and conventions (naming, organization)
     - Key entities and their roles
   - Be thorough - architectural understanding requires multiple perspectives

   **Exploratory Queries** ("What does this project do?", "Summarize the codebase"):
   - Goal: High-level overview
   - Subqueries: 4-5 broad surveys of project structure, entry points, major components

2. **Respect Validated Schema**
   - The reconciled schema shows ACTUAL Neo4j data (not theoretical possibilities)
   - The 'valid_pairs' field lists ONLY valid node pair connections
   - **CRITICAL**: Only use relationship paths that exist in valid_pairs lists
   - If Statement→Type is NOT in REFERENCES valid_pairs, do NOT create subqueries using that path
   - Check valid_pairs BEFORE generating any subquery using a relationship

3. **Identifier Handling**
   - Dotted notation (e.g., `WorkerFactory.CreateWorkers`):
     - Container: WorkerFactory (Type)
     - Contained: CreateWorkers (Function)
     - Relationship: Type -[CONTAINS]-> Function

4. **Logical Form** (optional, for complex queries)
   - Use simple logical notation: `→` implies, `∧` and, `∨` or
   - Keep it concise - focus on subqueries

5. **Subquery Formation**
   - Each subquery should retrieve one meaningful unit of information
   - Use retrieval verbs: *locate, collect, retrieve, count, summarize, explore*
   - Keep subqueries independent (AdaptiveQueryAgent handles refinement)
   - For architectural queries: cover structure, relationships, patterns comprehensively
   - For lookup queries: be precise and targeted

6. **Output Format**

```json
{{
  "intent": "<intent_type>",
  "logical_form": "<simple logical expression or 'N/A'>",
  "premises": [ "<schema assumptions needed for query>" ],
  "subqueries": [ "<retrieval-oriented subquery statements>" ]
}}
```

**IMPORTANT**:
- Output ONLY the JSON object, no additional text
- Lookup queries: 2-3 focused subqueries
- Architectural queries: 4-6 comprehensive subqueries covering multiple perspectives
- Only use paths that exist in the schema's valid_pairs lists
- Do NOT generate atomic micro-steps - each subquery should retrieve meaningful information
"""

        # Prepend error feedback if this is a retry
        if error_feedback:
            return f"{error_feedback}\n\n{base_prompt}"

        return base_prompt

    async def _decompose_user_query(self, state: AgentState, max_attempts: int = 3) -> Dict[str, Any]:
        """
        Phase 0: Decompose user query using logical reasoning with retry logic.

        Uses formal logic to express query structure, treating schema as possibilities
        rather than guarantees. Produces logical form and abstract retrieval subqueries.

        Includes retry mechanism with error feedback to handle JSON parsing failures
        and Pydantic validation errors.

        Args:
            state: Current agent state with user_query, intent, and schema
            max_attempts: Maximum retry attempts (default: 3)

        Returns:
            Dict with intent, logical_form, premises, and subqueries

        Raises:
            ValueError: If decomposition fails after all retry attempts
        """
        logger.info("🔍 Phase 0: Decomposing user query with logical reasoning...")

        user_query = state.get('user_query', '')
        intent = state.get('intent', {})

        # Check if reconciled schema is available (from schema_manager)
        schema_manager = state.get('schema_manager')
        if schema_manager and not schema_manager._loading:
            logger.info("✅ Using reconciled schema from DynamicSchemaManager")
            schema = schema_manager._reconciled_schema
        else:
            logger.info("📄 Using YAML schema (reconciled schema not ready)")
            schema = state.get('schema', {})

        intent_type = intent.get('intent_type', 'lookup')

        last_error = None
        error_feedback = ""

        for attempt in range(max_attempts):
            try:
                # Build prompt with error feedback if retrying
                prompt = self._build_decomposition_prompt(
                    user_query,
                    intent,
                    schema,
                    error_feedback=error_feedback
                )

                # Call LLM
                logger.info(f"  Using GPT-4o for logical query decomposition (attempt {attempt + 1}/{max_attempts})...")
                from src.core.llm_service import LLMModel
                result = await self.llm_service.generate_response(
                    prompt,
                    json_mode=True,
                    model=LLMModel.GPT4O,
                    max_tokens=10000,
                    temperature=0  # Deterministic decomposition
                )

                if not result or result.error:
                    raise Exception(f"LLM service error: {result.error if result else 'No response'}")

                # Parse JSON
                json_content = result.content.strip()
                json_content = self._clean_o4_json_formatting(json_content)
                decomposition_data = json.loads(json_content)

                # Validate using Pydantic model
                from .models import LogicalQueryDecomposition
                validated_decomposition = LogicalQueryDecomposition(**decomposition_data)

                # SUCCESS!
                logger.info(f"✅ Query decomposition complete (attempt {attempt + 1}):")
                logger.info(f"   Intent: {validated_decomposition.intent}")
                logger.info(f"   Logical Form: {validated_decomposition.logical_form}")
                logger.info(f"   Premises: {len(validated_decomposition.premises)}")
                logger.info(f"   Subqueries: {len(validated_decomposition.subqueries)}")

                for i, sq in enumerate(validated_decomposition.subqueries, 1):
                    logger.info(f"     [{i}] {sq}")

                # Return as dict for compatibility
                return validated_decomposition.model_dump()

            except json.JSONDecodeError as e:
                last_error = e
                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: JSON Parsing Error
Error Details: {str(e)}

CRITICAL ISSUE: Your response was not valid JSON.

Common JSON Errors:
- Trailing commas in arrays or objects
- Unescaped quotes inside strings (use \\" for quotes)
- Missing closing braces or brackets
- Comments (JSON does not support comments)
- Single quotes instead of double quotes

REQUIREMENTS:
1. Return ONLY a valid JSON object
2. Use double quotes for all strings and keys
3. No trailing commas
4. All braces and brackets must be properly closed
5. Escape special characters in strings

Try again with STRICTLY VALID JSON.
"""
                logger.warning(f"⚠️  JSON parse error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

            except ValidationError as e:
                last_error = e
                # Extract specific validation errors
                errors = []
                for error in e.errors():
                    field = '.'.join(str(loc) for loc in error['loc']) if error['loc'] else 'unknown'
                    msg = error['msg']
                    error_type = error['type']
                    errors.append(f"  - Field '{field}': {msg} (type: {error_type})")

                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: Pydantic Validation Error
Error Details: Your JSON structure doesn't match the required schema

Validation Errors:
{chr(10).join(errors)}

REQUIRED SCHEMA (ALL fields are mandatory):
{{
  "intent": <string> - The intent type from the classifier (e.g., "lookup", "architectural", "exploratory"),
  "logical_form": <string> - Formal logic expression with symbols like ∃, ∀, ∧, ∨, → (minimum 10 characters),
  "premises": <array of strings> - Logical assumptions and context (minimum 1 premise),
  "subqueries": <array of strings> - Retrieval-oriented queries using verbs: locate, retrieve, count, collect, summarize, compare (minimum 1 subquery)
}}

CRITICAL REQUIREMENTS:
1. ALL four fields must be present
2. "logical_form" must be at least 10 characters long
3. "premises" array must have at least 1 item
4. "subqueries" array must have at least 1 item
5. Each subquery should use retrieval verbs (locate, retrieve, count, collect, summarize, compare)

Try again with ALL required fields properly formatted.
"""
                logger.warning(f"⚠️  Validation error on attempt {attempt + 1}")
                logger.warning(f"   Errors: {errors}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

            except Exception as e:
                last_error = e
                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: Unexpected Error
Error Details: {str(e)}

Something went wrong while processing your response.
Please ensure:
1. You return ONLY valid JSON
2. No extra text before or after the JSON
3. All required fields are present and properly formatted

Try again with a properly formatted JSON response.
"""
                logger.warning(f"⚠️  Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

        # All attempts exhausted - FAIL LOUDLY
        logger.error(f"❌ Query decomposition failed after {max_attempts} attempts")
        logger.error(f"   Last error type: {type(last_error).__name__}")
        logger.error(f"   Last error details: {last_error}")
        logger.error(f"   Query: {user_query}")

        raise ValueError(
            f"Phase 0 decomposition failed after {max_attempts} attempts. "
            f"Cannot proceed with invalid decomposition. "
            f"Last error: {type(last_error).__name__}: {last_error}"
        )

    async def _analyze_dependencies(
        self,
        decomposition: Dict[str, Any],
        max_attempts: int = 3
    ) -> Dict[str, Any]:
        """
        Phase 0 Post-Processing: Analyze dependencies using LLM.

        Takes Phase 0 decomposition output and extracts explicit:
        1. Premise-to-Subquery mappings (which premises validate which subqueries)
        2. Subquery-to-Subquery dependencies (execution order)
        3. Parallel execution groups (which subqueries can run simultaneously)

        Args:
            decomposition: Phase 0 output with logical_form, premises, subqueries
            max_attempts: Maximum retry attempts (default: 3)

        Returns:
            Dict with enhanced premises, subqueries, and execution_groups

        Raises:
            ValueError: If dependency analysis fails after all retry attempts
        """
        logger.info("🔍 Phase 0 Post-Processing: Analyzing dependencies for parallel execution...")

        logical_form = decomposition.get('logical_form', '')
        premises = decomposition.get('premises', [])
        subqueries = decomposition.get('subqueries', [])

        # Build numbered lists for clarity
        premises_text = "\n".join([f"P{i+1}. {p}" for i, p in enumerate(premises)])
        subqueries_text = "\n".join([f"SQ{i+1}. {sq}" for i, sq in enumerate(subqueries)])

        last_error = None
        error_feedback = ""

        for attempt in range(max_attempts):
            try:
                # Build analysis prompt - simplified for synthesis needs
                prompt = f"""
You are analyzing query decomposition dependencies to support result synthesis.

## INPUT

**Logical Form:**
{logical_form}

**Premises (Schema Assumptions):**
{premises_text}

**Subqueries (Retrieval Operations):**
{subqueries_text}

{error_feedback}

## YOUR TASK

Map dependencies between premises and subqueries to help with result synthesis.

1. **Premise-to-Subquery**: Which premises does each subquery rely on?
   - If subquery uses a relationship → map the premise that defines that relationship
   - If subquery filters by attribute → map the premise that validates that attribute

2. **Subquery-to-Subquery**: Which subqueries need results from others for synthesis?
   - Mark as dependent ONLY if synthesis needs to combine their results
   - Example: "Get function F" → "Get calls from F" = dependent (synthesis combines them)
   - Example: "Count classes" + "List functions" = independent (separate facts)

**Note**: Worker pool runs all subqueries in parallel - dependencies only matter for synthesis.

## OUTPUT FORMAT

Return ONLY valid JSON:

{{
  "premises": [
    {{
      "id": "P1",
      "text": "<original premise text>",
      "validates": ["SQ1", "SQ3"]
    }}
  ],
  "subqueries": [
    {{
      "id": "SQ1",
      "text": "<original subquery text>",
      "depends_on_premises": ["P1"],
      "depends_on_subqueries": []
    }}
  ],
  "reasoning": "<brief explanation of dependency structure>"
}}

CRITICAL:
- ALL {len(premises)} premises and {len(subqueries)} subqueries MUST appear in output
- Use IDs: P1, P2, P3... and SQ1, SQ2, SQ3...
- Return ONLY the JSON object, no extra text
"""

                # Call LLM
                logger.info(f"  Using O4 mini for dependency analysis (attempt {attempt + 1}/{max_attempts})...")
                from src.core.llm_service import LLMModel
                result = await self.llm_service.generate_response(
                    prompt,
                    json_mode=True,
                    model=LLMModel.O4_MINI,
                    max_tokens=6000
                )

                if not result or result.error:
                    raise Exception(f"LLM service error: {result.error if result else 'No response'}")

                # Parse JSON
                json_content = result.content.strip()
                json_content = self._clean_o4_json_formatting(json_content)
                dependency_data = json.loads(json_content)

                # Validate using Pydantic model
                validated_analysis = DependencyAnalysis(**dependency_data)

                # SUCCESS!
                logger.info(f"✅ Dependency analysis complete (attempt {attempt + 1}):")
                logger.info(f"   Premises: {len(validated_analysis.premises)}")
                logger.info(f"   Subqueries: {len(validated_analysis.subqueries)} (all execute in parallel via worker pool)")

                # Log dependencies
                deps_count = sum(1 for sq in validated_analysis.subqueries if sq.depends_on_subqueries)
                if deps_count > 0:
                    logger.info(f"   {deps_count} subqueries have dependencies (for synthesis only)")

                # Return as dict for compatibility
                return validated_analysis.model_dump()

            except json.JSONDecodeError as e:
                last_error = e
                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: JSON Parsing Error
Error Details: {str(e)}

Your response was not valid JSON. Common issues:
- Trailing commas
- Unescaped quotes (use \\" inside strings)
- Missing closing braces/brackets
- Comments (not allowed in JSON)

Return ONLY valid JSON with proper formatting.
"""
                logger.warning(f"⚠️  JSON parse error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

            except ValidationError as e:
                last_error = e
                errors = []
                for error in e.errors():
                    field = '.'.join(str(loc) for loc in error['loc']) if error['loc'] else 'unknown'
                    msg = error['msg']
                    errors.append(f"  - {field}: {msg}")

                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: Validation Error
Error Details: Your output doesn't match the required schema

Validation Errors:
{chr(10).join(errors)}

REQUIRED STRUCTURE:
{{
  "premises": [ {{"id": "P1", "text": "...", "validates": ["SQ1", ...]}} ],
  "subqueries": [ {{"id": "SQ1", "text": "...", "depends_on_premises": ["P1"], "depends_on_subqueries": []}} ],
  "execution_groups": [ ["SQ1"], ["SQ2", "SQ3"], ... ],
  "reasoning": "..."
}}

CRITICAL:
- ALL {len(premises)} premises must be included with IDs P1-P{len(premises)}
- ALL {len(subqueries)} subqueries must be included with IDs SQ1-SQ{len(subqueries)}
- execution_groups must include ALL subquery IDs exactly once
- Use original text for each premise/subquery
"""
                logger.warning(f"⚠️  Validation error on attempt {attempt + 1}")
                logger.warning(f"   Errors: {errors}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

            except Exception as e:
                last_error = e
                error_feedback = f"""
❌ **PREVIOUS ATTEMPT FAILED** (Attempt {attempt + 1}/{max_attempts}):
Error Type: Unexpected Error
Error Details: {str(e)}

Ensure:
1. Valid JSON only
2. All required fields present
3. Correct ID formats (P1, P2, ... and SQ1, SQ2, ...)
4. All IDs from input appear in output
"""
                logger.warning(f"⚠️  Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    logger.info(f"   Retrying with error feedback...")
                    continue

        # All attempts exhausted - FAIL LOUDLY
        logger.error(f"❌ Dependency analysis failed after {max_attempts} attempts")
        logger.error(f"   Last error type: {type(last_error).__name__}")
        logger.error(f"   Last error details: {last_error}")

        raise ValueError(
            f"Dependency analysis failed after {max_attempts} attempts. "
            f"Cannot proceed. Last error: {type(last_error).__name__}: {last_error}"
        )

    def _build_approach_packets(
        self,
        decomposition: Dict[str, Any],
        dependency_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Build self-contained approach packets from decomposition and dependency analysis.

        Each packet contains EVERYTHING a mini CoT agent needs to execute independently:
        - Full subquery text
        - Complete logical form for context
        - All relevant premises (embedded, not references)
        - Dependencies (for scheduling)

        Args:
            decomposition: Phase 0 output (logical_form, premises, subqueries)
            dependency_analysis: Dependency analysis output (enhanced premises/subqueries with depends_on_subqueries)

        Returns:
            ApproachPacketCollection as dict with packets (execution_groups removed - worker pool executes all in parallel)
        """
        logger.info("🔨 Building self-contained approach packets...")

        logical_form = decomposition.get('logical_form', '')

        # Create lookup for premises by ID
        premises_by_id = {
            p['id']: p for p in dependency_analysis['premises']
        }

        # Build packets dict (all packets, no grouping)
        packets = {}
        for enhanced_sq in dependency_analysis['subqueries']:
            sq_id = enhanced_sq['id']

            # Get all premises this subquery depends on (embedded, not references)
            embedded_premises = []
            for premise_id in enhanced_sq['depends_on_premises']:
                if premise_id in premises_by_id:
                    premise_data = premises_by_id[premise_id]
                    embedded_premises.append(
                        EmbeddedPremise(
                            id=premise_data['id'],
                            text=premise_data['text']
                        )
                    )

            # Create approach packet (no execution_group - worker pool handles concurrency)
            packet = ApproachPacket(
                id=sq_id,
                text=enhanced_sq['text'],
                logical_form=logical_form,
                original_premises=embedded_premises,  # Store originals
                corrected_premises=[],  # No corrections yet
                active_premises=embedded_premises,  # Initially use originals
                depends_on_subqueries=enhanced_sq['depends_on_subqueries'],  # Keep for synthesis only
                status='pending',
                input_data={},
                result=None,
                error=None,
                sufficiency_status=None,
                sufficiency_reasoning=None,
                execution_time_ms=None,
                attempts=0
            )

            packets[sq_id] = packet

        # Create collection (no execution_groups)
        collection = ApproachPacketCollection(
            packets=packets,
            total_subqueries=len(packets)
        )

        logger.info(f"✅ Built {len(packets)} approach packets (worker pool will execute all in parallel)")

        # Log packet summary with dependencies
        for sq_id, packet in packets.items():
            deps = packet.depends_on_subqueries
            dep_str = f" → depends on: {', '.join(deps)}" if deps else ""
            logger.info(f"   {sq_id}{dep_str}")

        return collection.model_dump()

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
                # Check if reconciled schema is available (from schema_manager)
                schema_manager = state.get('schema_manager')
                if schema_manager and not schema_manager._loading:
                    logger.info("✅ Using reconciled schema from DynamicSchemaManager for approach planning")
                    complete_schema = schema_manager._reconciled_schema
                else:
                    logger.info("📄 Using YAML schema for approach planning (reconciled schema not ready)")
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
                    validated_approaches = audit_result["validated_approaches"]

                    # Phase 2.5: Discover actual paths between target nodes
                    # Skip if reconciled schema already has valid_pairs (paths already discovered by DynamicSchemaManager)
                    has_valid_pairs = False
                    if complete_schema and complete_schema.get('relationships'):
                        for rel_def in complete_schema['relationships'].values():
                            if isinstance(rel_def, dict) and 'valid_pairs' in rel_def:
                                has_valid_pairs = True
                                break

                    if has_valid_pairs:
                        logger.info("✅ Skipping path discovery - reconciled schema already has validated valid_pairs")
                    else:
                        # YAML schema: discover paths from database
                        cypher_server = state.get('cypher_server_service')
                        if cypher_server:
                            try:
                                enriched_approaches = await self._discover_paths_for_approaches(
                                    validated_approaches, cypher_server
                                )
                                validated_approaches = enriched_approaches
                            except Exception as e:
                                logger.error(f"❌ Path discovery failed: {e}")
                                # Continue with non-enriched approaches
                        else:
                            logger.warning("⚠️ No cypher server available for path discovery")

                    research_results = {
                        "data_collection_approaches": validated_approaches,
                        "total_approaches": len(validated_approaches),
                        "research_type": "simplified_with_audit",
                        "audit_passed": True,
                        "corrections_applied": audit_result.get("corrections_made", [])
                    }

                    # Save approach packets to pickle file for validation
                    self._save_approaches_to_pickle(validated_approaches, state)

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

                # CRITICAL FIX: Extract project name for concrete query generation
                metadata = state.get('metadata', {})
                project_name = metadata.get('project_name', 'HelloWorldApp')

                prompt = f"""
You are a CPG query planning expert. Given the user query and the complete graph schema, identify the MOST EFFECTIVE data collection approaches that will yield high-quality, relevant results.

**USER QUERY**: {state['user_query']}
**QUERY INTENT**: {state['intent']}
**PROJECT CONTEXT**: Project Name is '{project_name}' - use this exact value if referencing the project

{feedback_section}
{detailed_schema_text}

**YOUR TASK**: Identify 4-6 HIGH-QUALITY data collection approaches that are most likely to answer the query effectively. For each approach:

1. **Identify Target Nodes**: Which node types contain the MOST RELEVANT data we need?
2. **Map Useful Attributes**: Which specific attributes will give us the BEST information?
3. **Plan Navigation**: Which relationships provide the MOST DIRECT path to the data?
4. **Prioritize Impact**: Focus on approaches that maximize information gain, not just coverage

**QUALITY OVER QUANTITY GUIDELINES**:
- **Prefer SPECIFIC over GENERIC**: Target specific node types and attributes that directly answer the query
- **Balance SIMPLE and COMPLEX**: Include at least one simple/direct approach for diagnostics, but complex multi-hop traversals are valuable for comprehensive analysis
- **Prefer RICH over SPARSE**: Choose attributes that contain substantial information (e.g., 'body', 'documentation' over just 'name')
- **Avoid REDUNDANCY**: Don't create multiple similar approaches - consolidate complementary strategies
- **Focus on PRECISION**: Each approach should target a distinct aspect of the query, not variations of the same thing

**EXAMPLES OF HIGH-QUALITY APPROACHES**:
✅ GOOD: "Search function bodies for specific keywords" + "Traverse inheritance relationships for type structure"
❌ BAD: "Search by name" + "Search by partial name" + "Search by name pattern" (redundant variations)

**OUTPUT REQUIREMENTS**:
- Only use node types, attributes, and relationships that exist in the schema above
- Limit to 4-6 DISTINCT, HIGH-IMPACT approaches (not exhaustive list)
- Each approach must target a meaningfully different data source or collection strategy
- CRITICAL: If mentioning project filtering in strategy, use the actual project name '{project_name}' - NO $project_name placeholders
- CRITICAL: Neo4j properties are FLAT - strategies should NOT suggest nested property access like `p.property.subproperty`
  - ❌ WRONG: `p.config_metadata.workers` (nested access not supported in Neo4j)
  - ✅ CORRECT: Return flat properties like `p.config_metadata` OR use schema-validated relationships
  - DO NOT suggest non-existent relationships - use ONLY relationships from the schema above

**RESPONSE FORMAT** (JSON only):
{{
  "approaches": [
    {{
      "approach_name": "Approach 1 Name",
      "description": "What this approach does",
      "target_nodes": ["NodeType1", "NodeType2"],
      "key_attributes": ["attr1", "attr2"],
      "relationships": ["REL1", "REL2"],
      "strategy": "Brief explanation of how to execute this (use '{project_name}' if referencing the project)"
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
        Programmatically audit data collection approaches against the REAL database schema.

        Uses reconciled schema if available (has valid_pairs), otherwise fetches from APOC.
        This ensures validation against what actually exists in the graph.
        """
        logger.info("🔍 Starting schema validation...")

        # Check if complete_schema is reconciled schema (has valid_pairs field)
        has_valid_pairs = False
        if complete_schema and complete_schema.get('relationships'):
            for rel_def in complete_schema['relationships'].values():
                if isinstance(rel_def, dict) and 'valid_pairs' in rel_def:
                    has_valid_pairs = True
                    break

        if has_valid_pairs:
            # Reconciled schema available - use it directly (no need for APOC call)
            logger.info("✅ Using reconciled schema from DynamicSchemaManager for validation")
            return await self._audit_with_static_schema(state, approaches, complete_schema)

        # YAML schema - fetch real schema from database using APOC
        logger.info("📡 Fetching schema from APOC for validation...")
        cypher_server = state.get('cypher_server_service')
        if not cypher_server:
            logger.warning("⚠️ No cypher server available - falling back to static schema")
            return await self._audit_with_static_schema(state, approaches, complete_schema)

        try:
            logger.info("📡 Fetching real schema using apoc.meta.schema()...")
            result = await cypher_server.execute_query(
                'CALL apoc.meta.schema() YIELD value RETURN value'
            )

            if not result.get('data') or not result['data']:
                logger.warning("⚠️ APOC schema query returned no data - falling back to static schema")
                return await self._audit_with_static_schema(state, approaches, complete_schema)

            real_schema = result['data'][0]['value']
            logger.info(f"✅ Fetched real schema: {len(real_schema)} node types discovered")

            # Convert APOC schema format to our validation format
            schema_nodes = self._convert_apoc_to_node_schema(real_schema)
            schema_relationships = self._convert_apoc_to_rel_schema(real_schema)

        except Exception as e:
            logger.error(f"❌ Failed to fetch APOC schema: {e}")
            logger.warning("⚠️ Falling back to static schema")
            return await self._audit_with_static_schema(state, approaches, complete_schema)

        # Use shared validation logic with APOC-derived schema
        return self._validate_approaches_with_schema(
            approaches, schema_nodes, schema_relationships, source="APOC"
        )

    def _validate_approaches_with_schema(
        self,
        approaches: List[Dict[str, Any]],
        schema_nodes: Dict[str, Dict[str, Any]],
        schema_relationships: Dict[str, Dict[str, Any]],
        source: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Common validation logic used by both APOC-based and static schema audits.

        Args:
            approaches: List of approach packets to validate
            schema_nodes: Node schema (format: {NodeType: {attributes: [...]}} )
            schema_relationships: Relationship schema
            source: Source of schema ("APOC" or "static") for logging

        Returns:
            Validation result dict
        """
        validation_errors = []
        corrected_approaches = []
        corrections_made = []

        logger.info(f"📊 Validating with {source} schema: {len(schema_nodes)} node types, {len(schema_relationships)} relationship types")
        
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
                # Support both YAML (attributes) and reconciled (properties) schema formats
                node_attrs = schema_nodes[single_node].get('attributes') or schema_nodes[single_node].get('properties', [])

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

                    # Support both YAML (attributes) and reconciled (properties) schema formats
                    node_attrs = schema_nodes[node_type].get('attributes') or schema_nodes[node_type].get('properties', [])
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
                    # Support both YAML (attributes) and reconciled (properties) schema formats
                    node_attrs = schema_nodes[node_type].get('attributes') or schema_nodes[node_type].get('properties', [])
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

    def _save_approaches_to_pickle(self, approaches: List[Dict[str, Any]], state: AgentState) -> None:
        """
        Save validated approach packets to pickle file for inspection and validation.

        Args:
            approaches: List of validated approach packets
            state: Current workflow state
        """
        import pickle
        from datetime import datetime
        import os

        try:
            # Create output directory if needed
            output_dir = "approach_packets"
            os.makedirs(output_dir, exist_ok=True)

            # Build filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            user_query = state.get('user_query', 'unknown_query')
            # Sanitize query for filename
            safe_query = "".join(c if c.isalnum() or c in (' ', '_') else '_' for c in user_query)
            safe_query = safe_query[:50]  # Limit length
            filename = f"{output_dir}/approaches_{safe_query}_{timestamp}.pkl"

            # Prepare data for pickle
            output_data = {
                "timestamp": timestamp,
                "user_query": user_query,
                "project_name": state.get('metadata', {}).get('project_name', 'Unknown'),
                "total_approaches": len(approaches),
                "approaches": approaches
            }

            # Write to pickle file
            with open(filename, 'wb') as f:
                pickle.dump(output_data, f)

            logger.info(f"💾 Saved {len(approaches)} approach packets to {filename}")

        except Exception as e:
            logger.warning(f"⚠️ Failed to save approach packets to pickle: {e}")

    async def _discover_paths_for_approaches(
        self,
        approaches: List[Dict[str, Any]],
        cypher_server,
        max_depth: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Discover actual paths between target nodes using apoc.path.expandConfig().

        For each approach, finds all real path patterns that exist in the database
        between the target nodes. The relationship filter is dynamically built based
        on the approach's relationships to avoid confusion.

        Args:
            approaches: List of validated approach packets
            cypher_server: Cypher server instance
            max_depth: Maximum path depth to explore (default: 10, increased for future CPG depth)

        Returns:
            Approaches enriched with discovered path patterns
        """
        logger.info("🔍 Discovering paths using apoc.path.expandConfig()...")

        # Fetch all available relationship types from database once
        try:
            rel_types_result = await cypher_server.execute_query(
                'CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType'
            )
            available_relationships = [
                row['relationshipType'] for row in rel_types_result.get('data', [])
            ]
            default_filter = '|'.join([f"{rel}>" for rel in available_relationships])
            logger.info(f"  Discovered {len(available_relationships)} relationship types from database")
        except Exception as e:
            logger.warning(f"  Failed to fetch relationship types from database: {e}")
            # Only if query fails, use minimal fallback
            default_filter = 'CONTAINS>'
            logger.warning(f"  Using minimal fallback filter: {default_filter}")

        enriched_approaches = []

        for approach in approaches:
            target_nodes = approach.get('target_nodes', [])

            if len(target_nodes) <= 1:
                # Single node or no nodes - no paths needed
                enriched_approaches.append(approach)
                continue

            logger.info(f"  Discovering paths for '{approach['approach_name']}' with nodes: {target_nodes}")

            # Build WHERE clause for target nodes
            node_conditions = " OR ".join([f"start:{node}" for node in target_nodes])

            # Build dynamic relationship filter based on approach's relationships
            relationships = approach.get('relationships', [])
            if relationships:
                # Create filter with all specified relationships
                # Format: 'CONTAINS>|CALLS>|REFERENCES>' etc.
                relationship_filter = '|'.join([f"{rel}>" for rel in relationships])
            else:
                # Use all available relationships discovered from database
                relationship_filter = default_filter

            logger.info(f"    Using relationship filter: {relationship_filter}, max depth: {max_depth}")

            # Query to discover all paths using apoc.path.expandConfig
            path_query = f"""
            MATCH (start)
            WHERE {node_conditions}
            CALL apoc.path.expandConfig(start, {{
                relationshipFilter: '{relationship_filter}',
                maxLevel: {max_depth},
                uniqueness: 'NODE_GLOBAL',
                limit: 5000
            }})
            YIELD path
            WHERE length(path) > 0
            RETURN DISTINCT
                labels(nodes(path)[0])[0] AS start_node,
                labels(last(nodes(path)))[0] AS end_node,
                [node in nodes(path) | labels(node)[0]] AS pattern,
                count(*) AS occurrences,
                length(path) AS depth
            ORDER BY occurrences DESC
            LIMIT 50
            """

            try:
                result = await cypher_server.execute_query(path_query)

                if result.get('data'):
                    # Parse path patterns
                    discovered_paths = []
                    for row in result['data']:
                        start_node = row.get('start_node')
                        end_node = row.get('end_node')
                        pattern = row.get('pattern', [])
                        occurrences = row.get('occurrences', 0)
                        depth = row.get('depth', 0)

                        # Only include paths that connect nodes in our target_nodes list
                        if start_node in target_nodes and end_node in target_nodes:
                            discovered_paths.append({
                                'pattern': pattern,
                                'start_node': start_node,
                                'end_node': end_node,
                                'occurrences': occurrences,
                                'depth': depth
                            })

                    logger.info(f"    Found {len(discovered_paths)} relevant path patterns")

                    # Add discovered paths to approach
                    approach['discovered_paths'] = discovered_paths
                else:
                    logger.warning(f"    No paths discovered for {approach['approach_name']}")
                    approach['discovered_paths'] = []

            except Exception as e:
                logger.error(f"    Path discovery failed for {approach['approach_name']}: {e}")
                approach['discovered_paths'] = []

            enriched_approaches.append(approach)

        logger.info(f"✅ Path discovery complete for {len(enriched_approaches)} approaches")
        return enriched_approaches

    def _convert_apoc_to_node_schema(self, apoc_schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Convert APOC schema format to our node schema format.

        APOC format: {NodeType: {properties: {prop_name: {type, indexed, ...}}, ...}}
        Our format: {NodeType: {attributes: [prop1, prop2, ...]}}
        """
        node_schema = {}

        for node_type, node_data in apoc_schema.items():
            if node_data.get('type') == 'node':
                properties = node_data.get('properties', {})
                node_schema[node_type] = {
                    'attributes': list(properties.keys())
                }

        return node_schema

    def _convert_apoc_to_rel_schema(self, apoc_schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Convert APOC schema format to our relationship schema format.

        APOC format: {NodeType: {relationships: {REL_TYPE: {labels: [target_types], direction, ...}}}}
        Our format: {REL_TYPE: {from: source, to: [targets]}}
        """
        rel_schema = {}

        for node_type, node_data in apoc_schema.items():
            if node_data.get('type') == 'node':
                relationships = node_data.get('relationships', {})

                for rel_type, rel_data in relationships.items():
                    target_labels = rel_data.get('labels', [])
                    direction = rel_data.get('direction', 'out')

                    if rel_type not in rel_schema:
                        rel_schema[rel_type] = {
                            'from': node_type if direction == 'out' else target_labels,
                            'to': target_labels if direction == 'out' else node_type
                        }

        return rel_schema

    async def _audit_with_static_schema(self, state: AgentState, approaches: List[Dict[str, Any]], complete_schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Fallback audit using static schema file (original validation method).

        This is used when APOC schema fetching fails.
        """
        logger.info("🔄 Using static schema for validation...")

        # Extract schema facts for validation
        schema_nodes = complete_schema.get('nodes', {})
        schema_relationships = complete_schema.get('relationships', {})

        # Use shared validation logic with static schema
        return self._validate_approaches_with_schema(
            approaches, schema_nodes, schema_relationships, source="static"
        )
