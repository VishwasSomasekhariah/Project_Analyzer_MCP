# Prompt Ambiguity Analysis

## Problem Statement

SQ2 generated queries using `-[:REFERENCES]->` even though:
1. REFERENCES was **NOT in the extracted schema** (only CONTAINS and CALLS)
2. The cardinality validation instructions couldn't work (no REFERENCES to validate)
3. All 5 queries failed with 0 results

## Current Prompt Issues

### Issue 1: Conflicting Information Sources (Lines 147-152 vs 158-160)

**APPROACH Section (Line 151):**
```
- Relationships: {approach_details.get('relationships', [])}
```

**ACTUAL SCHEMA Section (Line 160):**
```
- Relationships: {rel_summary}  # Only CONTAINS, CALLS for SQ2
```

**Problem:** The approach might list REFERENCES (from Phase 0 decomposition based on "instantiate"), but the actual extracted schema doesn't have it. The LLM sees BOTH and gets confused about which is the source of truth.

**Evidence:**
- Approach goal: "instantiate Type nodes" → implies REFERENCES
- Extracted schema: `rels=['CONTAINS', 'CALLS']` → no REFERENCES
- LLM used: `-[:REFERENCES]->` anyway

### Issue 2: Weak Schema Constraint Language (Line 181)

**Current:**
```
⚠️ DO NOT invent relationships not in schema
```

**Problems:**
1. Advisory ("DO NOT") not enforced
2. Ambiguous: which schema? (approach relationships vs actual schema)
3. No consequences stated
4. LLMs ignore soft warnings when they "know better"

**Better:**
```
🚫 CRITICAL CONSTRAINT: You MUST ONLY use relationships listed in "ACTUAL SCHEMA" above.
   - Using ANY relationship not in that list will result in query failure.
   - If you need a relationship not in the schema, you CANNOT answer this query.
```

### Issue 3: Cardinality Instructions Apply to Wrong Relationship (Lines 184-190)

**Current:**
```
**CRITICAL - VALIDATE AGAINST CARDINALITY**:
- BEFORE using any relationship, CHECK if the specific (from→to) pair exists in its 'cardinality' list
- Example: If REFERENCES has cardinality [{from: Variable, to: Type}], then ONLY Variable→Type is valid
```

