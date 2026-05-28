# CoT Workflow Data Flow Analysis

## Your Question
> "what are we passing within each of the CoT workflow?"

## Summary

The CoT (Chain-of-Thought) workflow receives data through **three prompt functions**, each called at different stages by the `AdaptiveQueryAgent`:

1. **`get_cot_think_prompt()`** - Decide whether to continue generating queries
2. **`get_cot_generate_query_prompt()`** - Generate Cypher query
3. **`get_cot_analyze_results_prompt()`** - Analyze query results

---

## 1. CoT Think Prompt (Should we continue?)

**Function:** `get_cot_think_prompt()`
**File:** `/opt/genpod/src/core/workflow/prompts.py:49-106`
**Called:** Before each iteration to decide if more queries are needed

### Input Parameters:
```python
def get_cot_think_prompt(
    user_query: str,                # Original user question
    approach_details: Dict[str, Any],  # Approach goal, strategy, target nodes
    iteration: int,                 # Current iteration number (1, 2, 3...)
    max_iterations: int,            # Maximum allowed iterations
    previous_queries: str,          # Formatted string of past queries + results
    discovered_data_count: int,     # Number of data points found so far
    last_analysis_hint: str         # Hint from previous analyze step
) -> str:
```

### What Gets Passed:
- **User query**: "What classes does the CreateWorkers method instantiate or return?"
- **Approach details**:
  - `approach_name`: "Subquery SQ2"
  - `description`: "Retrieve Statement nodes that instantiate Type nodes"
  - `strategy`: "node_focused"
  - `target_nodes`: ["Statement", "Type", "Block"]
  - `relationships`: ["CONTAINS", "REFERENCES"]
- **Iteration**: Current iteration number (1-5 typically)
- **Previous queries**: Full text of past queries, their results, and analysis
- **Discovered data count**: How many results found so far (e.g., 0 for SQ2)
- **Last analysis hint**: "Try different relationship path" or "Query too specific"

### Output:
```json
{
  "should_continue": true/false,
  "reasoning": "Why continue or stop",
  "next_query_focus": "What should next query focus on?"
}
```

---

## 2. CoT Generate Query Prompt (Create Cypher query)

**Function:** `get_cot_generate_query_prompt()`
**File:** `/opt/genpod/src/core/workflow/prompts.py:109-225`
**Called:** When think step decides to generate a query

### Input Parameters:
```python
def get_cot_generate_query_prompt(
    user_query: str,                # Original user question
    approach_details: Dict[str, Any],  # Same as think prompt
    project_name: str,              # e.g., "HelloWorldApp"
    schema: Dict[str, Any],         # ⚠️ CRITICAL - Schema with/without cardinality
    schema_examples: str,           # Example query patterns
    previous_queries: str,          # Past queries + results
    last_analysis_hint: str         # Hint from analysis
) -> str:
```

### What Gets Passed:

#### Schema Structure (The Problem!)
```python
schema = {
    'node_labels': ['Project', 'File', 'Type', 'Function', 'Statement', ...],
    'relationships': {
        'REFERENCES': {
            'description': 'References relationship',
            'cardinality': [  # ⚠️ MAY OR MAY NOT BE PRESENT!
                {'from': 'Variable', 'to': 'Type'},
                {'from': 'Function', 'to': 'Type'}
                # Note: Statement -> Type is NOT in this list!
            ],
            'properties': ['text', 'start_point', ...],
            'count': 1234
        },
        'CONTAINS': { ... },
        ...
    }
}
```

**THE ISSUE:** The schema is supposed to come from:
- **Tier 1:** Filtered reconciled schema (has cardinality)
- **Tier 2:** Complete reconciled schema (has cardinality)
- **Tier 3:** YAML schema (NO cardinality - just 'from': [list], 'to': [list])

But our STATE.pkl inspection showed **NO cardinality**, suggesting either:
1. The schema was captured before reconciliation
2. The reconciliation failed
3. The schema is being overwritten somewhere

#### Schema Examples String
```
Common Cypher patterns:
- Project → File: Project-[:CONTAINS]->File
- File → Type: File-[:CONTAINS*1..2]->Type (handles optional Namespace)
- Function → Variable: Function-[:CONTAINS]->Block-[:CONTAINS]->Variable
...
```

### Prompt Format (lines 158-160):
```python
**ACTUAL SCHEMA** (use this as source of truth):
- Node Types: Project, File, Type, Function, Statement, ...
- Relationships: {json.dumps(relationships, indent=2)}
```

**When relationships is a dict**, it does `json.dumps(relationships, indent=2)` which should include cardinality IF it exists in the dict.

**The cardinality validation instructions (lines 184-190):**
```
**CRITICAL - VALIDATE AGAINST CARDINALITY**:
- BEFORE using any relationship, CHECK if the specific (from→to) pair exists in its 'cardinality' list
- The 'cardinality' field shows EXACTLY which node pairs can connect via each relationship
- Example: If REFERENCES has cardinality [{from: Variable, to: Type}], then ONLY Variable→Type is valid
- If you want to use Statement-[REFERENCES]->Type, you MUST verify {from: Statement, to: Type} is in REFERENCES.cardinality
- If the pair is NOT in cardinality, that direct edge DOES NOT EXIST - you must find an alternate path
```

