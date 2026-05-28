# Information Flow: ANALYZE → THINK → GENERATE

## Your Question

> "After ANALYZE, when control goes back to THINK and GENERATE, what really happens? Does GENERATE know what is missing or what it did and what it needs to do? I thought tool assignment to the GENERATE step was supposed to take care of it."

## Short Answer

**Yes, GENERATE receives the feedback**, but the problem is **HOW** it receives it and **HOW** it uses it:

1. ✅ GENERATE **DOES** receive ANALYZE's recommendation and hints
2. ✅ GENERATE **DOES** have access to schema validation tools
3. ❌ GENERATE **DOES NOT** use tools to pre-validate relationships BEFORE creating query plans
4. ❌ ANALYZE hints are **TOO VAGUE** - they don't explicitly blacklist failed relationships

## Detailed Information Flow

### 1. ANALYZE Output (What Gets Stored)

From `adaptive_query_agent.py:400-405`, after ANALYZE completes, the system stores:

```python
query_record = {
    'iteration': self.state.iteration,
    'analysis': {
        'analysis': "The query plan failed at step 4...",  # ← Explanation
        'key_findings': [
            "CreateWorkers function exists and contains Block nodes.",
            "Block nodes contain Statement nodes, but none reference Type nodes.",
            "The expected condition was not met."
        ],
        'recommendation': "Alternative",  # ← RecommendationType
        'next_query_hint': "Try querying directly for Statements..."  # ← The hint!
    }
}
self.state.queries_executed.append(query_record)
self.state.last_analysis_hint = result.next_query_hint  # ← Saved for next iteration
```

### 2. THINK Step Input

From `adaptive_query_agent.py:474-496`, THINK receives:

```python
async def _cot_think_step(self) -> bool:
    # Format ALL previous query history with analysis
    previous_context = self._format_previous_queries()  # ← Includes everything!

    prompt = get_cot_think_prompt(
        user_query=self.state.user_query,
        approach_details=self.state.approach_details,
        iteration=self.state.iteration,
        previous_queries=previous_context,  # ← Full history with analysis
        discovered_data_count=len(self.state.discovered_data),
        last_analysis_hint=self.state.last_analysis_hint  # ← Most recent hint
    )
```

What `previous_context` contains (`adaptive_query_agent.py:2025-2048`):

```python
Query 1 (Iteration 1):
  Cypher: MATCH (f:Function)...
  Purpose: Validate CreateWorkers...
  Results: 0 records
  Key Findings: No Type nodes referenced by Statements, Expected condition not met
  Recommendation: Alternative
  Next Hint: Try querying directly for Statements without going through Blocks
```

### 3. GENERATE Step Input

From `adaptive_query_agent.py:531-625`, GENERATE receives:

```python
async def _cot_generate_query_step(self) -> Optional[Dict[str, Any]]:
    # Same full history as THINK
    previous_context = self._format_previous_queries()  # ← All analysis details

    base_prompt = get_cot_generate_query_plan_prompt(
        user_query=self.state.user_query,
        approach_details=self.state.approach_details,
        schema=self.state.schema,  # ← Schema (but not validated yet!)
        previous_queries=previous_context,  # ← Full history
        last_analysis_hint=self.state.last_analysis_hint  # ← "Try different approach"
    )

    # TOOL-BASED GENERATION
    if self.use_schema_tools and self.schema_tool_caller:
        tool_prompt = f"""{system_prompt}

{tool_docs}  # ← Schema tools available!

{prompt}

IMPORTANT: Use schema discovery tools to validate your query before writing it!
"""
```

## The Problem: Two Gaps

### Gap 1: ANALYZE Hints Are Too Vague

**What ANALYZE Says** (from Run 1 SQ3):
```
Recommendation: Alternative
Next Hint: "Try querying directly for Statements without going through Blocks"
```

**What ANALYZE SHOULD Say**:
```
Recommendation: Alternative
Next Hint: "STOP using Statement-[:REFERENCES]->Type - this relationship does NOT exist in the schema.
           Use Statement.text pattern matching instead (WHERE s.text CONTAINS 'new')."
Blacklisted Relationships: ["Statement-[:REFERENCES]->Type"]
```

**Why it matters**: The current hint is a vague suggestion. GENERATE interprets "try different angle" as "maybe use different filters" rather than "this fundamental relationship doesn't exist, try completely different approach".

### Gap 2: GENERATE Doesn't Pre-Validate Relationships

