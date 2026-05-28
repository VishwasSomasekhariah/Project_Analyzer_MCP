"""
Centralized Prompt Management for Adaptive CPG Agent Workflow.

This module contains all LLM prompts used throughout the workflow with a clean
getter interface for parameter injection.
"""
import json
from typing import Dict, Any, List, Optional


class PromptManager:
    """
    Centralized manager for all workflow prompts.

    Provides type-safe methods to get prompts with parameter injection.
    """

    @staticmethod
    def get_intent_analysis_prompt(user_query: str) -> str:
        """
        Get prompt for analyzing user intent.

        Args:
            user_query: The user's question about the codebase

        Returns:
            Formatted prompt for intent analysis
        """
        return f"""
Analyze the user's intent and classify it appropriately.

User Query: {user_query}

Classify as:
- "lookup": Specific data retrieval (find comments, specific functions, etc.)
- "architectural": Understanding structure, relationships, patterns
- "hybrid": Combination of lookup and architectural analysis

Respond with valid JSON:
{{
    "intent_type": "lookup|architectural|hybrid",
    "confidence": 0.95,
    "reasoning": "Detailed reasoning for classification",
    "expected_result_type": "Description of expected results"
}}
"""

    @staticmethod
    def get_cot_think_prompt(
        user_query: str,
        approach_details: Dict[str, Any],
        iteration: int,
        max_iterations: int,
        previous_queries: str,
        discovered_data_count: int,
        last_analysis_hint: str
    ) -> str:
        """
        Get CoT think decision prompt.

        Args:
            user_query: Original user query
            approach_details: Approach configuration from discovery
            iteration: Current iteration number
            max_iterations: Maximum allowed iterations
            previous_queries: Formatted string of previous query results
            discovered_data_count: Number of data points discovered so far
            last_analysis_hint: Hint from last analysis step

        Returns:
            Formatted prompt for CoT think step
        """
        return f"""You are analyzing an approach for code property graph querying.

**USER QUERY**: {user_query}

**APPROACH GOAL**: {approach_details.get('description', 'Unknown')}
- Strategy: {approach_details.get('strategy', 'general')}
- Target Nodes: {approach_details.get('target_nodes', [])}
- Target Relationships: {approach_details.get('relationships', [])}

**ITERATION**: {iteration}/{max_iterations}

**PREVIOUS QUERIES** ({previous_queries.count('Query ') if 'Query ' in previous_queries else 0} executed):
{previous_queries}

**DISCOVERED DATA SO FAR**: {discovered_data_count} records

**LAST ANALYSIS HINT**: {last_analysis_hint if last_analysis_hint else 'None'}

**DECISION**: Should we generate another Cypher query for this approach?

Consider:
1. Have we gathered enough data to address this approach's goal?
2. Are previous queries failing (errors or empty results)?
3. Is there a different angle we should try based on the hint?
4. Have we exhausted reasonable query options?
5. Are we at max iterations?

Respond in JSON:
{{
    "should_continue": true/false,
    "reasoning": "Why continue or stop",
    "next_query_focus": "If continuing, what should next query focus on?"
}}
"""

    @staticmethod
    def get_cot_generate_query_prompt(
        user_query: str,
        approach_details: Dict[str, Any],
        project_name: str,
        schema: Dict[str, Any],
        previous_queries: str,
        last_analysis_hint: str,
        approach_packet: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get CoT query generation prompt.

        Args:
            user_query: Original user query
            approach_details: Approach configuration from discovery
            project_name: Project name to use in queries
            schema: Actual validated schema from workflow
            previous_queries: Formatted string of previous query results
            last_analysis_hint: Hint from last analysis step
            approach_packet: Optional full approach packet with premises

        Returns:
            Formatted prompt for CoT query generation
        """
        # Extract schema info
        node_labels = schema.get('node_labels', [])
        relationships = schema.get('relationships', {})

        # Format relationships - keep as JSON dump (LLM can parse it)
        rel_summary = json.dumps(relationships, indent=2)

        # Extract and format premises from approach_packet
        premises_section = ""
        if approach_packet:
            active_premises = approach_packet.get('active_premises', [])
            corrected_premises = approach_packet.get('corrected_premises', [])

            if active_premises:
                premises_list = "\n".join([f"  {p['id']}: {p['text']}" for p in active_premises])
                premises_section = f"""
**ACTIVE PREMISES** (treat these as true and already established):
{premises_list}
"""

                if corrected_premises:
                    corrections = "\n".join([f"  {p['id']}: {p['text']}" for p in corrected_premises])
                    premises_section = f"""
**CORRECTED PREMISES** (from previous APOC validation - use these as truth):
{corrections}

**ORIGINAL PREMISES** (replaced by corrections above):
{premises_list}
"""

        return f"""You are a Cypher query expert. Your task is to generate a single Cypher query to answer **this specific subquery**, using the given premises as truth and the actual schema.

# CONTEXT (Authoritative)
PROJECT: '{project_name}'  (use this exact literal value in the query; do NOT parameterize as $project_name)

USER QUERY:
{user_query}

SUBQUERY GOAL:
{approach_details.get('description', '')}
{approach_details.get('validation_summary', '')}
{premises_section}

ACTUAL SCHEMA (source of truth):
- Node Labels: {', '.join(node_labels) if isinstance(node_labels, list) else str(node_labels)}
- Relationships (JSON with valid_pairs specs):
{rel_summary}

PREVIOUS QUERIES (avoid duplicates):
{previous_queries}

LAST ANALYSIS HINT:
{last_analysis_hint if last_analysis_hint else 'None - this is the first query'}

# REASONING FRAMEWORK (summarize reasoning inside JSON fields)
Follow these six internal steps:

1. **Perspective**
   - State what aspect or entity this subquery investigates.
   - Example: “Find instantiation statements inside a known function.”

2. **Premise Validation**
   - Explicitly state which premises set the scope for this query.
   - Do *not* re-prove premises. Treat them as true and already established.
   - Example: "Using P1 (WorkerFactory is Type) and P2 (CreateWorkers contained in WorkerFactory)..."

3. **Path Trace**
   - Use the schema's valid_pairs to find the valid traversal path
     from the known entities in the premises to the target nodes.
   - If direct (from→to) is not valid, use a multi-hop path via allowed intermediates.
   - Never invent relationships not in schema.

4. **Filters**
   - Apply only filters relevant to this subquery’s goal
     (e.g., s.text CONTAINS 'new' for instantiation).
   - Respect property rules (no nested props, parse JSON strings before inspecting).

5. **Return Shape**
   - Return minimal but meaningful properties of target nodes.
   - Include enough context (function name, file path) for later synthesis.

6. **Optimize**
   - Add ORDER BY or LIMIT (25–100 typical).
   - Ensure query is not a duplicate of any PREVIOUS QUERIES.

---

# OUTPUT CONTRACT
Output only one valid JSON object (no markdown, no prose):

{{
  "cot_reasoning": {{
    "step1_perspective": "<short description>",
    "step2_premise_validation": "<how premises set the scope>",
    "step3_path_trace": "<label→relationship→label path used>",
    "step4_filters": "<filters used>",
    "step5_return": "<what properties are returned and why>",
    "step6_optimize": "<ordering, limits, dedup adjustments>"
  }},
  "cypher_query": "MATCH ... RETURN ... LIMIT ...",
  "query_purpose": "<concise sentence describing what this query discovers>",
  "entity_constraints": [
    {{
      "var": "f",
      "label": "Function",
      "property": "name",
      "value": "CreateWorkers"
    }}
  ]
}}

Guidelines:
- Premises are truth; do not attempt to validate or rediscover them.
- Focus only on answering the subquery, not the overall user question.
- Use only labels and relationships present in the ACTUAL SCHEMA.
- If direct (from→to) pair not in valid_pairs, build a valid multi-hop path.
- Avoid duplicate structure relative to PREVIOUS QUERIES.
- **entity_constraints**: List all WHERE clause property equality constraints (e.g., WHERE var.property = 'value').
  Extract the variable name, node label, property name, and the exact value being filtered.
  This enables diagnostics to verify entities exist. Empty array if no such constraints.
- Return only plain JSON—no code fences or explanation outside the object.
"""

    @staticmethod
    def get_cot_generate_query_plan_prompt(
        user_query: str,
        approach_details: Dict[str, Any],
        project_name: str,
        schema: Dict[str, Any],
        previous_queries: str,
        last_analysis_hint: str,
        approach_packet: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get CoT query plan generation prompt.

        This prompt instructs the LLM to generate a multi-step query plan with
        validation steps instead of a single query.

        Args:
            Same as get_cot_generate_query_prompt

        Returns:
            Formatted prompt for CoT query plan generation
        """
        # Extract schema info
        node_labels = schema.get('node_labels', [])
        relationships = schema.get('relationships', {})

        # Format relationships - keep as JSON dump (LLM can parse it)
        rel_summary = json.dumps(relationships, indent=2)

        # Extract and format premises from approach_packet
        premises_section = ""
        if approach_packet:
            active_premises = approach_packet.get('active_premises', [])
            corrected_premises = approach_packet.get('corrected_premises', [])

            if active_premises:
                premises_list = "\n".join([f"  {p['id']}: {p['text']}" for p in active_premises])
                premises_section = f"""
**ACTIVE PREMISES** (treat these as true and already established):
{premises_list}
"""

                if corrected_premises:
                    corrections = "\n".join([f"  {p['id']}: {p['text']}" for p in corrected_premises])
                    premises_section = f"""
**CORRECTED PREMISES** (from previous APOC validation - use these as truth):
{corrections}

**ORIGINAL PREMISES** (replaced by corrections above):
{premises_list}
"""

        return f"""You are a Cypher query expert. Your task is to generate a QUERY EXECUTION PLAN with multiple validation steps, not just a single query.

# CONTEXT (Authoritative)
PROJECT: '{project_name}'  (use this exact literal value in the query; do NOT parameterize as $project_name)

USER QUERY:
{user_query}

SUBQUERY GOAL:
{approach_details.get('description', '')}
{approach_details.get('validation_summary', '')}
{premises_section}

ACTUAL SCHEMA (source of truth):
- Node Labels: {', '.join(node_labels) if isinstance(node_labels, list) else str(node_labels)}
- Relationships (JSON with valid_pairs specs):
{rel_summary}

PREVIOUS QUERIES (avoid duplicates):
{previous_queries}

LAST ANALYSIS HINT:
{last_analysis_hint if last_analysis_hint else 'None - this is the first query'}

# QUERY PLAN STRUCTURE

Your plan should include:

1. **Entity Validation Steps** (step_type: "entity_check")
   - Verify entities mentioned exist (e.g., Function named 'CreateWorkers')
   - Query: MATCH (f:Function {{name: 'CreateWorkers'}}) RETURN count(f) as count
   - Expected: "count >= 1"
   - Guidance: What to do if entity doesn't exist

2. **Path Validation Steps** (step_type: "path_check")
   - Verify relationship paths exist (e.g., Function→Block→Statement)
   - Query: MATCH (f:Function {{name: 'X'}})-[:CONTAINS]->(b:Block) RETURN count(b) as count
   - Expected: "count >= 1"
   - Guidance: What to do if path doesn't exist

3. **Data Retrieval Step** (step_type: "data_retrieval")
   - The main query to get the actual data
   - Query: Full MATCH query with filters and RETURN
   - Expected: "results > 0"
   - Guidance: What to do if no results found

# REASONING FRAMEWORK (same 6 steps as before)

1. **Perspective**: What aspect or entity this subquery investigates
2. **Premise Validation**: Which premises set the scope
3. **Path Trace**: Valid traversal path from known entities to targets
4. **Filters**: Filters relevant to this subquery's goal
5. **Return Shape**: Minimal but meaningful properties
6. **Optimize**: ORDER BY, LIMIT, dedup

# OUTPUT CONTRACT

Output only one valid JSON object:

{{
  "cot_reasoning": {{
    "step1_perspective": "<short description>",
    "step2_premise_validation": "<how premises set the scope>",
    "step3_path_trace": "<label→relationship→label path used>",
    "step4_filters": "<filters used>",
    "step5_return": "<what properties are returned>",
    "step6_optimize": "<ordering, limits, dedup>"
  }},
  "plan_overview": "Brief overview of what this plan will accomplish",
  "steps": [
    {{
      "step_number": 1,
      "step_type": "entity_check",
      "purpose": "Verify CreateWorkers function exists",
      "cypher_query": "MATCH (f:Function {{name: 'CreateWorkers'}}) RETURN count(f) as count",
      "expected_outcome": "count >= 1",
      "on_failure_guidance": "Function 'CreateWorkers' not found - try fuzzy matching or check for typos",
      "depends_on_steps": [],
      "entities_validated": [
        {{
          "var": "f",
          "label": "Function",
          "property": "name",
          "value": "CreateWorkers"
        }}
      ]
    }},
    {{
      "step_number": 2,
      "step_type": "path_check",
      "purpose": "Verify Function contains Block nodes",
      "cypher_query": "MATCH (f:Function {{name: 'CreateWorkers'}})-[:CONTAINS]->(b:Block) RETURN count(b) as count",
      "expected_outcome": "count >= 1",
      "on_failure_guidance": "CreateWorkers has no Block nodes - statements may be direct children of Function",
      "depends_on_steps": [1],
      "entities_validated": []
    }},
    {{
      "step_number": 3,
      "step_type": "data_retrieval",
      "purpose": "Retrieve Statement nodes within Blocks",
      "cypher_query": "MATCH (f:Function {{name: 'CreateWorkers'}})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement) WHERE s.text CONTAINS 'new' RETURN s LIMIT 50",
      "expected_outcome": "results > 0",
      "on_failure_guidance": "No statements with 'new' keyword - try different text patterns or relationships",
      "depends_on_steps": [1, 2],
      "entities_validated": []
    }}
  ],
  "data_retrieval_step": 3,
  "fallback_hints": [
    "If Block path doesn't exist, try direct Function→Statement path",
    "If 'new' keyword filter returns nothing, try Statement→Type relationship"
  ],
  "all_entity_constraints": [
    {{
      "var": "f",
      "label": "Function",
      "property": "name",
      "value": "CreateWorkers"
    }}
  ]
}}

Guidelines:
- Start with entity checks to verify entities exist
- Then path checks to verify relationships exist
- Finally data retrieval to get actual data
- Each step should have clear expected outcome and failure guidance
- depends_on_steps should list previous step numbers (1-based) this step requires
- step_type must be exactly one of: "entity_check", "path_check", "count_check", "data_retrieval"
- expected_outcome should be checkable (e.g., "count >= 1", "results > 0")
- on_failure_guidance should explain what it means and suggest alternatives
- Return only plain JSON—no code fences or explanation outside the object
"""

    @staticmethod
    def get_cot_analyze_results_prompt(
        cypher_query: str,
        query_purpose: str,
        cot_reasoning: Dict[str, Any],
        execution_result: Dict[str, Any],
        diagnostic_info: Optional[Dict[str, Any]] = None,
        query_plan: Optional[Dict[str, Any]] = None,
        approach_goal: Optional[str] = None
    ) -> str:
        """
        Get CoT analysis prompt.

        Args:
            cypher_query: The executed query
            query_purpose: Purpose of the query
            cot_reasoning: CoT reasoning used to generate the query
            execution_result: Execution result with results/error
            diagnostic_info: Optional diagnostic information for empty results
            query_plan: Optional query plan with steps and validation criteria
            approach_goal: Optional approach-level goal to evaluate against

        Returns:
            Formatted prompt for CoT analysis
        """
        results = execution_result.get('results', [])
        error = execution_result.get('error')

        # Handle results whether it's a list or dict
        if isinstance(results, list):
            result_count = len(results)
        elif isinstance(results, dict):
            # If results is a dict, convert to list for display
            results = [results]
            result_count = 1
        else:
            results = []
            result_count = 0

        # Build query plan validation section
        plan_validation = ""
        if query_plan:
            steps = query_plan.get('steps', [])
            failed_at_step = query_plan.get('failed_at_step')

            if steps:
                plan_validation = "\n**QUERY PLAN VALIDATION**:\n"
                if failed_at_step is None and error is None:
                    plan_validation += "✅ ALL STEPS PASSED - Query executed successfully and met all expected_outcome criteria\n"
                    for i, step in enumerate(steps, 1):
                        expected = step.get('expected_outcome', 'N/A')
                        plan_validation += f"  Step {i}: ✅ PASSED (expected: {expected})\n"
                else:
                    plan_validation += f"❌ FAILED at step {failed_at_step}\n"
                    for i, step in enumerate(steps, 1):
                        if i < (failed_at_step or 999):
                            plan_validation += f"  Step {i}: ✅ PASSED\n"
                        elif i == failed_at_step:
                            plan_validation += f"  Step {i}: ❌ FAILED - {step.get('on_failure_guidance', 'No guidance')}\n"
                        else:
                            plan_validation += f"  Step {i}: ⏭️ SKIPPED\n"

        # Build approach goal section
        goal_section = ""
        if approach_goal:
            goal_section = f"\n**APPROACH GOAL**:\n{approach_goal}\n"

        return f"""You are analyzing the results of a Cypher query execution.

**QUERY EXECUTED**:
{cypher_query}

**QUERY PURPOSE**: {query_purpose}
{goal_section}
**COT REASONING USED**:
- Path: {cot_reasoning.get('step2_trace_path', 'N/A')}
- Filters: {cot_reasoning.get('step3_filter', 'N/A')}

**EXECUTION RESULT**:
- Success: {execution_result['success']}
- Result Count: {result_count}
- Error: {error if error else 'None'}
{plan_validation}
**RESULTS** (all results):
{json.dumps(results, indent=2, default=str) if results else 'Empty'}

{'**DIAGNOSTIC INFORMATION** (why query returned empty):' if diagnostic_info else ''}
{json.dumps(diagnostic_info, indent=2, default=str) if diagnostic_info else ''}

**ANALYZE**:

CRITICAL DECISION LOGIC:
1. If ALL STEPS PASSED (shown above), the query worked correctly!
2. Check if the results semantically answer the APPROACH GOAL (not just result count)
3. Look at the ACTUAL DATA in results - does it contain the information we need?
4. ONE result can contain MULTIPLE semantic entities (e.g., one Statement with multiple class instantiations)

If ERROR occurred:
- What went wrong? (syntax, schema mismatch, invalid path?)
- What would fix it? (different relationship, different node type?)

If EMPTY results:
- Look at diagnostic info - do the nodes exist in the database?
- Are the relationships correct according to diagnostics?
- Is the path too specific? Should we try a broader query?
- Are the filters too strict?

If ALL STEPS PASSED with results:
- ✅ The query executed successfully according to its own success criteria
- EVALUATE: Does the returned data answer the APPROACH GOAL?
  * Check the CONTENT of results (text fields, properties)
  * Don't judge by COUNT alone - one node can contain multiple semantic entities
  * If results contain the needed information → recommend "Sufficient"
  * If results don't answer the goal → explain what's missing and recommend "Continue"
- AVOID recommending "Refine" unless there's a technical issue (too many results, wrong data type, etc.)

Respond in JSON:
{{
    "analysis": "What happened and why",
    "key_findings": ["finding 1", "finding 2", ...],
    "recommendation": "EXACT value from list below",
    "next_query_hint": "If continuing, what should the next query do differently?"
}}

**CRITICAL - recommendation field MUST be EXACTLY one of these 5 values (no extra text)**:
- "Continue" → Continue with a different/refined query
- "Sufficient" → We have sufficient data for this approach
- "Alternative" → Try an alternative approach entirely
- "Stop" → Stop this approach (errors or no viable path forward)
- "Refine" → Query needs refinement (too many results, context issues)

Example VALID responses:
  {{"recommendation": "Continue"}}
  {{"recommendation": "Sufficient"}}

Example INVALID responses (will cause errors):
  {{"recommendation": "Continue with different query"}}  ❌ Extra text
  {{"recommendation": "Sufficient data"}}  ❌ Extra text
  {{"recommendation": "continue"}}  ❌ Wrong case
"""

    @staticmethod
    def get_approach_synthesis_prompt(
        user_query: str,
        approach_details: Dict[str, Any],
        discovered_data: List[Dict[str, Any]],
        partial_answers: List[Dict[str, Any]],
        avg_quality: float
    ) -> str:
        """
        Get prompt for synthesizing approach-level answer.

        Args:
            user_query: Original user query
            approach_details: Approach configuration
            discovered_data: All discovered data points with source query metadata
            partial_answers: Partial answers from each iteration
            avg_quality: Average quality grade across iterations

        Returns:
            Formatted prompt for approach synthesis
        """
        # Build summary of discovered data with indices - NO TRUNCATION
        data_summary = []
        for idx, data_point in enumerate(discovered_data):
            # Extract key fields for display (exclude internal metadata)
            display_fields = {k: v for k, v in data_point.items() if not k.startswith('_')}
            source_info = {
                'query': data_point.get('_source_query', 'Unknown'),  # Full query
                'iteration': data_point.get('_source_iteration', '?'),
                'purpose': data_point.get('_query_purpose', 'Unknown')
            }
            data_summary.append(f"""
Data Point [{idx}]:
  Source: Iteration {source_info['iteration']}, Purpose: {source_info['purpose']}
  Query: {source_info['query']}
  Data: {json.dumps(display_fields, default=str)}""")  # Full data, no truncation

        data_summary_str = '\n'.join(data_summary)

        # Build summary of partial answers - NO TRUNCATION
        findings_summary = []
        for pa in partial_answers:
            findings_summary.append(f"""
Iteration {pa['iteration']} ({pa['query_purpose']}):
  Quality: {pa['quality_grade']:.2f}/1.0
  Findings: {', '.join(pa['key_findings'])}""")  # All findings

        findings_summary_str = '\n'.join(findings_summary)

        return f"""You are synthesizing an answer for a specific **approach**, using discovered data from subqueries.

**USER QUERY**: {user_query}

**APPROACH**: {approach_details.get('approach_name', 'Unknown')}
- Goal: {approach_details.get('description', '')}
- Strategy: {approach_details.get('strategy', 'general')}
(Answer only from this approach's perspective, not the full user query.)

**DISCOVERED DATA** ({len(discovered_data)} total data points):
(Scan all data points carefully, not just the first few.)
{data_summary_str}

**ITERATION FINDINGS**:
(Use these to judge reliability of each data point.)
{findings_summary_str}

**AVERAGE QUALITY**: {avg_quality:.2f}/1.0

---

### YOUR TASK

1. **Identify Relevant Data**
   - Determine which discovered data points ([0] to [{len(discovered_data)-1}]) are relevant.
   - *Relevant* means the data directly supports or explains a fact necessary to answer the user's query **from this approach's goal**.

2. **Synthesize Answer**
   - Write an analytical, technical explanation that uses only the relevant data points.
   - Be specific: cite actual names, values, and relationships from the data.
   - Maintain coherence and factual precision.
   - Write as a coherent explanation, not bullet points or concatenated findings.
   - Do not try to solve the entire user query—focus strictly on this approach.

3. **Assess Confidence**
   - Rate confidence as High, Medium, or Low.
   - Base it primarily on the **number, consistency, and quality** of relevant data points.

---

Respond only with a valid JSON object:

{{
  "approach_answer": "Synthesized answer derived from relevant data points.",
  "data_points_used": [0, 3, 7],
  "confidence_assessment": "High/Medium/Low - brief justification."
}}

**IMPORTANT**:
- Output only the JSON object (no extra text or markdown).
- Include only indices you actually used.
- If no relevant data exists, return empty strings and an empty list.
"""


# Singleton instance
_prompt_manager = PromptManager()


# Convenience functions
def get_intent_analysis_prompt(user_query: str) -> str:
    """Get intent analysis prompt."""
    return _prompt_manager.get_intent_analysis_prompt(user_query)


def get_cot_think_prompt(
    user_query: str,
    approach_details: Dict[str, Any],
    iteration: int,
    max_iterations: int,
    previous_queries: str,
    discovered_data_count: int,
    last_analysis_hint: str
) -> str:
    """Get CoT think decision prompt."""
    return _prompt_manager.get_cot_think_prompt(
        user_query, approach_details, iteration, max_iterations,
        previous_queries, discovered_data_count, last_analysis_hint
    )


def get_cot_generate_query_prompt(
    user_query: str,
    approach_details: Dict[str, Any],
    project_name: str,
    schema: Dict[str, Any],
    previous_queries: str,
    last_analysis_hint: str,
    approach_packet: Optional[Dict[str, Any]] = None
) -> str:
    """Get CoT query generation prompt."""
    return _prompt_manager.get_cot_generate_query_prompt(
        user_query, approach_details, project_name, schema,
        previous_queries, last_analysis_hint, approach_packet
    )


def get_cot_generate_query_plan_prompt(
    user_query: str,
    approach_details: Dict[str, Any],
    project_name: str,
    schema: Dict[str, Any],
    previous_queries: str,
    last_analysis_hint: str,
    approach_packet: Optional[Dict[str, Any]] = None
) -> str:
    """Get CoT query plan generation prompt."""
    return _prompt_manager.get_cot_generate_query_plan_prompt(
        user_query, approach_details, project_name, schema,
        previous_queries, last_analysis_hint, approach_packet
    )


def get_cot_analyze_results_prompt(
    cypher_query: str,
    query_purpose: str,
    cot_reasoning: Dict[str, Any],
    execution_result: Dict[str, Any],
    diagnostic_info: Optional[Dict[str, Any]] = None
) -> str:
    """Get CoT analysis prompt."""
    return _prompt_manager.get_cot_analyze_results_prompt(
        cypher_query, query_purpose, cot_reasoning,
        execution_result, diagnostic_info
    )


def get_approach_synthesis_prompt(
    user_query: str,
    approach_details: Dict[str, Any],
    discovered_data: List[Dict[str, Any]],
    partial_answers: List[Dict[str, Any]],
    avg_quality: float
) -> str:
    """Get approach synthesis prompt."""
    return _prompt_manager.get_approach_synthesis_prompt(
        user_query, approach_details, discovered_data,
        partial_answers, avg_quality
    )
