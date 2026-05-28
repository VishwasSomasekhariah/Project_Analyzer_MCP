# Parallel Execution Critical Fixes

## Issue Summary

Test completed in **259.5 seconds** with 3 critical issues:

1. **Approach Index Collision Bug** (CRITICAL - causes data loss)
2. **Cypher Query Generation Failures** (need CoT reasoning)
3. **Performance Bottlenecks** (sequential LLM calls, excessive diagnostics)

---

## 1. CRITICAL: Approach Index Assignment Bug

### Problem
```
ERROR - ⚠️ CRITICAL: Dict key collision! Overlapping keys: {2, 3, 4, 5, 7, 8}
ERROR - ❌ Invalid approach index 7, total: 6
ERROR - ❌ Invalid approach index 8, total: 6
```

**Root Cause**: In `_run_approach_with_workflow_nodes`:
- Line 2234 sets `approach_state['current_approach_index'] = approach_index`
- Line 2247 does `approach_state.update(think_result)`
- The `think()` node returns incremented `current_approach_index`
- This overwrites the pre-assigned index, causing collisions!

### Solution

**File**: `src/core/workflow/nodes.py`

#### Fix 1: Protect approach_index in parallel execution

```python
async def _run_approach_with_workflow_nodes(
    self,
    approach: Dict[str, Any],
    approach_index: int,
    base_state: AgentState,
    cypher_server: Any
) -> Dict[str, Any]:
    """Run a single approach with actual workflow nodes."""

    # Create approach-specific state
    approach_state = dict(base_state)
    approach_state['current_approach_index'] = approach_index
    approach_state['current_approach_details'] = approach

    # NEW: Mark this execution as part of parallel batch
    approach_state['_in_parallel_batch'] = True
    approach_state['_fixed_approach_index'] = approach_index  # Immutable during this execution

    if cypher_server:
        approach_state['dedicated_cypher_server'] = cypher_server

    try:
        # Step 1: Think
        think_result = await self.think(approach_state)

        # NEW: Filter out approach_index changes during parallel execution
        filtered_result = self._filter_parallel_state_updates(think_result, approach_index)
        approach_state.update(filtered_result)

        # ... rest of the method
```

#### Fix 2: Add filtering helper

```python
def _filter_parallel_state_updates(
    self,
    node_result: Dict[str, Any],
    fixed_approach_index: int
) -> Dict[str, Any]:
    """
    Filter state updates from nodes during parallel execution.

    Prevents nodes from modifying:
    - current_approach_index (fixed per branch)
    - Other branch-specific immutable fields
    """
    filtered = dict(node_result)

    # Restore fixed approach index (don't let nodes change it)
    if 'current_approach_index' in filtered:
        logger.debug(f"  🔒 Protecting approach_index: ignoring change to {filtered['current_approach_index']}, keeping {fixed_approach_index}")
        filtered['current_approach_index'] = fixed_approach_index

    return filtered
```

#### Fix 3: Update all node update calls

```python
# In _run_approach_with_workflow_nodes, replace all:
approach_state.update(think_result)
# With:
approach_state.update(self._filter_parallel_state_updates(think_result, approach_index))

# Apply to all node calls:
- think_result
- generate_result
- execute_result
- rethink_result
```

---

## 2. Cypher Query Generation with Chain-of-Thought

### Problem
```
ERROR - ❌ Query generation failed: list index out of range
WARNING - 🔄 Using fallback query: MATCH (n:Type) RETURN n LIMIT 75
```

**Root Cause**: LLM generating invalid relationship paths (e.g., `Project-[:CONTAINS]->Type` instead of `Project->File->Type`)

### Solution

**File**: `src/core/workflow/nodes.py` in `generate_query` node

```python
async def generate_query(self, state: AgentState) -> Dict[str, Any]:
    """Generate Cypher query with Chain-of-Thought reasoning."""

    # ... existing setup code ...

    # NEW: Add CoT reasoning step
    cot_system_prompt = f"""You are a Cypher query expert. Use step-by-step reasoning to generate correct queries.

SCHEMA:
{schema_context}

APPROACH:
{approach_details}

Think through these steps:
1. IDENTIFY: What entities do we need from the schema?
2. TRACE PATH: What's the correct relationship path?
   - Check the schema carefully
   - Example: To get Types in a Project, path is: Project-[:CONTAINS]->File-[:CONTAINS]->Type
3. FILTER: What properties should we filter on?
4. RETURN: What fields should we return?
5. OPTIMIZE: Can we add limits or additional filters?

Now write the Cypher query based on your reasoning."""

    cot_user_prompt = f"""Generate a Cypher query for: {approach_description}

Think step-by-step:
Step 1 (Identify entities):
Step 2 (Trace path):
Step 3 (Filter):
Step 4 (Return fields):
Step 5 (Optimize):

Final Cypher Query:
```cypher
[YOUR QUERY HERE]
```"""

    # Call LLM with CoT prompt
    response = await self.llm_service.generate_with_pydantic(
        system_prompt=cot_system_prompt,
        user_prompt=cot_user_prompt,
        response_model=CypherQueryGeneration,
        model_name="gpt-4o",  # Use more capable model for CoT
        call_type="query_generation_cot",
        approach_index=approach_index,
        state=state
    )

    # ... rest of generation logic ...
```