**Problems:**
1. Assumes relationship exists in schema (but REFERENCES doesn't for SQ2)
2. Example uses REFERENCES, which reinforces LLM's belief it's available
3. No guidance for "what if relationship isn't in schema at all?"

### Issue 4: "SCHEMA EXAMPLES" Section Confuses (Line 162-163)

**Current:**
```
**SCHEMA EXAMPLES** (guidance for common patterns):
{schema_examples}
```

**Problem:**
- schema_examples might include REFERENCES patterns from other queries
- LLM sees these as "available patterns" even if not in current schema
- "guidance" sounds optional, not restrictive

### Issue 5: Approach Goal Uses Ambiguous Language

**SQ2 Goal:**
> "Retrieve Statement nodes that **instantiate** Type nodes"

**Problem:**
- "instantiate" strongly implies REFERENCES relationship (semantically correct)
- LLM uses training knowledge: "instantiation = object creation = references"
- Even though schema doesn't have REFERENCES, the goal primes the LLM to use it

### Issue 6: No Explicit "ONLY THESE" List

The prompt lists what's available but doesn't explicitly restrict to ONLY those items.

**Current approach:**
- Shows what's available ✓
- Warns against invention ⚠️
- But doesn't enforce "ONLY THESE" ✗

---

## Root Cause Analysis

### The Cognitive Flow Leading to Hallucination:

1. **LLM reads approach goal:** "instantiate Type nodes"
   - Training knowledge: instantiation = object creation = REFERENCES

2. **LLM sees approach relationships (line 151):** might include REFERENCES

3. **LLM sees ACTUAL SCHEMA (line 160):** CONTAINS, CALLS (no REFERENCES)

4. **LLM sees warning (line 181):** "Don't invent relationships"
   - But relationship is in approach (not inventing!)
   - Just not in extracted schema

5. **LLM decision:**
   - "REFERENCES makes semantic sense for 'instantiate'"
   - "It's in the approach relationships"
   - "The warning is soft ('DO NOT' not 'CANNOT')"
   - "I'll use REFERENCES"

6. **Result:** Query fails, 28K tokens wasted

---

## Proposed Enhancements

### Enhancement 1: Remove Approach Relationships from Prompt

**Current:**
```python
**APPROACH**: {approach_details.get('approach_name', 'Unknown')}
- Goal: {approach_details.get('description', '')}
- Strategy: {approach_details.get('strategy', 'general')}
- Target Nodes: {approach_details.get('target_nodes', [])}
- Relationships: {approach_details.get('relationships', [])}  ← REMOVE THIS
```

**Reason:** Don't show relationships that aren't in the actual schema. This creates confusion.

### Enhancement 2: Strengthen Schema Restriction Language

**Add at beginning:**
```
🚫 CRITICAL CONSTRAINT - SCHEMA BOUNDARY:
You MUST ONLY use relationships from the "AVAILABLE RELATIONSHIPS" list below.
- Any relationship not in this list DOES NOT EXIST in the database.
- Using an unlisted relationship will cause query failure and waste resources.
- If the query cannot be answered with available relationships, return {"error": "insufficient_schema", "missing": ["REL_NAME"]}.
```

### Enhancement 3: Replace "ACTUAL SCHEMA" with "AVAILABLE RELATIONSHIPS"

**Current:**
```
**ACTUAL SCHEMA** (use this as source of truth):
- Node Types: Function, Type, Statement
- Relationships: {rel_summary}
```

**Enhanced:**
```
🔓 AVAILABLE RELATIONSHIPS (COMPLETE LIST - NOTHING ELSE EXISTS):
{rel_summary}

✅ You MAY use: CONTAINS, CALLS (and their cardinality-validated paths)
❌ You MAY NOT use: REFERENCES, DECLARES, or ANY other relationship
   (They don't exist in the extracted schema for this query)
```

### Enhancement 4: Move Cardinality to Relationship Definitions

**Current:** Cardinality instructions are separate (lines 184-190)

**Enhanced:** Inline cardinality with each relationship
```
🔓 AVAILABLE RELATIONSHIPS:

1. CONTAINS:
   Valid paths (cardinality-validated):
   - Function -> Block
   - Block -> Statement
   - Type -> Function
   - File -> Type

   ❌ INVALID: Statement -> Type (not in cardinality)

2. CALLS:
   Valid paths:
   - Function -> Function

   ❌ INVALID: Function -> Type, Statement -> Function
```

### Enhancement 5: Add Explicit "Schema Gap" Guidance

**New section after Step 2:**
```
⚠️ SCHEMA GAP HANDLING:
- If the query requires a relationship not in AVAILABLE RELATIONSHIPS:
  * DO NOT use it anyway (will fail)
  * DO NOT try to infer it (not in database)
  * Instead: Use only available relationships to get closest possible result
  * Or return: {"error": "insufficient_schema", "needed": "RELATIONSHIP_NAME"}
```

### Enhancement 6: Make Step 2 More Explicit

**Current:**
```
Step 2 - TRACE PATH: What's the correct relationship path in the schema?
- Look at the schema examples above carefully
- ⚠️ DO NOT invent relationships not in schema
```

**Enhanced:**
```
Step 2 - TRACE PATH: What's the correct relationship path?
- CRITICAL: ONLY use relationships from "AVAILABLE RELATIONSHIPS" above
- Check each (from→to) pair against the valid paths listed
- If needed relationship is not listed, STOP and report insufficient schema
- Example validation:
  * Want: Statement-[:REFERENCES]->Type
  * Check: Is REFERENCES in available relationships? NO
  * Action: Cannot use this path, must find alternative or report gap
```

---

## Enhanced Prompt Template

```python
f"""You are a Cypher query expert. Use step-by-step reasoning to generate a correct query.

**USER QUERY**: {user_query}

**APPROACH GOAL**: {approach_details.get('description', '')}
- Target Nodes: {approach_details.get('target_nodes', [])}
- Strategy: {approach_details.get('strategy', 'general')}

**PROJECT**: '{project_name}' (use this exact value, NOT $project_name)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🚫 CRITICAL CONSTRAINT - SCHEMA BOUNDARY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You MUST ONLY use relationships from "AVAILABLE RELATIONSHIPS" below.
- Any relationship not in this list DOES NOT EXIST in the database.
- Using an unlisted relationship will cause query failure.
- If needed relationship is missing, return {{"error": "insufficient_schema"}}.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔓 AVAILABLE RELATIONSHIPS (COMPLETE LIST):

{format_relationships_with_cardinality(schema['relationships'])}

✅ Node Types Available: {', '.join(node_labels)}

**SCHEMA EXAMPLES** (patterns using ONLY available relationships):
{schema_examples}

**PREVIOUS QUERIES** (learn from these):
{previous_queries}

**LAST ANALYSIS HINT**: {last_analysis_hint if last_analysis_hint else 'None - this is the first query'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**CHAIN-OF-THOUGHT REASONING** (Follow these 5 steps):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step 1 - IDENTIFY: What entities do I need?
- What node types from the approach should I retrieve?
- Example: "I need Type nodes representing classes"

Step 2 - VALIDATE RELATIONSHIPS: Can I build this path with available relationships?
- Check: Is each needed relationship in "AVAILABLE RELATIONSHIPS" above?
- Check: Is each (from→to) pair in the relationship's cardinality list?
- If ANY relationship is missing:
  * STOP - Cannot generate valid query
  * Return: {{"error": "insufficient_schema", "missing_relationships": ["REL_NAME"]}}
- If ANY (from→to) pair is invalid:
  * Find alternate path using valid pairs
  * Or return error if no alternate exists

Step 3 - TRACE PATH: What's the correct relationship path?
- Start from Project node: Project {{name: '{project_name}'}}
- Use ONLY relationships validated in Step 2
- Example: "Project-[:CONTAINS]->File-[:CONTAINS]->Type"
- ⚠️ DO NOT skip intermediate nodes

Step 4 - FILTER: What properties should I filter on?
- Use approach's target attributes: {approach_details.get('key_attributes', [])}
- Example: "Filter where type_kind='class'"

Step 5 - RETURN & OPTIMIZE:
- Include relevant properties from target nodes
- Add LIMIT clause (25-100 results)
- Order by relevance if helpful

**NOW GENERATE**:

Respond in JSON:
{{
    "schema_validation": {{
        "all_relationships_available": true/false,
        "missing_relationships": ["REL_NAME", ...] or [],
        "cardinality_valid": true/false
    }},
    "cot_reasoning": {{
        "step1_identify": "entities needed...",
        "step2_validate": "relationship validation check...",
        "step3_trace_path": "relationship path...",
        "step4_filter": "filters to apply...",
        "step5_optimize": "optimizations..."
    }},
    "cypher_query": "MATCH ... RETURN ... LIMIT ..." or null if schema insufficient,
    "query_purpose": "What this query will discover" or error description
}}
"""
```

---

## Expected Impact

### Before Enhancement (Current):
- SQ2: 5 queries, 0 results, 28,937 tokens wasted
- LLM uses REFERENCES (not in schema)
- No explicit validation

### After Enhancement:
- Step 2 validation would fail: "REFERENCES not in AVAILABLE RELATIONSHIPS"
- Return: `{"error": "insufficient_schema", "missing": ["REFERENCES"]}`
- 0 wasted queries, early detection
- Or: Agent finds alternate path using CONTAINS only

### Cost Savings:
- Current waste: ~$0.058 per failed approach
- With enhancement: ~$0.002 for validation (97% savings)
- Added benefit: Clear error messages for debugging
