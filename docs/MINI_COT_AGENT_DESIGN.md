# Mini CoT Agent for Cypher Query Generation - Design

## Overview

Replace the current complex retry/diagnostic logic with a **lightweight CoT agent per approach** that autonomously generates and refines Cypher queries.

---

## Current Architecture (Complex)

```
execute_batch_approaches()
  ├─> _run_approach_with_workflow_nodes()
       ├─> think() - analyze approach
       ├─> generate_query() - generate 1-8 queries at once
       │    └─> if syntax error: retry with feedback (3 attempts)
       ├─> execute_queries() - execute all queries
       │    ├─> for each query:
       │    │    ├─> if syntax error: add to failed list
       │    │    └─> if empty results: add to failed list
       │    └─> _run_diagnostics_on_failed_queries() (5 diagnostics per failure!)
       │         ├─> check_node_exists
       │         ├─> check_relationships
       │         ├─> sample_paths
       │         ├─> validate_attributes
       │         └─> suggest_corrections
       └─> rethink() - assess sufficiency
```

**Problems**:
- ❌ Generates all queries upfront (can't adapt based on results)
- ❌ Expensive diagnostics run on every failure (5 per query!)
- ❌ No learning from previous query results
- ❌ Complex retry logic scattered across nodes

---

## New Architecture (Simple)

```
execute_batch_approaches()
  ├─> _run_approach_with_mini_cot_agent()
       └─> MiniCoTAgent(approach, schema, cypher_server)
            │
            ├─> LOOP (max 3-5 iterations):
            │    │
            │    ├─> cot_think_step()
            │    │    - Review approach goal
            │    │    - Analyze previous results (if any)
            │    │    - Decide: generate new query OR done?
            │    │
            │    ├─> cot_generate_query_step()
            │    │    - Step 1: Identify entities needed
            │    │    - Step 2: Trace schema path (using examples)
            │    │    - Step 3: Apply filters
            │    │    - Step 4: Structure RETURN
            │    │    - Step 5: Generate Cypher
            │    │
            │    ├─> execute_query()
            │    │    - Send query to cypher_server
            │    │    - Get results OR error
            │    │
            │    ├─> cot_analyze_results_step()
            │    │    - If error: understand what went wrong
            │    │    - If empty: understand why (no diagnostic queries!)
            │    │    - If success: extract key findings
            │    │    - Decide: need more queries OR sufficient?
            │    │
            │    └─> if sufficient: BREAK
            │
            └─> return aggregated_results
```

**Benefits**:
- ✅ Adaptive - learns from each query result
- ✅ No expensive diagnostics - LLM reasons about failures
- ✅ Simpler code - single loop instead of nested retries
- ✅ Better queries - informed by previous results

---

## Mini CoT Agent State

```python
@dataclass
class MiniCoTAgentState:
    """State for a single approach's CoT agent."""

    # Approach context (immutable)
    approach_index: int
    approach_details: Dict[str, Any]
    user_query: str
    schema: Dict[str, Any]
    project_name: str

    # Execution state (mutable)
    iteration: int = 0
    max_iterations: int = 5

    # Query history
    queries_executed: List[Dict[str, Any]] = field(default_factory=list)
    # Each query: {query: str, results: List, error: str, reasoning: str}

    # Accumulated findings
    discovered_data: List[Dict[str, Any]] = field(default_factory=list)

    # Decision state
    is_sufficient: bool = False
    sufficiency_reason: str = ""

    # Token tracking
    tokens_used: int = 0
```

---

## Mini CoT Agent Implementation

### File: `src/core/workflow/mini_cot_agent.py`

```python
class MiniCoTAgent:
    """
    Lightweight CoT agent for a single approach.

    Generates and refines Cypher queries iteratively based on results.
    """

    def __init__(
        self,
        approach_index: int,
        approach_details: Dict[str, Any],
        user_query: str,
        schema: Dict[str, Any],
        project_name: str,
        llm_service: Any,
        cypher_server: Any,
        max_iterations: int = 5
    ):
        self.state = MiniCoTAgentState(
            approach_index=approach_index,
            approach_details=approach_details,
            user_query=user_query,
            schema=schema,
            project_name=project_name,
            max_iterations=max_iterations
        )
        self.llm_service = llm_service
        self.cypher_server = cypher_server

    async def run(self) -> Dict[str, Any]:
        """
        Main execution loop - iteratively generate and refine queries.
        """
        logger.info(f"🤖 Mini CoT Agent starting for approach {self.state.approach_index}")

        for iteration in range(self.state.max_iterations):
            self.state.iteration = iteration + 1
            logger.info(f"  🔄 Iteration {self.state.iteration}/{self.state.max_iterations}")

            # Step 1: Think - should we generate another query?
            should_continue = await self._cot_think_step()
            if not should_continue:
                logger.info(f"  ✅ Agent decided to stop: {self.state.sufficiency_reason}")
                break

            # Step 2: Generate query using CoT reasoning
            query_result = await self._cot_generate_query_step()
            if not query_result:
                logger.warning(f"  ⚠️ Failed to generate query, stopping")
                break

            # Step 3: Execute query
            execution_result = await self._execute_query(query_result['cypher_query'])

            # Step 4: Analyze results and update state
            analysis_result = await self._cot_analyze_results_step(query_result, execution_result)

            # Record this query execution with full traceability
            self.state.queries_executed.append({
                'iteration': self.state.iteration,
                'query': query_result['cypher_query'],
                'reasoning': {
                    'cot_reasoning': query_result.get('cot_reasoning', {}),
                    'query_purpose': query_result.get('query_purpose', 'Unknown')
                },
                'results': execution_result.get('results', []),
                'error': execution_result.get('error'),
                'result_count': len(execution_result.get('results', [])),
                # Store analysis for reasoning trail
                'analysis': {
                    'analysis': analysis_result.get('analysis', ''),
                    'key_findings': analysis_result.get('key_findings', []),
                    'recommendation': analysis_result.get('recommendation', ''),
                    'next_query_hint': analysis_result.get('next_query_hint', '')
                }
            })

        # Return aggregated results
        return self._build_final_result()

    async def _cot_think_step(self) -> bool:
        """
        CoT Step: Decide if we should generate another query.

        Returns: True if should continue, False if sufficient
        """
        # Build context from previous queries
        previous_context = self._format_previous_queries()

        prompt = f"""You are analyzing an approach for code property graph querying.

**USER QUERY**: {self.state.user_query}

**APPROACH GOAL**: {self.state.approach_details.get('description', 'Unknown')}
- Strategy: {self.state.approach_details.get('strategy', 'general')}
- Target: {self.state.approach_details.get('target_nodes', [])}

**ITERATION**: {self.state.iteration}/{self.state.max_iterations}

**PREVIOUS QUERIES** ({len(self.state.queries_executed)} executed):
{previous_context}

**DISCOVERED DATA SO FAR**: {len(self.state.discovered_data)} records

**DECISION**: Should we generate another Cypher query for this approach?

Consider:
1. Have we gathered enough data to address this approach's goal?
2. Are previous queries failing (errors or empty results)?
3. Is there a different angle we should try?
4. Have we exhausted reasonable query options?

Respond in JSON:
{{
    "should_continue": true/false,
    "reasoning": "Why continue or stop",
    "next_query_focus": "If continuing, what should next query focus on?"
}}
"""

        result = await self.llm_service.generate_with_pydantic(
            system_prompt="You are a query planning expert.",
            user_prompt=prompt,
            response_model=CoTThinkDecision,
            model_name="gpt-4o-mini",  # Fast model for decision
            call_type="cot_think",
            approach_index=self.state.approach_index
        )

        self.state.is_sufficient = not result.should_continue
        self.state.sufficiency_reason = result.reasoning

        return result.should_continue

    async def _cot_generate_query_step(self) -> Optional[Dict[str, Any]]:
        """
        CoT Step: Generate a Cypher query with step-by-step reasoning.

        Uses schema examples to guide correct relationship paths.
        """
        # Build schema examples showing correct paths
        schema_examples = self._build_schema_path_examples()

        # Get context from previous queries
        previous_context = self._format_previous_queries()

        prompt = f"""You are a Cypher query expert. Use step-by-step reasoning to generate a correct query.

**USER QUERY**: {self.state.user_query}

**APPROACH**: {self.state.approach_details.get('approach_name', 'Unknown')}
- Goal: {self.state.approach_details.get('description', '')}
- Strategy: {self.state.approach_details.get('strategy', 'general')}
- Target Nodes: {self.state.approach_details.get('target_nodes', [])}
- Relationships: {self.state.approach_details.get('relationships', [])}

**PROJECT**: '{self.state.project_name}' (use this exact value, NOT $project_name)

**SCHEMA RELATIONSHIP EXAMPLES**:
{schema_examples}

**PREVIOUS QUERIES** (learn from these):
{previous_context}

**CHAIN-OF-THOUGHT REASONING** (Follow these 5 steps):

Step 1 - IDENTIFY: What entities do I need?
- What node types from the approach should I retrieve?
- Example: "I need Type nodes representing classes"

Step 2 - TRACE PATH: What's the correct relationship path in the schema?
- Look at the schema examples above
- Start from Project node: Project {{name: '{self.state.project_name}'}}
- Example: "To reach Type → Project-[:CONTAINS]->File-[:CONTAINS]->Type"
- ⚠️ DO NOT skip intermediate nodes (e.g., File)

Step 3 - FILTER: What properties should I filter on?
- Use approach's target attributes: {self.state.approach_details.get('key_attributes', [])}
- Example: "Filter where type_kind='class'"

Step 4 - RETURN: What should the query return?
- Include relevant properties from target nodes
- Include context (file paths, names)
- ⚠️ NO nested properties (e.g., node.prop.subprop is INVALID)

Step 5 - OPTIMIZE: Final touches
- Add LIMIT clause (50-100 results)
- Order by relevance if helpful

**NOW GENERATE**:

Respond in JSON:
{{
    "cot_reasoning": {{
        "step1_identify": "entities needed...",
        "step2_trace_path": "relationship path...",
        "step3_filter": "filters to apply...",
        "step4_return": "what to return...",
        "step5_optimize": "optimizations..."
    }},
    "cypher_query": "MATCH ... RETURN ... LIMIT ...",
    "query_purpose": "What this query will discover"
}}
"""

        result = await self.llm_service.generate_with_pydantic(
            system_prompt="You are a Cypher query expert using Chain-of-Thought reasoning.",
            user_prompt=prompt,
            response_model=CoTQueryGeneration,
            model_name="gpt-4o",  # Stronger model for query generation
            call_type="cot_generate",
            approach_index=self.state.approach_index
        )

        return result.dict()

    async def _execute_query(self, cypher_query: str) -> Dict[str, Any]:
        """Execute query via cypher server."""
        try:
            results = await self.cypher_server.execute_query(cypher_query)
            return {
                'results': results,
                'error': None,
                'success': True
            }
        except Exception as e:
            return {
                'results': [],
                'error': str(e),
                'success': False
            }

    async def _cot_analyze_results_step(
        self,
        query_result: Dict[str, Any],
        execution_result: Dict[str, Any]
    ):
        """
        CoT Step: Analyze query results and extract insights.

        For empty results, run focused diagnostics to understand why.
        """
        results = execution_result.get('results', [])
        error = execution_result.get('error')

        # For syntax errors, LLM can reason about the fix (no diagnostics needed)
        # For empty results, run diagnostics to understand the data landscape
        diagnostic_info = None
        if not error and len(results) == 0:
            diagnostic_info = await self._run_targeted_diagnostics(query_result['cypher_query'])

        prompt = f"""You are analyzing the results of a Cypher query execution.

**QUERY EXECUTED**:
{query_result['cypher_query']}

**QUERY PURPOSE**: {query_result.get('query_purpose', 'Unknown')}

**EXECUTION RESULT**:
- Success: {execution_result['success']}
- Result Count: {len(results)}
- Error: {error if error else 'None'}

**RESULTS** (first 5):
{json.dumps(results[:5], indent=2, default=str) if results else 'Empty'}

{'**DIAGNOSTIC INFORMATION** (why query returned empty):' if diagnostic_info else ''}
{json.dumps(diagnostic_info, indent=2, default=str) if diagnostic_info else ''}

**ANALYZE**:

If ERROR occurred:
- What went wrong? (syntax, schema mismatch, invalid path?)
- What would fix it? (different relationship, different node type?)

If EMPTY results:
- Look at diagnostic info - do the nodes exist in the database?
- Are the relationships correct according to diagnostics?
- Is the path too specific? Should we try a broader query?
- Are the filters too strict?

If SUCCESS with results:
- What did we discover that's relevant to the approach goal?
- Do we need more queries or is this sufficient?

Respond in JSON:
{{
    "analysis": "What happened and why",
    "key_findings": ["finding 1", "finding 2", ...],
    "recommendation": "Continue with different query / Sufficient data / Try alternative",
    "next_query_hint": "If continuing, what should the next query do differently?"
}}
"""

        result = await self.llm_service.generate_with_pydantic(
            system_prompt="You are a query analysis expert.",
            user_prompt=prompt,
            response_model=CoTAnalysisResult,
            model_name="gpt-4o-mini",
            call_type="cot_analyze",
            approach_index=self.state.approach_index
        )

        # Update state with findings
        if results:
            self.state.discovered_data.extend(results)

        # Store the hint for next iteration
        self.state.last_analysis_hint = result.get('next_query_hint', '')

        logger.info(f"  📊 Analysis: {result.analysis}")
        logger.info(f"  💡 Findings: {result.key_findings}")
        logger.info(f"  📌 Recommendation: {result.recommendation}")
        if result.get('next_query_hint'):
            logger.info(f"  💡 Next Query Hint: {result.next_query_hint}")

        # Return analysis result for storage in query record
        return result.dict()

    async def _run_targeted_diagnostics(self, failed_query: str) -> Dict[str, Any]:
        """
        Run 1-2 focused diagnostics on empty results to understand the data landscape.

        These are CHEAP queries that return minimal metadata, not full results.
        Purpose: Help LLM understand what data exists so it can craft better queries.
        """
        diagnostics = {}

        try:
            # Diagnostic 1: Check if target nodes exist (just COUNT, not full data)
            # Extract target node type from query (simple regex)
            import re
            match = re.search(r'MATCH.*?\((\w+):(\w+)', failed_query)
            if match:
                var_name, node_type = match.groups()

                # Get count of nodes of this type in the project
                count_query = f"""
                MATCH (p:Project {{name: '{self.state.project_name}'}})
                OPTIONAL MATCH (p)-[:CONTAINS*1..2]->(n:{node_type})
                RETURN
                    COUNT(DISTINCT n) as node_count,
                    COLLECT(DISTINCT n.name)[..5] as sample_names,
                    COLLECT(DISTINCT n.type_kind)[..5] as sample_type_kinds
                """

                count_result = await self.cypher_server.execute_query(count_query)
                diagnostics['target_node_availability'] = {
                    'node_type': node_type,
                    'count': count_result[0]['node_count'] if count_result else 0,
                    'sample_names': count_result[0]['sample_names'] if count_result else [],
                    'sample_type_kinds': count_result[0]['sample_type_kinds'] if count_result else []
                }

            # Diagnostic 2: Check relationship path validity (for multi-hop queries)
            # Only if query has relationship patterns
            if '-[' in failed_query:
                # Extract the full path pattern
                path_match = re.search(r'MATCH\s+(.*?)(?:WHERE|RETURN)', failed_query, re.IGNORECASE | re.DOTALL)
                if path_match:
                    path_pattern = path_match.group(1).strip()

                    # Check if intermediate nodes exist
                    # Example: For Project-[:CONTAINS]->File-[:CONTAINS]->Type
                    # Check: Do Files exist? Do Types exist?
                    intermediate_query = f"""
                    MATCH (p:Project {{name: '{self.state.project_name}'}})
                    OPTIONAL MATCH (p)-[:CONTAINS]->(f:File)
                    OPTIONAL MATCH (f)-[:CONTAINS]->(t:Type)
                    RETURN
                        COUNT(DISTINCT f) as file_count,
                        COUNT(DISTINCT t) as type_count,
                        COLLECT(DISTINCT f.name)[..3] as sample_files,
                        COLLECT(DISTINCT t.name)[..3] as sample_types
                    """

                    path_result = await self.cypher_server.execute_query(intermediate_query)
                    diagnostics['relationship_path_check'] = {
                        'pattern_attempted': path_pattern[:100],
                        'file_count': path_result[0]['file_count'] if path_result else 0,
                        'type_count': path_result[0]['type_count'] if path_result else 0,
                        'sample_files': path_result[0]['sample_files'] if path_result else [],
                        'sample_types': path_result[0]['sample_types'] if path_result else []
                    }

        except Exception as e:
            logger.warning(f"⚠️ Diagnostic queries failed: {e}")
            diagnostics['error'] = str(e)

        return diagnostics

    def _build_schema_path_examples(self) -> str:
        """
        Build concrete examples of valid relationship paths from schema.
        """
        return f"""
**Common Valid Paths in This Schema**:

1. **Project → File**:
   MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS]->(f:File)

2. **Project → File → Type**:
   MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type)

3. **Project → File → Function**:
   MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function)

4. **Type → Method (CONTAINS)**:
   MATCH (t:Type)-[:CONTAINS]->(m:Function WHERE m.type_kind = 'method')

5. **Type → Type (Inheritance)**:
   MATCH (child:Type)-[:INHERITS_FROM|IMPLEMENTS]->(parent:Type)

6. **Function → Type (Usage)**:
   MATCH (fn:Function)-[:USES_TYPE]->(t:Type)

**KEY RULES**:
- ⚠️ Project does NOT directly connect to Type/Function (must go through File)
- ⚠️ Use exact relationship names from schema: CONTAINS, INHERITS_FROM, IMPLEMENTS, USES_TYPE, CALLS
- ⚠️ Properties are flat - NO nested access like `node.prop.subprop`
"""

    def _format_previous_queries(self) -> str:
        """Format previous queries for context."""
        if not self.state.queries_executed:
            return "No previous queries yet."

        formatted = []
        for i, q in enumerate(self.state.queries_executed, 1):
            formatted.append(f"""
Query {i}:
  Cypher: {q['query'][:100]}...
  Results: {q['result_count']} records
  Error: {q.get('error') or 'None'}
""")
        return "\n".join(formatted)

    def _build_final_result(self) -> Dict[str, Any]:
        """
        Build final result with rich citations and reasoning trail.

        Returns comprehensive traceability:
        - Which query discovered each data point
        - Why each query was generated (CoT reasoning)
        - How the agent decided to continue/stop
        - Full reasoning trail for transparency
        """
        # Build citation map: data -> query that discovered it
        citations = self._build_citation_map()

        # Build reasoning trail showing decision process
        reasoning_trail = self._build_reasoning_trail()

        # Build evidence summary with attributions
        evidence_summary = self._build_evidence_summary(citations)

        return {
            'approach_index': self.state.approach_index,
            'approach_name': self.state.approach_details.get('approach_name', 'Unknown'),
            'approach_goal': self.state.approach_details.get('description', ''),

            # Core results
            'discovered_data': self.state.discovered_data,
            'total_results': len(self.state.discovered_data),

            # Query execution details
            'queries_executed': len(self.state.queries_executed),
            'query_history': self.state.queries_executed,

            # Citations: map each data point to its source query
            'citations': citations,

            # Reasoning trail: show the agent's thought process
            'reasoning_trail': reasoning_trail,

            # Evidence summary: group findings by query with CoT reasoning
            'evidence_summary': evidence_summary,

            # Sufficiency assessment
            'is_sufficient': self.state.is_sufficient,
            'sufficiency_reason': self.state.sufficiency_reason,

            # Resource usage
            'tokens_used': self.state.tokens_used,
            'iterations': self.state.iteration
        }

    def _build_citation_map(self) -> Dict[str, Any]:
        """
        Build a map showing which query discovered each piece of data.

        Returns:
        {
            "data_point_0": {
                "query_index": 0,
                "query": "MATCH ...",
                "iteration": 1,
                "cot_reasoning": {...}
            },
            ...
        }
        """
        citations = {}
        data_index = 0

        for query_record in self.state.queries_executed:
            query_idx = query_record['iteration'] - 1
            results = query_record.get('results', [])

            for result in results:
                citation_key = f"data_point_{data_index}"
                citations[citation_key] = {
                    'query_index': query_idx,
                    'query': query_record['query'][:100] + '...',  # Truncate for readability
                    'full_query': query_record['query'],
                    'iteration': query_record['iteration'],
                    'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown'),
                    'cot_reasoning': query_record['reasoning'].get('cot_reasoning', {}),
                    'discovered_at': f"Iteration {query_record['iteration']}, Query {query_idx + 1}"
                }
                data_index += 1

        return citations

    def _build_reasoning_trail(self) -> List[Dict[str, Any]]:
        """
        Build a chronological trail of the agent's reasoning process.

        Shows:
        - What the agent thought at each step
        - Why it decided to generate each query
        - How it analyzed results
        - Why it decided to continue or stop
        """
        trail = []

        for query_record in self.state.queries_executed:
            iteration = query_record['iteration']

            # Decision to continue
            trail.append({
                'step': f"Iteration {iteration} - Decision",
                'type': 'think',
                'reasoning': f"Agent decided to generate another query based on previous results",
                'context': f"{len(self.state.discovered_data)} data points collected so far"
            })

            # Query generation with CoT
            cot = query_record['reasoning'].get('cot_reasoning', {})
            trail.append({
                'step': f"Iteration {iteration} - Query Generation",
                'type': 'generate',
                'query': query_record['query'],
                'cot_reasoning': {
                    'step1_identify': cot.get('step1_identify', 'N/A'),
                    'step2_trace_path': cot.get('step2_trace_path', 'N/A'),
                    'step3_filter': cot.get('step3_filter', 'N/A'),
                    'step4_return': cot.get('step4_return', 'N/A'),
                    'step5_optimize': cot.get('step5_optimize', 'N/A')
                },
                'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown')
            })

            # Execution result
            result_count = query_record.get('result_count', 0)
            error = query_record.get('error')
            trail.append({
                'step': f"Iteration {iteration} - Execution",
                'type': 'execute',
                'result_count': result_count,
                'error': error if error else None,
                'status': 'success' if not error and result_count > 0 else 'empty' if not error else 'error'
            })

            # Analysis (from stored analysis results)
            # Note: We need to store analysis results in query_record
            if 'analysis' in query_record:
                trail.append({
                    'step': f"Iteration {iteration} - Analysis",
                    'type': 'analyze',
                    'analysis': query_record['analysis'].get('analysis', ''),
                    'key_findings': query_record['analysis'].get('key_findings', []),
                    'recommendation': query_record['analysis'].get('recommendation', ''),
                    'next_query_hint': query_record['analysis'].get('next_query_hint', '')
                })

        # Final decision
        trail.append({
            'step': 'Final Decision',
            'type': 'conclude',
            'is_sufficient': self.state.is_sufficient,
            'reason': self.state.sufficiency_reason,
            'total_iterations': self.state.iteration,
            'total_data_points': len(self.state.discovered_data)
        })

        return trail

    def _build_evidence_summary(self, citations: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a summary of evidence organized by query.

        Groups findings by which query discovered them, with CoT reasoning.
        """
        evidence_by_query = {}

        for query_record in self.state.queries_executed:
            query_idx = query_record['iteration'] - 1
            key = f"query_{query_idx}"

            results = query_record.get('results', [])
            cot = query_record['reasoning'].get('cot_reasoning', {})

            evidence_by_query[key] = {
                'iteration': query_record['iteration'],
                'query': query_record['query'],
                'query_purpose': query_record['reasoning'].get('query_purpose', 'Unknown'),
                'cot_reasoning': {
                    'entities_targeted': cot.get('step1_identify', 'N/A'),
                    'path_used': cot.get('step2_trace_path', 'N/A'),
                    'filters_applied': cot.get('step3_filter', 'N/A')
                },
                'result_count': len(results),
                'key_findings': query_record.get('analysis', {}).get('key_findings', []),
                'sample_results': results[:3] if results else []  # First 3 for reference
            }

        return evidence_by_query
```

---

## Integration with Workflow

### Modified: `src/core/workflow/nodes.py`

Replace the complex `_run_approach_with_workflow_nodes()` with:

```python
async def _run_approach_with_mini_cot_agent(
    self,
    approach: Dict[str, Any],
    approach_index: int,
    base_state: AgentState,
    cypher_server: Any
) -> Dict[str, Any]:
    """
    Run a single approach using a mini CoT agent.

    Much simpler than the old approach - just create the agent and run it.
    """
    logger.info(f"🤖 Starting Mini CoT Agent for approach {approach_index}")

    # Extract context from state
    user_query = base_state.get('user_query', '')
    schema = base_state.get('schema', {})
    metadata = base_state.get('metadata', {})
    project_name = metadata.get('project_name', 'HelloWorldApp')
    llm_service = base_state.get('llm_service')

    # Create and run mini agent
    agent = MiniCoTAgent(
        approach_index=approach_index,
        approach_details=approach,
        user_query=user_query,
        schema=schema,
        project_name=project_name,
        llm_service=llm_service,
        cypher_server=cypher_server,
        max_iterations=5
    )

    result = await agent.run()

    # Convert to state update format
    return {
        'approach_index': approach_index,
        'state_updates': {
            'discovered_data': result['discovered_data'],
            'total_tokens_used': result['tokens_used'],
            'approach_statuses': {approach_index: 'completed'},
            'approach_raw_results': {approach_index: result['query_history']}
        }
    }
```

---

## Citation and Reasoning Output Example

### What Gets Returned

```json
{
  "approach_index": 0,
  "approach_name": "Class Structure Analysis",
  "approach_goal": "Identify all classes and their methods in the project",

  "discovered_data": [
    {"name": "Program", "type_kind": "class", "file_path": "Program.cs", ...},
    {"name": "Helper", "type_kind": "class", "file_path": "Helper.cs", ...},
    {"name": "Main", "type_kind": "method", "return_type": "void", ...}
  ],
  "total_results": 15,

  "queries_executed": 3,

  "citations": {
    "data_point_0": {
      "query_index": 0,
      "query": "MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type WHERE t.type_kind='class')...",
      "full_query": "MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type WHERE t.type_kind='class') RETURN t, f.file_path LIMIT 50",
      "iteration": 1,
      "query_purpose": "Find all class definitions in the project",
      "cot_reasoning": {
        "step1_identify": "I need Type nodes where type_kind='class'",
        "step2_trace_path": "Path: Project-[:CONTAINS]->File-[:CONTAINS]->Type (NOT direct Project->Type)",
        "step3_filter": "Filter Type nodes where type_kind='class'",
        "step4_return": "Return Type node and file path for context",
        "step5_optimize": "Limit to 50 results to control context"
      },
      "discovered_at": "Iteration 1, Query 1"
    },
    "data_point_1": {
      "query_index": 0,
      "query": "MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type WHERE t.type_kind='class')...",
      "iteration": 1,
      "query_purpose": "Find all class definitions in the project",
      "cot_reasoning": {...},
      "discovered_at": "Iteration 1, Query 1"
    },
    "data_point_2": {
      "query_index": 1,
      "query": "MATCH (t:Type {name: 'Program'})-[:CONTAINS]->(m:Function WHERE m.type_kind='method')...",
      "iteration": 2,
      "query_purpose": "Find methods within the Program class",
      "cot_reasoning": {
        "step1_identify": "I need Function nodes where type_kind='method' inside Type 'Program'",
        "step2_trace_path": "Path: Type-[:CONTAINS]->Function (classes contain methods)",
        "step3_filter": "Filter Function where type_kind='method' AND parent Type is 'Program'",
        "step4_return": "Return method name, return_type, parameters",
        "step5_optimize": "Limit to 25 results per class"
      },
      "discovered_at": "Iteration 2, Query 2"
    }
  },

  "reasoning_trail": [
    {
      "step": "Iteration 1 - Decision",
      "type": "think",
      "reasoning": "Agent decided to generate another query based on previous results",
      "context": "0 data points collected so far"
    },
    {
      "step": "Iteration 1 - Query Generation",
      "type": "generate",
      "query": "MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type WHERE t.type_kind='class') RETURN t, f.file_path LIMIT 50",
      "cot_reasoning": {
        "step1_identify": "I need Type nodes where type_kind='class'",
        "step2_trace_path": "Path: Project-[:CONTAINS]->File-[:CONTAINS]->Type",
        "step3_filter": "Filter Type nodes where type_kind='class'",
        "step4_return": "Return Type node and file path",
        "step5_optimize": "Limit to 50 results"
      },
      "query_purpose": "Find all class definitions in the project"
    },
    {
      "step": "Iteration 1 - Execution",
      "type": "execute",
      "result_count": 2,
      "error": null,
      "status": "success"
    },
    {
      "step": "Iteration 1 - Analysis",
      "type": "analyze",
      "analysis": "Successfully found 2 classes: Program and Helper. Both are well-defined classes with proper structure.",
      "key_findings": [
        "Program class is the entry point",
        "Helper class provides utility functions"
      ],
      "recommendation": "Continue with different query",
      "next_query_hint": "Now find methods within each class to understand their functionality"
    },
    {
      "step": "Iteration 2 - Decision",
      "type": "think",
      "reasoning": "Agent decided to generate another query based on previous results",
      "context": "2 data points collected so far"
    },
    {
      "step": "Iteration 2 - Query Generation",
      "type": "generate",
      "query": "MATCH (t:Type)-[:CONTAINS]->(m:Function WHERE m.type_kind='method') WHERE t.name IN ['Program', 'Helper'] RETURN m, t.name as class_name LIMIT 25",
      "cot_reasoning": {
        "step1_identify": "I need Function nodes (methods) within the classes we found",
        "step2_trace_path": "Path: Type-[:CONTAINS]->Function",
        "step3_filter": "Filter to methods in Program and Helper classes",
        "step4_return": "Return method details with class name for context",
        "step5_optimize": "Limit to 25 methods total"
      },
      "query_purpose": "Find methods within the Program and Helper classes"
    },
    {
      "step": "Iteration 2 - Execution",
      "type": "execute",
      "result_count": 3,
      "error": null,
      "status": "success"
    },
    {
      "step": "Iteration 2 - Analysis",
      "type": "analyze",
      "analysis": "Found 3 methods: Main in Program, PrintMessage in Helper, FormatString in Helper. This covers the main functionality.",
      "key_findings": [
        "Program.Main is the entry point method",
        "Helper.PrintMessage handles console output",
        "Helper.FormatString provides string formatting"
      ],
      "recommendation": "Sufficient data",
      "next_query_hint": ""
    },
    {
      "step": "Final Decision",
      "type": "conclude",
      "is_sufficient": true,
      "reason": "Collected comprehensive data about classes and their methods. Found 2 classes with 3 methods, which covers the project structure.",
      "total_iterations": 2,
      "total_data_points": 5
    }
  ],

  "evidence_summary": {
    "query_0": {
      "iteration": 1,
      "query": "MATCH (p:Project {name: 'HelloWorldApp'})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type WHERE t.type_kind='class') RETURN t, f.file_path LIMIT 50",
      "query_purpose": "Find all class definitions in the project",
      "cot_reasoning": {
        "entities_targeted": "Type nodes where type_kind='class'",
        "path_used": "Project-[:CONTAINS]->File-[:CONTAINS]->Type",
        "filters_applied": "type_kind='class'"
      },
      "result_count": 2,
      "key_findings": [
        "Program class is the entry point",
        "Helper class provides utility functions"
      ],
      "sample_results": [
        {"name": "Program", "type_kind": "class", ...},
        {"name": "Helper", "type_kind": "class", ...}
      ]
    },
    "query_1": {
      "iteration": 2,
      "query": "MATCH (t:Type)-[:CONTAINS]->(m:Function WHERE m.type_kind='method') WHERE t.name IN ['Program', 'Helper'] RETURN m, t.name LIMIT 25",
      "query_purpose": "Find methods within the Program and Helper classes",
      "cot_reasoning": {
        "entities_targeted": "Function nodes (methods) within classes",
        "path_used": "Type-[:CONTAINS]->Function",
        "filters_applied": "type_kind='method', parent class in ['Program', 'Helper']"
      },
      "result_count": 3,
      "key_findings": [
        "Program.Main is the entry point method",
        "Helper has 2 utility methods"
      ],
      "sample_results": [
        {"name": "Main", "return_type": "void", "class_name": "Program"},
        {"name": "PrintMessage", "return_type": "void", "class_name": "Helper"},
        {"name": "FormatString", "return_type": "string", "class_name": "Helper"}
      ]
    }
  },

  "is_sufficient": true,
  "sufficiency_reason": "Collected comprehensive data about classes and their methods",
  "tokens_used": 4500,
  "iterations": 2
}
```

### How This Helps Downstream

**1. Synthesize Response Node** can:
- See exactly which query discovered each fact
- Understand the reasoning behind each query
- Trace the agent's decision-making process
- Cite sources accurately: "According to Query 1 (Iteration 1), which searched for class definitions..."

**2. User Gets Transparency**:
- "I found 2 classes by searching Project→File→Type path"
- "Then I searched within those classes to find 3 methods"
- "Each finding is tagged with how it was discovered"

**3. Debugging**:
- If wrong data comes back, trace which query generated it
- See the CoT reasoning that led to that query
- Understand if path was wrong, filters were wrong, etc.

**4. Token Audit**:
- Track tokens per iteration
- See which queries were expensive
- Understand cost breakdown

---

## Smart Diagnostic Strategy

### When to Run Diagnostics

**❌ Don't run diagnostics for**:
- Syntax errors → LLM can fix these by reasoning about the query
- Successful queries with results → No need, we got data
- Queries that already ran diagnostics in same iteration

**✅ Run diagnostics for**:
- Empty results (0 records returned) → Need to understand why
- First empty result in an approach → To guide the agent

### What Diagnostics Return

**CHEAP queries that return METADATA only**, not full results:

1. **Node Count Check** (1 query):
   - Does the target node type exist in the project?
   - How many instances? (COUNT only)
   - Sample names (max 5)
   - Sample type_kinds (max 5)

2. **Relationship Path Check** (1 query):
   - Do intermediate nodes exist? (File count, Type count)
   - Sample file names (max 3)
   - Sample type names (max 3)

**Total overhead**: 2 queries returning ~20-50 bytes each = minimal context impact

### How Agent Uses Diagnostics

The diagnostic info is fed to the LLM in the analysis step:

```
Query returned empty.

Diagnostics show:
- Type nodes exist: 12 total
- Sample names: ["Program", "Helper", "Calculator"]
- File nodes exist: 3 total

Analysis: The nodes exist, but the relationship path is wrong.
The query tried: Project-[:CONTAINS]->Type
Correct path should be: Project-[:CONTAINS]->File-[:CONTAINS]->Type

Next query hint: Use File as intermediate node in the path.
```

The agent then uses this hint in the next CoT iteration to generate a corrected query.

### Context Window Control

**Current approach (5 diagnostics)**:
- 5 queries × 75 results each = 375 records in context
- Each record ~500 chars = 187KB per failure
- 5 failures = 935KB in context! 💥

**New approach (2 diagnostics)**:
- 2 queries × minimal metadata = ~50 bytes total
- 5 empty results = 250 bytes total ✅
- **99.97% reduction in diagnostic overhead**

---

## Benefits Summary

### Code Simplification
- **Before**: ~1000 lines of retry/diagnostic logic across multiple methods
- **After**: ~400 lines in single self-contained agent class

### Performance
- **Before**: 5 diagnostic queries per failure = 25 extra queries if 5 failures
- **After**: 0 diagnostic queries - LLM reasons about failures

### Adaptability
- **Before**: All queries generated upfront, no learning
- **After**: Each query informed by previous results

### Debuggability
- **Before**: Complex state scattered across nodes
- **After**: All state in one MiniCoTAgentState object

---

## Migration Plan

1. ✅ Create `mini_cot_agent.py` with MiniCoTAgent class
2. ✅ Add Pydantic models for CoT responses
3. ✅ Update `execute_batch_approaches` to use mini agents
4. ✅ Remove old retry/diagnostic logic
5. ✅ Test with parallel execution

**Estimated LOC reduction**: -600 lines (1000 → 400)
**Estimated performance improvement**: 30-50% faster (no diagnostic overhead)

---

## Deprecation and Cleanup Plan

### Phase 1: Mark as Deprecated (While Building Mini CoT Agent)

Add `@deprecated` decorators and warnings to old methods in `nodes.py`:

```python
@deprecated("Use MiniCoTAgent instead - will be removed after v2.0")
async def think(self, state: AgentState) -> AgentState:
    """DEPRECATED: Replaced by MiniCoTAgent._cot_think_step()"""
    logger.warning("⚠️ DEPRECATED: think() node - use MiniCoTAgent instead")
    # ... existing code ...

@deprecated("Use MiniCoTAgent instead - will be removed after v2.0")
async def generate_query(self, state: AgentState) -> AgentState:
    """DEPRECATED: Replaced by MiniCoTAgent._cot_generate_query_step()"""
    logger.warning("⚠️ DEPRECATED: generate_query() node - use MiniCoTAgent instead")
    # ... existing code ...

@deprecated("Use MiniCoTAgent instead - will be removed after v2.0")
async def execute_queries(self, state: AgentState) -> AgentState:
    """DEPRECATED: Replaced by MiniCoTAgent._execute_query()"""
    logger.warning("⚠️ DEPRECATED: execute_queries() node - use MiniCoTAgent instead")
    # ... existing code ...

@deprecated("Use MiniCoTAgent instead - will be removed after v2.0")
async def rethink(self, state: AgentState) -> AgentState:
    """DEPRECATED: Replaced by MiniCoTAgent._cot_analyze_results_step()"""
    logger.warning("⚠️ DEPRECATED: rethink() node - use MiniCoTAgent instead")
    # ... existing code ...

@deprecated("Use MiniCoTAgent._run_targeted_diagnostics() instead - will be removed after v2.0")
async def _run_diagnostics_on_failed_queries(self, ...):
    """DEPRECATED: Replaced by smarter targeted diagnostics in MiniCoTAgent"""
    logger.warning("⚠️ DEPRECATED: Old 5-diagnostic system - use MiniCoTAgent targeted diagnostics")
    # ... existing code ...
```

### Phase 2: Simplify AgentState

**Current AgentState** (747 lines, 50+ fields):
```python
class AgentState(TypedDict):
    # Query generation state
    current_query: str
    generated_queries: List[List[Dict[str, Any]]]  # Nested lists!
    query_reasoning: str
    expected_results: str

    # Execution state
    execution_status: str
    execution_error: str
    execution_results: List
    raw_query_results: List[Tuple[str, List[Dict]]]

    # Retry/error state
    syntax_error_feedback: Dict
    syntax_error_count: int
    failed_queries: List
    diagnostic_results: List

    # Approach iteration state
    current_approach_index: int
    current_approach_details: Dict
    thinking_results: Dict

    # ... 30+ more fields
```

**Simplified AgentState** (after Mini CoT Agent):
```python
class AgentState(TypedDict):
    """Simplified workflow state - most approach execution is in MiniCoTAgent."""

    # Core workflow inputs
    user_query: str
    schema: Dict[str, Any]
    metadata: Dict[str, Any]
    llm_service: Any

    # Workflow services
    cypher_server_manager: Any

    # Discovery phase (initial_discovery node)
    discovery_research: Dict[str, Any]  # Contains approaches
    discovered_entities: Dict[str, Any]

    # Intent analysis (analyze_intent node)
    intent: Dict[str, Any]

    # Batch execution results (execute_batch_approaches node)
    # Each approach returns MiniCoTAgent result with full citations/reasoning
    approach_results: List[Dict[str, Any]]  # NEW: Clean list of agent results

    # Accumulated data (manually aggregated in execute_batch_approaches)
    discovered_data: List[Dict[str, Any]]
    total_tokens_used: int

    # Sufficiency assessment (check_sufficiency node)
    is_sufficient: bool
    sufficiency_reasoning: str

    # Final response (synthesize_response node)
    final_response: str
    response_metadata: Dict[str, Any]

    # Workflow control
    current_iteration: int
    max_iterations: int
    current_node: str

# REMOVED FIELDS (no longer needed):
# - current_query, generated_queries (MiniCoTAgent handles)
# - execution_status, execution_error (MiniCoTAgent handles)
# - syntax_error_feedback, syntax_error_count (MiniCoTAgent handles)
# - failed_queries, diagnostic_results (MiniCoTAgent handles)
# - current_approach_index (MiniCoTAgent tracks internally)
# - thinking_results, query_reasoning (MiniCoTAgent returns full reasoning)
# ... ~25 fields removed!
```

**Reduction**: 50+ fields → ~20 fields (60% reduction)

### Phase 3: Simplify Token Tracking

**Current Token Tracking** (scattered across many fields):
```python
# In AgentState
total_tokens_used: int
tokens_per_approach: Dict[int, int]
llm_call_history: List[Dict]
think_tokens: int
generate_tokens: int
execute_tokens: int
rethink_tokens: int
total_estimated_cost_usd: float
models_used: List[str]
# ... complex tracking across multiple nodes
```

**Simplified Token Tracking** (consolidated in MiniCoTAgent):
```python
# MiniCoTAgent returns:
{
    'tokens_used': 4500,
    'token_breakdown': {
        'iteration_1': {
            'think': 500,
            'generate': 1200,
            'analyze': 400,
            'total': 2100
        },
        'iteration_2': {
            'think': 450,
            'generate': 1100,
            'analyze': 350,
            'diagnostics': 200,  # Only if diagnostics ran
            'total': 2100
        }
    },
    'cost_estimate_usd': 0.045,
    'models_used': ['gpt-4o', 'gpt-4o-mini']
}

# Workflow just sums across approaches:
total_tokens = sum(approach['tokens_used'] for approach in approach_results)
total_cost = sum(approach['cost_estimate_usd'] for approach in approach_results)
```

**Benefits**:
- Each agent tracks its own tokens (no global state pollution)
- Clear per-iteration breakdown for debugging
- Easy to aggregate at workflow level
- No scattered token fields in AgentState

### Phase 4: Cleanup Schedule

**Week 1: Build and Test**
- Implement MiniCoTAgent
- Test with parallel execution
- Validate citations and reasoning output
- Mark old methods as deprecated

**Week 2: Migration**
- Switch `execute_batch_approaches` to use MiniCoTAgent
- Update manual aggregation to use new result format
- Test end-to-end workflow

**Week 3: Cleanup**
- Remove deprecated methods (think, generate_query, execute_queries, rethink)
- Remove old diagnostic system (_run_diagnostics_on_failed_queries)
- Simplify AgentState schema
- Remove unused state fields
- Update all type hints

**Week 4: Documentation**
- Update architecture docs
- Update API docs
- Create migration guide for any external integrations

### Methods to Remove After Validation

```python
# In src/core/workflow/nodes.py

# Core node methods (replaced by MiniCoTAgent)
async def think(self, state: AgentState) -> AgentState  # Line ~600
async def generate_query(self, state: AgentState) -> AgentState  # Line ~743
async def execute_queries(self, state: AgentState) -> AgentState  # Line ~950
async def rethink(self, state: AgentState) -> AgentState  # Line ~1214

# Helper methods (replaced by MiniCoTAgent internals)
async def _perform_thinking_analysis_with_llm(...)  # Line ~1800
async def _analyze_approach_scope_with_llm(...)  # Line ~1900
def _build_targeted_query_generation_prompt(...)  # Line ~3134
def _build_syntax_error_fix_prompt(...)  # Line ~3400
async def _execute_queries_with_refinement(...)  # Line ~2775
async def _run_diagnostics_on_failed_queries(...)  # Line ~2900
async def _execute_single_query_with_validation(...)  # Line ~3370 (already marked deprecated)
async def _perform_rethink_analysis_with_llm(...)  # Line ~3600
async def _create_iteration_summary(...)  # Line ~3700

# Total: ~12 major methods, ~1500 lines of code
```

**Clean slate after removal**:
- `nodes.py`: 3500 lines → 2000 lines (43% reduction)
- `models.py`: AgentState 50 fields → 20 fields (60% reduction)
- New file: `mini_cot_agent.py`: ~400 lines (self-contained)

**Net code reduction**: ~900 lines removed overall
