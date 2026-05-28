# Prompt Data Sources - Where Each Piece Comes From

## Summary of Findings

### 1. **schema_examples** (Line 388 in adaptive_query_agent.py)

**Built by:** `_build_schema_path_examples()` at line 1127

**Source:** STATIC HARDCODED examples!

```python
def _build_schema_path_examples(self) -> str:
    """
    Build concrete examples of valid relationship paths from schema.

    These examples guide the LLM to use correct paths.
    """
    return f"""
**Some Valid Path Examples**:

1. **Project → File nodes**:
   MATCH (p:Project {{name: '{self.state.project_name}'}})-[:CONTAINS]->(f:File)

2. **Reaching Type nodes (optional Namespace may exist)**:
   MATCH (f:File)-[:CONTAINS*1..2]->(t:Type)

3. **Reaching Function nodes**:
   MATCH (t:Type)-[:CONTAINS]->(fn:Function)
   MATCH (f:File)-[:CONTAINS]->(fn:Function)

4. **Accessing Statement nodes (requires Block nodes)**:
   MATCH (fn:Function)-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)

5. **Type node relationships**:
   MATCH (child:Type)-[:INHERITS_FROM]->(parent:Type)  ← Shows INHERITS_FROM
   MATCH (impl:Type)-[:IMPLEMENTS]->(interface:Type)   ← Shows IMPLEMENTS

6. **Function node relationships**:
   MATCH (caller:Function)-[:CALLS]->(callee:Function)
```

**Problem:**
- These examples are **NOT filtered** by what's in `self.state.schema['relationships']`
- They show ALL possible relationships from the full CPG (INHERITS_FROM, IMPLEMENTS, etc.)
- For SQ2, only CONTAINS and CALLS are available, but examples show more
- **Confusing signal:** LLM sees relationships in examples that aren't in actual schema

**Impact:**
- LLM thinks relationships like INHERITS_FROM are available
- May prime LLM to hallucinate other relationships from training data

---

### 2. **approach_details['relationships']** (Line 507-512 in nodes.py)

**Built at:** `nodes.py:507-512` when creating minimal approach_details

```python
approach_details = {
    'approach_name': f"Subquery {packet['id']}",
    'description': packet['text'],
    'target_nodes': [],        # Empty list
    'strategy': 'lookup'
    # NO 'relationships' field!
}
```

**What gets passed to prompt (line 151 in prompts.py):**
```python
- Relationships: {approach_details.get('relationships', [])}
```

**Result:** Shows `[]` (empty list) because field doesn't exist!

**Good news:** This is NOT the source of confusion - it's empty.

**But:** In the old discovery-based approach (before packets), this field existed and came from Phase 0 decomposition.

---

### 3. **Actual Schema Relationships** (Line 229 in adaptive_query_agent.py)

**Built by:** `schema_manager.get_schema_for_subquery()`

**Returns:**
```python
self.state.schema = {
    'nodes': node_schemas,
    'node_labels': list(node_schemas.keys()),
    'relationships': schema_result.get('relationship_schemas', {}),  ← From extraction
    'paths': schema_result.get('paths', [])
}
```

**For SQ2:**
```python
'relationships': {
    'CONTAINS': {
        'description': 'Contains relationship',
        'cardinality': [
            {'from': 'Function', 'to': 'Block'},
            {'from': 'Block', 'to': 'Statement'},
            ...
        ],
        'properties': [...],
        'count': ...
    },
    'CALLS': {
        'cardinality': [
            {'from': 'Function', 'to': 'Function'}
        ],
        ...
    }
}
```

**Formatted in prompt (line 160):**
```python
- Relationships: {rel_summary}
```

Where `rel_summary = json.dumps(relationships, indent=2)` (line 141)

**This is the CORRECT schema**, but:
- Buried in JSON blob
- Comes AFTER static examples that show more relationships
- "Source of truth" language is weak

---

## The Cognitive Conflict for the LLM

### What the LLM Sees (in order):

1. **Approach relationships:** `[]` (empty - not confusing)

2. **Static schema examples:** Shows CONTAINS, CALLS, INHERITS_FROM, IMPLEMENTS, etc.
   - "**Some Valid Path Examples**"
   - LLM thinks: "These are available patterns"

3. **Actual schema JSON:** Only CONTAINS and CALLS
   - "**ACTUAL SCHEMA** (use this as source of truth)"
   - LLM sees: Limited relationship set
   - But already primed by examples showing more

4. **Approach goal:** "instantiate Type nodes"
   - LLM training: instantiation = REFERENCES
   - Semantic priming overrides schema constraints

