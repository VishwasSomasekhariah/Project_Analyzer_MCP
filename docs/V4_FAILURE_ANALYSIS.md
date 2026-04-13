# V4 Benchmark Failure Analysis - Runs 1 & 3

## Executive Summary

Runs 1 and 3 both failed due to **schema validation failures** during query generation, NOT due to entity name issues. The entity diagnostics feature worked correctly but wasn't relevant to these failures.

---

## Root Cause: Schema Validation Failure

### What Happened

**Run 1 - SQ2 (Subquery 2) Failure:**
```
2025-11-19 21:04:36,840 - ERROR - ❌ Schema validation failed after 2 retries
Failed Query: MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)-[:REFERENCES]->(t:Type) RETURN s, s.text
Validation Error: (Statement)-[:REFERENCES]->(Type): Invalid relationship: REFERENCES cannot connect Statement to Type
```

**Run 3 - SQ2 (Subquery 2) Failure:**
```
2025-11-19 21:06:52,740 - ERROR - ❌ Schema validation failed after 2 retries
Failed Query: MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)-[:REFERENCES]->(t:Type) RETURN s
Validation Error: (Statement)-[:REFERENCES]->(Type): Invalid relationship: REFERENCES cannot connect Statement to Type
```

### The Problem

1. **Invalid Relationship Path**: The LLM tried to use `Statement-[:REFERENCES]->Type` which doesn't exist in the CPG schema

2. **Schema Constraints**: According to the schema, `REFERENCES` can only connect:
   - `Type -> Type`
   - `Variable -> Type`
   - `Function -> Type`
   - `Variable -> Variable`
   - `Variable -> Function`

   But **NOT** `Statement -> Type`

3. **Retry Mechanism Failed**: The agent retried 2 times with schema feedback but couldn't generate a valid alternative

4. **Premature Termination**: After 2 failed retries, the agent gave up and stopped query generation for that approach

---

## Why Run 4 Succeeded

**Run 4 - SQ2 Generated a VALID Query:**
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s.text
```

**Key Difference:**
- ✅ Did NOT try to traverse `Statement-[:REFERENCES]->Type`
- ✅ Simply returned the Statement text with filtering
- ✅ Passed schema validation on first attempt
- ✅ Found the correct answer: "new WorkerA, WorkerB, WorkerC"

---

## Detailed Execution Flow

### Run 1 (Failed)

**Approach Execution:**
- **SQ1**: ✅ Executed 1 query, found CreateWorkers function
- **SQ2**: ❌ Failed to generate valid query after 2 retries → 0 queries executed
- **SQ3**: ❌ Failed to generate valid query after 2 retries → 0 queries executed

**Final State:**
- Total queries: 1
- Total data points: 1
- Final answer: INCOMPLETE - "The specific classes... could not be determined"

### Run 3 (Failed)

**Approach Execution:**
- **SQ1**: ✅ Executed 1 query, found CreateWorkers function
- **SQ2**: ❌ Failed to generate valid query after 2 retries → 0 queries executed
- **SQ3**: ✅ Executed 1 query using `Function-[:REFERENCES]->Type` (valid path)

**Final State:**
- Total queries: 2
- Total data points: 2 (from SQ1 and SQ3)
- Final answer: INCOMPLETE - Found "WorkerFactory" type but missed the instantiated worker classes

---

## Analysis: Why Did Schema Validation Fail?

### 1. LLM Misunderstanding of Schema

The LLM **incorrectly assumed** that:
- Statement nodes could have REFERENCES relationships to Type nodes
- This would allow finding which Types are instantiated in a Statement

**Reality:**
- Statement nodes don't directly reference Types
- To find instantiations, you need to:
  1. Get the Statement text (`s.text`)
  2. Parse the text for class names (e.g., "new WorkerA")
  OR
  3. Traverse Statement → Variable → Type (if Variables exist)

### 2. Insufficient Schema Understanding in Prompts

The LLM received schema feedback showing valid REFERENCES paths:
```
💡 Suggestion: To reach Type:
  (Function)-[:REFERENCES]->(Type)
  (Type)-[:REFERENCES]->(Type)
  (Variable)-[:REFERENCES]->(Type)
```

But **failed to adapt** and kept trying the same invalid pattern.

### 3. Retry Logic Limitation

**Current Behavior:**
- Max 2 retries for schema validation
- After 2 failures → Give up completely
- No fallback to alternative query strategies

**Should Be:**
- After validation failures, try fundamentally different approach
- Consider text-based filtering instead of relationship traversal
- Don't give up on the entire approach after query generation fails

---

## Why Entity Diagnostics Weren't Relevant

The entity diagnostics feature (checking if entity names exist) was **not triggered** because:

1. **No Empty Results from Valid Queries**: The failures happened during query **generation**, not execution
2. **No Entity Constraints Declared**: Failed queries never got to the point of declaring entity constraints
3. **Schema Issues, Not Data Issues**: The problem was invalid relationship paths, not missing entity names

**Conclusion**: Entity diagnostics are working correctly but address a different failure mode (wrong entity names in otherwise valid queries).

---

## Comparison: V3 vs V4

### V3 Benchmark (Before Entity Diagnostics)
- Success Rate: 2/5 runs (40%)
- Failure Mode: Schema validation issues + entity name issues

### V4 Benchmark (With Entity Diagnostics)
- Success Rate: 2/5 runs (40%)
- Failure Mode: Same schema validation issues
- Entity Diagnostics: Working but not triggered

**Conclusion**: No regression. Entity diagnostics didn't help because the failures were due to schema violations, not entity names.

---

## Recommendations

### 1. Improve Schema Validation Retry Logic

**Current:**
```python
max_retries = 2  # Give up after 2 failures
```

**Proposed:**
```python
# Try different query strategies if schema validation fails
strategies = [
  "use_references_path",  # Try Statement->Variable->Type
  "use_text_filtering",   # Get Statement.text and filter
  "use_calls_path"        # Try Function->CALLS->Function->REFERENCES->Type
]
```

### 2. Enhance Prompt for Schema Awareness

Add to query generation prompt:
```
CRITICAL SCHEMA RULES:
- Statement nodes DO NOT have REFERENCES relationships to Types
- To find instantiated types from Statements:
  Option 1: Get Statement.text and filter for 'new ClassName'
  Option 2: Traverse Statement -> Variable -> Type (if Variables exist)
  Option 3: Use Function -> CALLS -> Function -> REFERENCES -> Type
```

### 3. Add Fallback Query Strategy

If query generation fails after retries:
1. Don't give up on the approach entirely
2. Try a simpler query (e.g., just get Statement text)
3. Log the failure but continue with partial data

### 4. Improve LLM Feedback Loop

When schema validation fails:
- Show **example working queries** for similar patterns
- Highlight **why** the suggested path is wrong
- Provide **concrete alternative** query templates

---

## Conclusion

**The Real Problem:** LLM's inability to generate schema-valid queries for Statement→Type traversal, combined with giving up too easily after validation failures.

**Not the Problem:** Entity name issues (entity diagnostics are working but weren't needed here).

**Fix Priority:**
1. High: Improve query generation prompt with explicit schema patterns
2. High: Add fallback query strategies when validation fails
3. Medium: Increase retry limit or use different strategies per retry
4. Low: Entity diagnostics are already working correctly