### Alternative: Few-Shot Examples

Add schema-specific examples to prompt:

```python
EXAMPLES = """
Example 1: Find all classes in a project
❌ WRONG: MATCH (p:Project {{name: 'Foo'}})-[:CONTAINS]->(t:Type) RETURN t
✅ CORRECT: MATCH (p:Project {{name: 'Foo'}})-[:CONTAINS]->(f:File)-[:CONTAINS]->(t:Type {{type_kind: 'class'}}) RETURN t

Example 2: Find methods in a class
❌ WRONG: MATCH (c:Type {{name: 'Bar'}})-[:HAS]->(m:Method) RETURN m
✅ CORRECT: MATCH (c:Type {{name: 'Bar'}})-[:CONTAINS]->(m:Method) RETURN m

Example 3: Find inheritance relationships
❌ WRONG: MATCH (c:Type)-[:INHERITS]->(p:Type) RETURN c, p
✅ CORRECT: MATCH (c:Type)-[:IMPLEMENTS|EXTENDS]->(p:Type) RETURN c, p
"""
```

---

## 3. Performance Optimizations

### 3a. Parallelize LLM Calls Within Nodes

**Current**: Sequential LLM calls in `think`, `generate`, `rethink`
**Target**: Parallel calls where possible

```python
# In think node - parallelize multiple reasoning tasks
async def think(self, state: AgentState) -> Dict[str, Any]:
    """Think with parallel LLM calls."""

    # If we need multiple analyses, run them in parallel
    tasks = [
        self._analyze_scope(approach, state),
        self._analyze_constraints(approach, state),
        self._analyze_expected_results(approach, state)
    ]

    scope, constraints, expected = await asyncio.gather(*tasks)

    # Combine results
    thinking_result = {
        "scope": scope,
        "constraints": constraints,
        "expected_results": expected
    }

    return {"thinking_results": thinking_result}
```

### 3b. Reduce Diagnostic Overhead

**Current**: 5 diagnostics per failed query (many return empty)
**Target**: 2-3 most effective diagnostics in parallel

```python
def _run_diagnostics_on_failed_queries(self, failed_queries, state):
    """Run reduced set of diagnostics in parallel."""

    # Reduced to 3 most effective diagnostics
    diagnostic_types = [
        "check_node_exists",      # Does the primary node type exist?
        "check_relationships",     # Are the relationships correct?
        "sample_correct_query"     # Show a working query for reference
    ]

    # Run in parallel
    async def run_all_diagnostics():
        tasks = [
            self._run_diagnostic(query, diag_type, state)
            for query in failed_queries
            for diag_type in diagnostic_types
        ]
        return await asyncio.gather(*tasks, return_exceptions=True)

    return asyncio.run(run_all_diagnostics())
```

### 3c. Improve Initial Query Generation

**Current**: 3 retries with syntax errors
**Target**: Get it right the first time

```python
# Add schema validation before LLM call
def _validate_schema_context(self, schema, approach):
    """Extract and validate relevant schema subset."""

    # Parse approach to identify needed entities
    needed_entities = self._extract_entities_from_approach(approach)

    # Get schema subset with those entities and their relationships
    schema_subset = self._get_schema_subset(schema, needed_entities)

    # Add relationship examples
    schema_with_examples = self._add_relationship_examples(schema_subset)

    return schema_with_examples
```

---

## Expected Performance Improvements

### Before Fixes:
- ⏱️ Time: 259.5 seconds
- ❌ Errors: Approach index collisions, query generation failures
- 🐌 Bottlenecks: Sequential LLM calls, excessive diagnostics

### After Fixes:
- ⏱️ Time: ~60-90 seconds (3-4x faster)
  - Parallel LLM calls: -50s
  - Reduced diagnostics: -30s
  - Better initial queries (fewer retries): -80s
- ✅ Errors: No collisions, successful query generation
- 🚀 Throughput: True parallelism with dedicated servers

---

## Implementation Order

1. **CRITICAL FIRST**: Fix approach index collision (prevents data loss)
2. **HIGH PRIORITY**: Add CoT to query generation (fixes query errors)
3. **OPTIMIZATION**: Add parallel LLM calls (speeds up execution)
4. **OPTIMIZATION**: Reduce diagnostic overhead (speeds up error recovery)

---

## Testing

After each fix:

```bash
python3 test_parallel_with_token_tracking.py
```

Check for:
1. No collision errors in logs
2. No "list index out of range" errors
3. Reduced execution time
4. Successful query generation (no fallback queries)