### Output:
```json
{
  "cot_reasoning": {
    "step1_identify": "entities needed",
    "step2_trace_path": "relationship path (verified each pair against cardinality)",
    "step3_filter": "filters to apply",
    "step4_return": "what to return",
    "step5_optimize": "optimizations"
  },
  "cypher_query": "MATCH ... RETURN ... LIMIT ...",
  "query_purpose": "What this query will discover"
}
```

---

## 3. CoT Analyze Results Prompt (What happened?)

**Function:** `get_cot_analyze_results_prompt()`
**File:** `/opt/genpod/src/core/workflow/prompts.py:228-323`
**Called:** After executing a Cypher query

### Input Parameters:
```python
def get_cot_analyze_results_prompt(
    cypher_query: str,              # The query that was executed
    query_purpose: str,             # What we expected to find
    cot_reasoning: Dict[str, Any],  # The 5-step reasoning used
    execution_result: Dict[str, Any],  # Success, results, error
    diagnostic_info: Optional[Dict[str, Any]] = None  # Why query failed
) -> str:
```

### What Gets Passed:
- **Cypher query**: The actual query executed
- **Query purpose**: "Find Statement nodes that instantiate Type nodes"
- **CoT reasoning**: The 5-step reasoning from generation
- **Execution result**:
  ```python
  {
    'success': False,
    'results': [],  # Empty for SQ2
    'error': None
  }
  ```
- **Diagnostic info** (if empty results):
  ```python
  {
    'node_exists': {
      'Statement': True,  # 142 Statement nodes exist
      'Type': True        # 5 Type nodes exist
    },
    'relationship_cardinality': {
      'REFERENCES': [
        {'from': 'Variable', 'to': 'Type'},
        {'from': 'Function', 'to': 'Type'}
        # Statement -> Type NOT here!
      ]
    },
    'alternate_paths': [...]
  }
  ```

### Output:
```json
{
  "analysis": "What happened and why",
  "key_findings": ["finding 1", "finding 2"],
  "recommendation": "Continue|Sufficient|Alternative|Stop|Refine",
  "next_query_hint": "What should next query do differently?"
}
```

---

## The Critical Finding

### Where Cardinality Gets Lost

**From our investigation:**

1. **DynamicSchemaManager creates reconciled schema with cardinality** (line 490):
   ```python
   reconciled['relationships'][rel_type] = {
       'description': ...,
       'cardinality': valid_pairs,  # ← HAS CARDINALITY
       'properties': ...,
       'count': ...
   }
   ```

2. **AdaptiveQueryAgent sets `self.state.schema`** (lines 226-242):
   ```python
   self.state.schema = {
       'nodes': node_schemas,
       'node_labels': list(node_schemas.keys()),
       'relationships': schema_result.get('relationships', {})  # ← Should have cardinality
   }
   ```

3. **But STATE.pkl shows NO cardinality:**
   ```python
   'REFERENCES': {
       'from': ['Function', 'Type', 'Variable'],  # ← List format (old APOC)
       'to': ['Function', 'Type', 'Variable'],    # ← Not cardinality pairs!
       'properties': [...]
   }
   ```

### Two Possibilities:

#### Hypothesis 1: Schema not reconciled yet when captured
- STATE.pkl was saved before adaptive agent ran
- The schema stored is the initial YAML schema from `initialize_environment`
- Reconciled schema with cardinality exists but wasn't saved to pickle

#### Hypothesis 2: Schema Manager returns old format
- The `schema_result.get('relationships', {})` returns old APOC format
- Need to verify what `get_nodes_for_subquery_types()` actually returns

---

## What This Means for Cardinality Validation

### Why Prompt Instructions Failed:

If the schema passed to `get_cot_generate_query_prompt()` looks like this:
```python
'REFERENCES': {
    'from': ['Function', 'Type', 'Variable'],  # List of all possible sources
    'to': ['Function', 'Type', 'Variable']      # List of all possible targets
}
```

Then there's **NO cardinality field to validate against!**

The LLM sees:
- REFERENCES exists ✓
- Statement can use REFERENCES (Statement is a node type) ✓
- Type can use REFERENCES (Type is in 'to' list) ✓
- **No explicit pairs to check** ❌

So the LLM generates: `Statement -[REFERENCES]-> Type`

### If Schema Had Cardinality:
```python
'REFERENCES': {
    'cardinality': [
        {'from': 'Variable', 'to': 'Type'},
        {'from': 'Function', 'to': 'Type'}
    ]
}
```

The LLM could validate:
- Is `{'from': 'Statement', 'to': 'Type'}` in the cardinality list? ❌ NO!
- Must use alternate path

---

## Recommendation

**We need to verify the actual schema format being passed to prompts during runtime.**

Options:
1. Add logging in `get_cot_generate_query_prompt()` to dump the schema structure
2. Check if `get_nodes_for_subquery_types()` returns cardinality
3. Implement programmatic validation as backup (don't rely on LLM to parse JSON)

The real fix is ensuring cardinality data flows correctly from:
```
DynamicSchemaManager.reconciled_schema
  → get_nodes_for_subquery_types()
    → AdaptiveQueryAgent.state.schema
      → get_cot_generate_query_prompt()
        → LLM prompt
```
