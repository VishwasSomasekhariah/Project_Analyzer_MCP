# Root Cause Analysis: Fake Cypher Queries in Run 4

## The Problem

In Run 4, the LLM generated these syntactically valid but semantically useless queries:

```cypher
MATCH (f:Function {name: 'CreateWorkers'})
RETURN 'Schema does not support direct instantiation tracing.'
```

```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CALLS]->(callee:Function)
RETURN 'Schema does not support direct instantiation tracing.'
```

These queries execute successfully in Neo4j but return hardcoded strings instead of actual data.

## Investigation Timeline

### 1. Initial Discovery

From `benchmark_createworkers_with_query_feedback.log` lines 1101-1105:
```
2025-11-14 15:56:00,445 - WARNING - ⚠️ Schema validation failed (attempt 2)
2025-11-14 15:56:00,445 - INFO - 🔄 Retrying with schema validation feedback...
2025-11-14 15:56:01,535 - INFO - ✅ Query passed schema validation
2025-11-14 15:56:01,535 - INFO - 🔍 Generated Query (attempt 3): MATCH (f:Function {name: 'CreateWorkers'}) RETURN 'Schema does not support...
```

**Key Finding**: The fake query was generated on **attempt 3** after **TWO validation failures**.

### 2. LLM's Reasoning (from Run 4 JSON output)

```json
{
  "step3_path_trace": "Since there is no direct relationship between Function and Type,
                       and the schema only provides CALLS between Function nodes,
                       we cannot directly trace instantiations.
                       We need additional schema information to find a valid path."
}
```

**The LLM concluded**:
1. No direct relationship between Function and Type exists
2. Only CALLS relationship is available
3. Therefore, it's impossible to answer the query
4. Returns a hardcoded message expressing this limitation

### 3. The Contradiction

**From the user's Neo4j query**:
```cypher
MATCH (fn)-[:IMPLEMENTS]->(ty) RETURN fn.name, fn.type, ty.name, ty.type
```

**Results include**:
| fn.name | fn.type | ty.name | ty.type |
|---------|---------|---------|---------|
| "CreateWorkers" | "Function" | "WorkerFactory" | "Type" |
| "Notify" | "Function" | "INotifier" | "Type" |
| "Main" | "Function" | "Program" | "Type" |

**Proof**: `(Function)-[:IMPLEMENTS]->(Type)` **DOES EXIST** with multiple instances!

**From the log** (line showing schema extraction for SQ3):
```
🎯 Extracted for subquery: nodes=['Function', 'Type', 'Namespace', 'File'],
                           rels=['CALLS', 'CONTAINS', 'IMPLEMENTS']
```

**The schema manager** included IMPLEMENTS in the relationship list!

### 4. The Root Cause Hypothesis

There are three possible explanations:

#### A) Schema Filtering Bug (Most Likely)

The schema's `relationship_schemas` dictionary had IMPLEMENTS but with **incomplete cardinality**:

```python
# What SHOULD be in the schema:
relationship_schemas = {
    'IMPLEMENTS': {
        'cardinality': [
            {'from': 'Function', 'to': 'Type'},      # ← THIS WAS MISSING OR FILTERED OUT
            {'from': 'Type', 'to': 'Type'},
            ...
        ],
        'description': '...',
        'properties': [...],
        'count': 38
    }
}
```

**Evidence**:
- Schema manager logged: `rels=['IMPLEMENTS']` ✅
- LLM said: "schema only provides CALLS between Function nodes" ❌
- This mismatch suggests cardinality was incomplete

**Code Path** (from `dynamic_schema_manager.py:1541-1544`):
```python
relationship_schemas = {}
for rel_type in relationship_types:
    if rel_type in self._reconciled_schema.get('relationships', {}):
        relationship_schemas[rel_type] = self._reconciled_schema['relationships'][rel_type]
```

The cardinality comes from `self._reconciled_schema` which is built by `_reconcile_schemas()` (lines 415-497).

Cardinality is populated from `self._valid_rel_pairs` (line 490):
```python
reconciled['relationships'][rel_type] = {
    'description': self._extract_relationship_description(rel_type),
    'cardinality': valid_pairs,  # ← From self._valid_rel_pairs
    'properties': [...],
    'count': count
}
```

**Potential Bug**: The `_valid_rel_pairs` is fetched by a query (lines 400-413) that might:
1. Filter out certain pairs
2. Have incorrect WHERE clauses
3. Return incomplete results due to timing issues

#### B) JSON Format Too Complex

The schema is dumped as JSON (from `prompts.py:138`):
```python
rel_summary = json.dumps(relationships, indent=2)
```

If cardinality is large/complex, the LLM might:
1. Miss the (Function, Type) pair in a long list
2. Misparse the JSON structure
3. Give up and conclude it doesn't exist

#### C) LLM Reasoning Error

The LLM saw the correct schema but failed to use it properly due to:
1. Prompt ambiguity
2. Confusion from prior validation failures
3. Learned pattern from validation feedback

### 5. Why No RETURN 'message' Precedent?

Searched entire codebase:
- ✅ No examples of `RETURN 'hardcoded string'` in prompts
- ✅ No examples in code
- ✅ No guidance suggesting this pattern

**Conclusion**: The LLM invented this pattern on its own as a way to express "I can't answer this query with the given schema."

### 6. Validation Feedback Loop

The log shows the LLM failed validation **twice** before generating the fake query:

