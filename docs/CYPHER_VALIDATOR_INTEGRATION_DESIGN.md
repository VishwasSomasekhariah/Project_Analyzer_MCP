# Cypher Validator Integration Design

## Overview

Integration of the Cypher Query Validator into the CoT Agent's generate and analyze steps to:
1. **Generate Step**: Catch invalid queries before Neo4j execution
2. **Analyze Step**: Distinguish between "data doesn't exist" vs "tried wrong path"

---

## Part 1: Generate Step Integration (Error Prevention)

### Current Flow
```
LLM generates query → Pydantic validation → Duplicate check → Execute on Neo4j
```

### Enhanced Flow
```
LLM generates query → Pydantic validation → Duplicate check → Schema validation → Execute on Neo4j
                                                                      ↓ (if invalid)
                                                              Retry with feedback
```

### Implementation

**Location:** `adaptive_query_agent.py:_cot_generate_query_step()` line 442-468

**Code:**
```python
# After duplicate check passes (line 458)

# Validate Cypher query against schema
if self.schema_manager:
    from .cypher_query_validator import CypherQueryValidator

    validator = CypherQueryValidator(self.schema_manager._reconciled_schema)
    validation_result = validator.validate(result.cypher_query)

    if not validation_result.is_valid:
        if attempt < max_retries:
            # Build error feedback for LLM
            error_messages = []
            for issue in validation_result.get_errors():
                error_messages.append(f"  ❌ {issue.location}: {issue.message}")
                if issue.suggestion:
                    error_messages.append(f"     💡 {issue.suggestion}")

            validation_feedback = f"""Your generated Cypher query has schema validation errors:

{chr(10).join(error_messages)}

Please regenerate the query fixing these issues. Ensure:
1. All node labels exist in the schema
2. All relationship types are valid between the specified node types
3. All properties exist on the correct node types
4. Follow the relationship cardinality rules from the schema
"""
            logger.warning(f"    ⚠️ Schema validation failed (attempt {attempt + 1})")
            logger.info(f"    🔄 Retrying with validation feedback...")
            continue
        else:
            logger.error(f"    ❌ Schema validation failed after {max_retries} retries")
            return None
    else:
        logger.info(f"    ✅ Query passed schema validation")

# Proceed to line 468: return result.dict()
```

---

## Part 2: Analyze Step Enhancement (Smart Guidance)

### The Problem: Ambiguous Empty Results

When a query returns empty results, the analyze step currently cannot distinguish:

**Scenario A: Data Doesn't Exist**
- Query: `MATCH (f:Function {name: 'NonExistentFunction'}) RETURN f`
- Schema: ✅ Valid (Function.name exists)
- Result: Empty
- **Reason**: No function with that name in codebase
- **Action**: STOP trying, mark as "not found"

**Scenario B: Query Used Wrong Path**
- Query: `MATCH (f:File)-[:CONTAINS]->(func:Function) RETURN func`
- Schema: ❌ Invalid (File cannot directly contain Function)
- Result: Empty
- **Reason**: Invalid relationship path
- **Action**: CONTINUE with corrected path

**Scenario C: Query Valid But Wrong Filters**
- Query: `MATCH (f:Function) WHERE f.name =~ '.*Worker' RETURN f`
- Schema: ✅ Valid
- Result: Empty
- **Reason**: No functions match the regex pattern
- **Action**: Try different filters or stop

### The Solution: Pass Validation Metadata

**Enhanced execution result structure:**
```python
execution_result = {
    'success': True,
    'results': [],
    'error': None,

    # NEW: Add validation metadata
    'validation': {
        'is_valid': True,  # Was the query structurally valid?
        'attempted_paths': [  # What paths did query try?
            ('File', 'CONTAINS', 'Function'),  # Invalid!
            ('Type', 'CONTAINS', 'Function')    # Valid
        ],
        'attempted_filters': [  # What filters were used?
            ('Function', 'name', '.*Worker')
        ],
        'validation_issues': [  # Any schema issues?
            {
                'severity': 'ERROR',
                'message': 'Invalid relationship: CONTAINS cannot connect File to Function',
                'suggestion': 'Valid patterns: (File)-[:CONTAINS]->(Type), (Type)-[:CONTAINS]->(Function)'
            }
        ]
    }
}
```

### Enhanced Analyze Prompt

**Add to prompt** (after line 300 in prompts.py):

```python
{'**QUERY VALIDATION CONTEXT**:' if execution_result.get('validation') else ''}
{self._format_validation_context(execution_result.get('validation')) if execution_result.get('validation') else ''}
```

**Helper method:**
```python
def _format_validation_context(validation: Dict) -> str:
    """Format validation metadata for analyze prompt."""
    if not validation:
        return ""

    parts = []

    # Schema validity
    if validation.get('is_valid'):
        parts.append("- Query Structure: ✅ Valid (follows schema rules)")
    else:
        parts.append("- Query Structure: ❌ Invalid (violates schema rules)")
        for issue in validation.get('validation_issues', []):
            parts.append(f"  • {issue['message']}")
            if issue.get('suggestion'):
                parts.append(f"    💡 {issue['suggestion']}")

    # Attempted paths
    paths = validation.get('attempted_paths', [])
    if paths:
        parts.append("\n- Relationship Paths Attempted:")
        for from_label, rel_type, to_label in paths:
            parts.append(f"  • ({from_label})-[:{rel_type}]->({to_label})")

    # Attempted filters
    filters = validation.get('attempted_filters', [])
    if filters:
        parts.append("\n- Filters Applied:")
        for label, prop, value in filters:
            parts.append(f"  • {label}.{prop} = {value}")

    return '\n'.join(parts)
```