5. **Soft warning:** "⚠️ DO NOT invent relationships not in schema"
   - Advisory tone, not enforced
   - LLM rationalizes: "REFERENCES is semantically correct for instantiation"

### Result:
LLM generates `-[:REFERENCES]->` even though:
- REFERENCES not in extracted schema (only CONTAINS, CALLS)
- REFERENCES not in approach relationships (empty)
- But: Primed by static examples + semantic goal + training knowledge

---

## Root Causes Identified

### Issue #1: Static Schema Examples (HIGH IMPACT)
**Location:** `adaptive_query_agent.py:1127-1171`

**Problem:**
- Hardcoded examples showing ALL relationships (INHERITS_FROM, IMPLEMENTS, etc.)
- NOT filtered by `self.state.schema['relationships']`
- Contradicts actual extracted schema

**Fix Options:**
1. **Remove examples entirely** - rely only on extracted schema
2. **Filter examples dynamically** - only show patterns using available relationships
3. **Generate examples from cardinality** - build from `self.state.schema['relationships']`

### Issue #2: Weak Schema Constraint (MEDIUM IMPACT)
**Location:** `prompts.py:181`

**Problem:**
- "⚠️ DO NOT invent" is advisory, not enforced
- Ambiguous "not in schema" - which schema?
- No validation step required

**Fix Options:**
1. **Stronger language:** "YOU CANNOT" instead of "DO NOT"
2. **Explicit allowlist:** "✅ Available: CONTAINS, CALLS" + "❌ NOT available: anything else"
3. **Validation step:** Require explicit relationship check before query generation

### Issue #3: No Error Return Path (LOW IMPACT)
**Location:** `prompts.py:213-224`

**Problem:**
- Format forces query generation
- No option to say "insufficient schema"

**Fix Options:**
1. Add optional error field
2. Make cypher_query nullable
3. Require schema validation in output

---

## Recommended Fixes (Priority Order)

### Priority 1: Fix Static Examples (Quick Win)
**Change:** Make `_build_schema_path_examples()` use `self.state.schema['relationships']`

**Before:**
```python
def _build_schema_path_examples(self) -> str:
    return f"""
    5. **Type node relationships**:
       MATCH (child:Type)-[:INHERITS_FROM]->(parent:Type)
    """
```

**After:**
```python
def _build_schema_path_examples(self) -> str:
    available_rels = self.state.schema.get('relationships', {})

    # Only show examples for available relationships
    examples = []

    if 'CONTAINS' in available_rels:
        examples.append("Project-[:CONTAINS]->File-[:CONTAINS]->Type")

    if 'CALLS' in available_rels:
        examples.append("Function-[:CALLS]->Function")

    if 'INHERITS_FROM' in available_rels:  # Only if extracted!
        examples.append("Type-[:INHERITS_FROM]->Type")

    return format_dynamic_examples(examples)
```

### Priority 2: Add Explicit Allowlist
**Change:** In `prompts.py`, format relationships as explicit allowlist

**Before:**
```python
**ACTUAL SCHEMA** (use this as source of truth):
- Relationships: {json.dumps(relationships)}
```

**After:**
```python
🔓 AVAILABLE RELATIONSHIPS (YOU MAY ONLY USE THESE):
✅ CONTAINS - (see cardinality below)
✅ CALLS - (see cardinality below)

❌ YOU MAY NOT USE: REFERENCES, DECLARES, INHERITS_FROM, or ANY other relationship
   (They are NOT in the extracted schema for this query)

Detailed Cardinality:
{format_with_cardinality(relationships)}
```

### Priority 3: Strengthen Constraint Language
**Change:** In Step 2, make validation mandatory

**Before:**
```python
Step 2 - TRACE PATH:
- ⚠️ DO NOT invent relationships not in schema
```

**After:**
```python
Step 2 - VALIDATE RELATIONSHIPS:
- First, CHECK: Is each relationship in "AVAILABLE RELATIONSHIPS" above?
- If ANY relationship is NOT in that list, STOP and return error
- Only proceed if ALL relationships are available
```

---

## Testing Plan

1. **Test with current code:**
   - Run workflow
   - Capture actual prompt sent to LLM
   - Verify static examples show unavailable relationships

2. **Test with dynamic examples:**
   - Modify `_build_schema_path_examples()` to filter
   - Re-run workflow
   - Check if LLM still hallucinates REFERENCES

3. **Test with allowlist format:**
   - Modify prompt formatting
   - Re-run workflow
   - Check compliance with constraints

4. **Measure impact:**
   - Compare token usage (before/after)
   - Compare query success rate
   - Compare approach utilization (2/3 vs 3/3)