**Attempt 1**: Failed validation (unknown query)
**Attempt 2**: Failed validation (unknown query)
**Attempt 3**: Generated fake query (passed validation because it's syntactically valid)

**Critical Issue**: The validation feedback told the LLM about schema violations but didn't suggest:
1. Statement.text filtering as a fallback
2. That hardcoded RETURN strings are not acceptable

From `adaptive_query_agent.py:483-508`, the validation feedback says:

```python
validation_feedback = f"""SCHEMA VALIDATION ERRORS:

YOUR PREVIOUS CYPHER QUERY:
```cypher
{result.cypher_query}
```

ERRORS FOUND:
{chr(10).join(error_messages)}

🚨 YOUR QUERY VIOLATES THE SCHEMA'S CARDINALITY RULES
...
TO FIX THIS:
1. Locate the "Relationships" section in the schema below
2. Find the relationship type you attempted to use
3. Check the valid (from, to) pairs for that relationship
4. If your desired (source → target) pair is not listed, you MUST use a multi-hop path
```

**Missing**:
- No mention of Statement.text fallback
- No prohibition of hardcoded RETURN strings
- Assumes a valid path exists (but what if it doesn't?)

### 7. Why Run 1 Succeeded

Run 1 generated this query on its first or second attempt:
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)
      -[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s.text
```

**Key difference**: Run 1 discovered the Statement.text filtering strategy without being told.

## Summary

### Direct Cause
After failing validation twice, the LLM concluded that the schema was insufficient to answer the query and generated a syntactically valid query that returns a hardcoded error message.

### Root Cause (Most Likely)
The schema's IMPLEMENTS relationship had incomplete cardinality - missing the (Function, Type) pair despite it existing in Neo4j. This made the LLM believe no valid path existed.

### Contributing Factors
1. **Schema filtering bug**: `_valid_rel_pairs` might not include all actual pairs
2. **No fallback guidance**: Validation feedback doesn't suggest Statement.text filtering
3. **No prohibition**: Nothing prevents hardcoded RETURN strings
4. **Non-deterministic success**: Run 1 succeeded by luck, not by design

## Impact

**Failure Rate**: 60% (3 out of 5 runs failed to find the answer)
- Run 1: ✅ Success (Statement.text filtering)
- Run 2: ❌ Failed (tried IMPLEMENTS, got WorkerFactory not WorkerA/B/C)
- Run 3: ✅ Success (CALLS relationship)
- Run 4: ❌ Failed (fake queries)
- Run 5: ❌ Failed (tried IMPLEMENTS, empty results)

## Recommended Fixes

### 1. Add Logging to Verify Schema Content (Immediate)

In `adaptive_query_agent.py` around line 256, after building `self.state.schema`:

```python
# DEBUG: Log the actual schema being sent to LLM
if 'IMPLEMENTS' in self.state.schema.get('relationships', {}):
    impl = self.state.schema['relationships']['IMPLEMENTS']
    cardinality = impl.get('cardinality', [])
    func_to_type = [c for c in cardinality if c.get('from') == 'Function' and c.get('to') == 'Type']
    logger.info(f"  🔍 IMPLEMENTS cardinality has {len(cardinality)} pairs, (Function→Type): {len(func_to_type)}")
```

### 2. Add Statement.text Fallback to Prompt (Critical)

In `prompts.py` around line 236-242, add:

```python
CRITICAL FALLBACK STRATEGY:
If no relationship path exists in the schema, query node TEXT/VALUE properties:
- For instantiations: (Function)-[:CONTAINS]->(Block)-[:CONTAINS]->(Statement) WHERE s.text CONTAINS 'new ClassName'
- For method calls: WHERE s.text CONTAINS 'methodName('
- For references: Query Expression.value or Statement.text fields

❌ NEVER return hardcoded strings like RETURN 'Schema does not support...'
   Always query actual graph data using valid relationships OR property filters.
```

### 3. Prohibit Hardcoded RETURN Strings (Critical)

In `cypher_query_validator.py`, add a validation check:

```python
def validate_return_clause(self, cypher: str) -> List[ValidationIssue]:
    """Validate that RETURN clause doesn't contain hardcoded strings"""
    issues = []

    # Check for RETURN 'string' or RETURN "string" pattern
    if re.search(r"RETURN\s+['\"].*['\"]", cypher, re.IGNORECASE):
        issues.append(ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="RETURN clause contains hardcoded string instead of graph data",
            location="RETURN clause",
            suggestion="Return actual node properties, relationship data, or aggregations - never hardcoded strings"
        ))

    return issues
```

### 4. Fix Schema Cardinality Bug (Required)

Investigate `dynamic_schema_manager.py:400-413` to ensure `_valid_rel_pairs` includes ALL actual pairs from Neo4j.

Add comprehensive logging:
```python
# After line 411
logger.debug(f"📊 Relationship {rel_type}: {len(pairs)} cardinality pairs")
if rel_type == 'IMPLEMENTS':
    func_pairs = [p for p in pairs if p['from'] == 'Function']
    logger.info(f"  IMPLEMENTS from Function: {len(func_pairs)} pairs")
```

## Next Steps

1. **Run diagnostic logging** to confirm schema cardinality issue
2. **Add Statement.text fallback** to prompts immediately
3. **Add hardcoded RETURN validation** to prevent fake queries
4. **Fix schema filtering** if cardinality is confirmed incomplete
5. **Re-run benchmark** to verify 100% success rate