**Current Flow**:
1. LLM generates query plan with relationships
2. Schema tools are available but **OPTIONAL** for the LLM to use
3. Plan gets executed
4. Fails at step 4 (Statement-[:REFERENCES]->Type doesn't exist)
5. ANALYZE says "Alternative"
6. Loop back to step 1 with vague hint

**What SHOULD Happen**:
1. LLM starts thinking about query plan
2. **BEFORE** finalizing plan, use schema tools to verify:
   ```python
   result = schema_tool_caller.call_tool('get_valid_pairs', {
       'source_label': 'Statement',
       'relationship_type': 'REFERENCES',
       'target_label': 'Type'
   })
   # Returns: [] (empty - relationship doesn't exist!)
   ```
3. LLM sees relationship doesn't exist, tries different approach
4. Generate plan with valid relationships only
5. Execute and succeed

## Evidence from V10 Logs

### Failing Run (Run 1, Iteration 1):

**GENERATE created plan with**:
```
Step 4: Verify Statement nodes reference Type nodes
Query: MATCH (...)-[s:Statement]-[:REFERENCES]->(t:Type)
Expected: count >= 1
```

**ANALYZE feedback**:
```json
{
  "recommendation": "Alternative",
  "next_query_hint": "Try querying for a direct path from Function to Statement without filtering for return statements, or broaden the statement types to include all possible statements."
}
```

**Problem**: No mention that REFERENCES relationship doesn't exist!

### Iteration 2 (Same Run):

**GENERATE created ANOTHER plan with**:
```
Step 3: Verify Statement nodes reference Type nodes  (← Still using REFERENCES!)
Query: MATCH (...)-[s:Statement]-[:REFERENCES]->(t:Type)
```

**Why?** Because the hint didn't explicitly say "REFERENCES doesn't exist". GENERATE thought "broaden the statement types" meant changing the WHERE filter, not the relationship!

### Successful Run (Run 2):

**GENERATE created plan with**:
```
Step 3: Retrieve Statement nodes within Blocks
Query: MATCH (f:Function)-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
       WHERE s.text CONTAINS 'new'
       RETURN s.text
```

**No REFERENCES relationship!** This worked immediately because GENERATE randomly chose text pattern matching instead.

## Why Schema Tools Aren't Helping

The schema tools ARE available to GENERATE, but:

1. **LLM decides whether to use them** - It's not enforced
2. **Tool usage happens DURING query generation** - Not before plan finalization
3. **No automatic validation** - The system doesn't automatically validate relationships in the plan

From the logs, we saw:
```
🛠️ Executing 6 tool call(s)
   • get_node_labels({})
   • get_valid_pairs({'relationship_type': 'CONTAINS'})
   • get_valid_pairs({'relationship_type': 'REFERENCES'})  ← It DID check REFERENCES!
   • get_node_properties({'label': 'Function'})
   • get_node_properties({'label': 'Statement'})
   • get_node_properties({'label': 'Type'})
```

But the problem is: **When get_valid_pairs returns empty for REFERENCES**, the LLM doesn't interpret that as "don't use this relationship". It might think "hmm, let me try it anyway" or "maybe it exists but wasn't returned".

## The Solution: Three-Part Fix

### Fix 1: Explicit Relationship Validation in ANALYZE

When ANALYZE detects a failed step due to missing relationship, explicitly state:

```python
if failed_step_type == "path_check" and result_count == 0:
    # Extract relationship from failed query
    relationship = extract_relationship_from_query(failed_query)  # e.g., "REFERENCES"

    analysis_result['next_query_hint'] = (
        f"The relationship {relationship} between {source} and {target} "
        f"does NOT exist in the CPG schema. Do not use it in future queries. "
        f"Try alternative approaches: 1) Direct property matching (WHERE text CONTAINS), "
        f"2) Different relationship paths, 3) Different node types."
    )
    analysis_result['blacklisted_relationships'] = [
        f"{source}-[:{relationship}]->{target}"
    ]
```

### Fix 2: Pre-Validation in GENERATE

Before executing query plan, validate all relationships:

```python
# After LLM generates plan, before execution
plan_relationships = extract_relationships_from_plan(query_plan)

for rel in plan_relationships:
    valid = schema_tool_caller.call_tool('get_valid_pairs', {
        'source_label': rel.source,
        'relationship_type': rel.type,
        'target_label': rel.target
    })

    if not valid or len(valid) == 0:
        logger.warning(f"⚠️ Invalid relationship in plan: {rel}")
        # Automatically regenerate with feedback
        validation_feedback += (
            f"\nRelationship {rel.source}-[:{rel.type}]->{rel.target} "
            f"does NOT exist in the schema!"
        )
        retry_with_feedback()
```

### Fix 3: Enforce Tool Usage for Relationship Validation

Make schema tool validation **mandatory**, not optional:

```python
# In GENERATE step
system_prompt = """You are a Cypher query plan expert.

MANDATORY PROCESS:
1. BEFORE creating your query plan, use get_valid_pairs() to verify EVERY relationship
2. If a relationship doesn't exist, immediately try alternative approaches
3. ONLY include validated relationships in your final plan

Do NOT proceed with any relationship that get_valid_pairs() shows as invalid!
"""
```

## Summary

**Question**: Does GENERATE know what failed and what to do?

**Answer**:
- ✅ **It receives the information** (via `previous_context` and `last_analysis_hint`)
- ✅ **It has the tools** (schema validation tools)
- ❌ **But the information is too vague** ("try different angle" instead of "REFERENCES doesn't exist")
- ❌ **And the tools aren't enforced** (LLM can ignore validation results)

The fix isn't adding more information to the flow - the information is already there! The fix is:
1. Make ANALYZE's feedback more explicit about WHAT doesn't exist
2. Make GENERATE validate relationships BEFORE creating plans
3. Enforce schema tool usage instead of making it optional