### Enhanced Analyze Instructions

**Update prompt section** (line 304-316 in prompts.py):

```python
**ANALYZE**:

If QUERY WAS INVALID (validation issues present):
- The empty result is EXPECTED because the query violated schema rules
- DO NOT interpret this as "data doesn't exist"
- Recommendation: REFINE with corrected schema relationships
- next_query_hint: Suggest valid alternative paths from validation suggestions

If QUERY WAS VALID but returned EMPTY:
- The query structure was correct, but no data matched
- Check attempted paths and filters:
  • If path was very specific → Try broader relationship traversal
  • If filters were strict → Try relaxed filters or different properties
  • If you've tried multiple valid paths → Data likely doesn't exist
- Consider: Have we exhausted all reasonable query perspectives?

If QUERY WAS VALID and returned DATA:
- Analyze findings for relevance to subquery
- Assess if we need additional perspectives

Recommendation Guidelines:
- Continue: More valid query perspectives to try
- Sufficient: Found relevant data, no more queries needed
- Refine: Query had validation errors, fix and retry
- Stop: Exhausted all valid paths, data doesn't exist
```

---

## Integration Workflow Example

### Scenario: Looking for function "WorkerFactory.CreateWorkers()"

**Iteration 1: Invalid Path**
```
Generate: MATCH (file:File)-[:CONTAINS]->(f:Function {name: 'CreateWorkers'}) RETURN f
Validate: ❌ INVALID - File-[:CONTAINS]->Function violates cardinality
Action:   RETRY with corrected path
```

**Iteration 2: Corrected Path**
```
Generate: MATCH (file:File)-[:CONTAINS]->(t:Type)-[:CONTAINS]->(f:Function {name: 'CreateWorkers'}) RETURN f
Validate: ✅ VALID
Execute:  Empty result
Analyze:  "Query was valid but no results. Tried File→Type→Function path with exact name match.
           This is a valid path, so data either doesn't exist OR filter is too strict."
Recommend: CONTINUE - Try relaxed filter (e.g., name contains 'CreateWorkers')
```

**Iteration 3: Relaxed Filter**
```
Generate: MATCH (t:Type)-[:CONTAINS]->(f:Function) WHERE f.name =~ '.*CreateWorkers.*' RETURN f
Validate: ✅ VALID
Execute:  Found 1 result
Analyze:  "Found function with relaxed filter. Full qualified name was 'WorkerFactory.CreateWorkers()'."
Recommend: SUFFICIENT
```

### Scenario: Looking for non-existent function "DeleteAllData()"

**Iteration 1-3**: Try multiple valid paths and filter combinations, all return empty

**Iteration 4: Analysis**
```
Analyze: "We've tried:
  1. File→Type→Function path with exact name
  2. Direct Function search with contains filter
  3. Namespace→Type→Function path

  All queries were schema-valid but returned empty.
  We've exhausted reasonable query perspectives."
Recommend: STOP - Data doesn't exist in codebase
```

---

## Benefits of This Design

### 1. Prevent Wasted Iterations
- Invalid queries caught before Neo4j execution
- No need to "learn" schema rules through trial-and-error

### 2. Smart Empty Result Interpretation
```
Query Invalid → Empty is EXPECTED → Don't interpret as "data missing"
Query Valid   → Empty is REAL     → Meaningful signal for decision-making
```

### 3. Exhaustion Detection
Track attempted perspectives:
```python
attempted_paths_history = [
    ('File', 'CONTAINS', 'Type', 'CONTAINS', 'Function'),
    ('Namespace', 'CONTAINS', 'Type', 'CONTAINS', 'Function'),
    ('Type', 'CONTAINS', 'Function'),
    # ... all failed with valid queries
]
# → Can confidently say "data doesn't exist"
```

### 4. Actionable Guidance
```
"Query failed validation: Statement-[:IMPLEMENTS]->Type not allowed.
 Valid alternatives: Function-[:IMPLEMENTS]->Type, Type-[:IMPLEMENTS]->Type"
```
vs.
```
"Query returned empty, try something else."  # Vague, unhelpful
```

---

## Implementation Checklist

### Phase 1: Generate Step (High Priority)
- [ ] Add validator import in `adaptive_query_agent.py`
- [ ] Insert validation check after duplicate detection
- [ ] Build validation feedback for LLM retry
- [ ] Test with known invalid queries (Statement-IMPLEMENTS->Type)

### Phase 2: Analyze Step (High Value)
- [ ] Update `execution_result` dict to include validation metadata
- [ ] Add `_format_validation_context()` helper to prompts.py
- [ ] Update analyze prompt with validation context section
- [ ] Update analyze instructions to distinguish invalid vs valid-but-empty

### Phase 3: State Tracking (Future Enhancement)
- [ ] Track attempted paths across iterations
- [ ] Detect when all valid paths exhausted
- [ ] Add "exhaustion" recommendation type

---

## Expected Impact

**Metrics to Track:**
- Reduction in failed queries (invalid → caught early)
- Reduction in iterations to find data
- Improvement in "data doesn't exist" accuracy
- Reduction in false positives (empty due to invalid query vs truly missing)

**Estimated Improvements:**
- 40-55% of queries caught before execution (based on validator benchmark)
- 2-3 fewer iterations per approach (avoid invalid path attempts)
- Better stop/continue decisions (validation context guides analysis)
