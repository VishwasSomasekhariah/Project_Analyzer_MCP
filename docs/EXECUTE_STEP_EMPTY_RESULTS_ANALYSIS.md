# Execute Step: Empty Results Handling - Current vs Enhanced

## Current Flow (Lines 544-634)

### How Empty Results Are Handled Today

```python
async def _execute_query(self, cypher_query: str) -> Dict[str, Any]:
    # 1. Execute query on Neo4j
    response = await self.cypher_server.execute_query(cypher_query)

    # 2. Check for errors
    if error:
        if is_syntax_error:
            return {'results': [], 'error': error, 'success': False}
        else:
            # Non-syntax error → APOC validation
            validation_result = await self._validate_premises_with_apoc(error=error)
            return {'results': [], 'error': error, 'premise_validations': ...}

    # 3. Handle empty results (Line 602-619)
    if len(results) == 0:
        logger.info(f"🔬 Empty result, running APOC validation...")
        validation_result = await self._validate_premises_with_apoc(empty_result=True)

        # Determine if NOT_FOUND (premises valid) vs INSUFFICIENT_DATA (premises invalid)
        all_validated = all(v['status'] == 'validated' for v in validation_result['premise_validations'])
        sufficiency_status = 'NOT_FOUND' if all_validated else 'INSUFFICIENT_DATA'

        return {
            'results': [],
            'success': True,
            'sufficiency_status': sufficiency_status,
            'premise_validations': validation_result['premise_validations'],
            'apoc_diagnostics_used': True
        }

    # 4. Success with results
    return {'results': results, 'success': True}
```

### What Information Is Available

**From APOC validation (premise-based):**
- `premise_validations`: Array of premise validation results
- `sufficiency_status`: 'NOT_FOUND' or 'INSUFFICIENT_DATA'
- Tells us: Are the premises (assumptions) in the query correct?

**Example:**
```python
# Query: Find function 'CreateWorkers' in type 'WorkerFactory'
# Empty result

APOC checks:
- Does type 'WorkerFactory' exist? → Yes ✅
- Does function 'CreateWorkers' exist? → No ❌

Result: sufficiency_status = 'NOT_FOUND'
Interpretation: Query was correct, data just doesn't exist
```

---

## The Problem: Missing Schema Validation Context

### Current Limitation

The APOC validation checks **premises** (assumptions about what exists), but doesn't know if the **query structure** was valid.

**Example Scenario:**

```python
# Query: (File)-[:CONTAINS]->(Function {name: 'CreateWorkers'})
# Empty result

APOC validation:
- Does File exist? → Yes ✅
- Does Function 'CreateWorkers' exist? → Yes ✅

Current conclusion: sufficiency_status = 'NOT_FOUND'
WRONG! The query was schema-invalid. File cannot directly contain Function.
```

### What's Missing

We need to know:
1. **Was the query schema-valid?** (from validator in generate step)
2. **If invalid, what was wrong?** (relationship paths, properties)
3. **If valid, what did we actually try?** (for tracking exhaustion)

---

## Enhanced Flow: Add Validation Context

### Proposal: Pass Validation Info to Execute Result

**In `_cot_generate_query_step()` (Line 460-498):**

```python
# After validation passes (line 498):
validation_metadata = {
    'is_valid': schema_validation.is_valid,
    'attempted_paths': [
        (from_label, rel_type, to_label)
        for from_label, rel_type, to_label in schema_validation.extracted_relationships
    ],
    'attempted_filters': [
        (alias, label, prop)
        for alias, label, prop in schema_validation.extracted_properties
    ],
    'validation_issues': [
        {
            'severity': issue.severity.value,
            'message': issue.message,
            'location': issue.location,
            'suggestion': issue.suggestion
        }
        for issue in schema_validation.issues
    ]
}

# Store in result dict
return {
    **result.dict(),
    'validation_metadata': validation_metadata  # NEW
}
```

**In `_execute_query()` - pass through to execution result:**

```python
async def _execute_query(self, cypher_query: str, validation_metadata: Optional[Dict] = None) -> Dict[str, Any]:
    # ... existing code ...

    # Handle empty results with enhanced context
    if len(results) == 0:
        logger.info(f"🔬 Empty result, analyzing...")

        # Check if query was schema-valid
        if validation_metadata and not validation_metadata.get('is_valid'):
            # Query was INVALID - empty is expected!
            logger.info(f"    ⚠️ Query violated schema, empty result expected")
            return {
                'results': [],
                'success': True,
                'sufficiency_status': 'SCHEMA_INVALID',  # NEW status
                'validation_metadata': validation_metadata,
                'interpretation': 'Query structure violated schema rules. Empty result expected.'
            }

        # Query was valid - run APOC to check premises
        logger.info(f"    ✅ Query was schema-valid, checking premises...")
        validation_result = await self._validate_premises_with_apoc(empty_result=True)

        all_validated = all(v['status'] == 'validated' for v in validation_result['premise_validations'])
        sufficiency_status = 'NOT_FOUND' if all_validated else 'INSUFFICIENT_DATA'

        return {
            'results': [],
            'success': True,
            'sufficiency_status': sufficiency_status,
            'premise_validations': validation_result['premise_validations'],
            'validation_metadata': validation_metadata,  # Include for analyze step
            'apoc_diagnostics_used': True,
            'interpretation': 'Query was schema-valid. Premises checked with APOC.'
        }
```

---

## New Sufficiency Status: SCHEMA_INVALID

### Three-Way Classification

**Before (2 states):**
- `NOT_FOUND`: Premises valid, data doesn't exist
- `INSUFFICIENT_DATA`: Premises invalid, query assumptions wrong

**After (3 states):**
- `SCHEMA_INVALID`: Query violated schema rules (NEW!)
- `NOT_FOUND`: Schema valid, premises valid, data doesn't exist
- `INSUFFICIENT_DATA`: Schema valid, premises invalid

### Decision Tree

```
Empty Result
    ├─ Was query schema-valid?
    │   ├─ NO → SCHEMA_INVALID (don't count as attempt)
    │   └─ YES → Check premises with APOC
    │       ├─ All premises valid → NOT_FOUND (data doesn't exist)
    │       └─ Some premises invalid → INSUFFICIENT_DATA (wrong assumptions)
```

---

## Benefits for Analyze Step

### Before: Ambiguous Empty Results

```python
# Analyze step receives:
execution_result = {
    'results': [],
    'sufficiency_status': 'NOT_FOUND',
    'premise_validations': [...]
}

# Analysis must guess:
"Empty result - was the query valid? Should we try different path?"
```

### After: Clear Context

```python
# Analyze step receives:
execution_result = {
    'results': [],
    'sufficiency_status': 'SCHEMA_INVALID',  # or NOT_FOUND, INSUFFICIENT_DATA
    'validation_metadata': {
        'is_valid': False,
        'attempted_paths': [('File', 'CONTAINS', 'Function')],
        'validation_issues': [{
            'message': 'CONTAINS cannot connect File to Function',
            'suggestion': 'Valid: (File)-[:CONTAINS]->(Type)-[:CONTAINS]->(Function)'
        }]
    },
    'interpretation': 'Query structure violated schema rules.'
}

# Analysis knows:
"Query was schema-invalid. Empty is EXPECTED, not meaningful.
 Validator suggests: (File)-[:CONTAINS]->(Type)-[:CONTAINS]->(Function)"
```

---

## Enhanced Analyze Prompt

### Add to Analyze Prompt (prompts.py line 300+)

```python
**VALIDATION CONTEXT**:
{format_validation_context(execution_result)}

def format_validation_context(execution_result):
    val_meta = execution_result.get('validation_metadata', {})
    sufficiency = execution_result.get('sufficiency_status')

    if sufficiency == 'SCHEMA_INVALID':
        return f"""
⚠️ Query Structure: INVALID (violated schema rules)
- Empty result was EXPECTED (invalid queries cannot return data)
- This was NOT a valid attempt to find data
- Validation errors:
{format_validation_issues(val_meta.get('validation_issues', []))}

IMPORTANT: Do not interpret this empty result as "data doesn't exist".
Recommend: REFINE with corrected schema relationships.
"""

    elif sufficiency == 'NOT_FOUND':
        return f"""
✅ Query Structure: VALID
✅ Premises: ALL VALIDATED (via APOC)
📊 Result: Empty (data doesn't exist in codebase)

Attempted paths: {val_meta.get('attempted_paths', [])}
Attempted filters: {val_meta.get('attempted_filters', [])}

This was a VALID attempt. Consider:
- Have we tried other valid perspectives?
- Should we try different filters?
- Or conclude data doesn't exist?
"""

    elif sufficiency == 'INSUFFICIENT_DATA':
        return f"""
✅ Query Structure: VALID
⚠️ Premises: SOME INVALID (via APOC)
📊 Result: Empty (wrong assumptions about data)

Premise validation failures:
{format_premise_validations(execution_result.get('premise_validations', []))}

Query assumptions were incorrect. Try different perspective.
"""
```

---

## Example Scenarios

### Scenario 1: Invalid Query → Empty

**Query:** `(File)-[:CONTAINS]->(Function {name: 'CreateWorkers'})`

**Execution Result:**
```python
{
    'results': [],
    'sufficiency_status': 'SCHEMA_INVALID',
    'validation_metadata': {
        'is_valid': False,
        'validation_issues': [{
            'message': 'CONTAINS cannot connect File to Function',
            'suggestion': '(File)-[:CONTAINS]->(Type)-[:CONTAINS]->(Function)'
        }]
    }
}
```

**Analyze Decision:**
- Recommendation: `REFINE` (not STOP!)
- Next hint: "Use correct path: File→Type→Function"
- Don't count as valid attempt

### Scenario 2: Valid Query → Empty (Data Doesn't Exist)

**Query:** `(File)-[:CONTAINS]->(Type)-[:CONTAINS]->(Function {name: 'NonExistent'})`

**Execution Result:**
```python
{
    'results': [],
    'sufficiency_status': 'NOT_FOUND',
    'validation_metadata': {
        'is_valid': True,
        'attempted_paths': [('File', 'CONTAINS', 'Type'), ('Type', 'CONTAINS', 'Function')]
    },
    'premise_validations': [
        {'entity': 'Type', 'status': 'validated'},
        {'entity': 'Function:NonExistent', 'status': 'not_found'}
    ]
}
```

**Analyze Decision:**
- Recommendation: `STOP` or `CONTINUE` (based on iteration count)
- This WAS a valid attempt
- Function 'NonExistent' truly doesn't exist

### Scenario 3: Valid Query → Empty (Wrong Assumption)

**Query:** `(Namespace {name: 'NonExistentNamespace'})-[:CONTAINS]->(Type)`

**Execution Result:**
```python
{
    'results': [],
    'sufficiency_status': 'INSUFFICIENT_DATA',
    'validation_metadata': {
        'is_valid': True,
        'attempted_paths': [('Namespace', 'CONTAINS', 'Type')]
    },
    'premise_validations': [
        {'entity': 'Namespace:NonExistentNamespace', 'status': 'not_found'}
    ]
}
```

**Analyze Decision:**
- Recommendation: `CONTINUE`
- Try without namespace filter OR verify namespace name

---

## Implementation Checklist

### Phase 1: Pass Validation Metadata
- [ ] Store validation results in generate step return dict
- [ ] Pass validation_metadata to _execute_query()
- [ ] Add validation_metadata to execution result dict

### Phase 2: Add SCHEMA_INVALID Status
- [ ] Check validation_metadata.is_valid in empty result handling
- [ ] Return SCHEMA_INVALID status if query was invalid
- [ ] Skip APOC validation for invalid queries (not meaningful)

### Phase 3: Enhanced Analyze Prompt
- [ ] Add format_validation_context() helper
- [ ] Update analyze prompt to include validation context
- [ ] Update analyze instructions with SCHEMA_INVALID guidance

### Phase 4: Update Recommendations
- [ ] REFINE recommendation for SCHEMA_INVALID
- [ ] Track valid vs invalid attempts separately
- [ ] Update exhaustion logic to only count valid attempts

---

## Expected Impact

### Better Empty Result Interpretation

**Metric:** % of empty results correctly classified

**Before:**
```
Empty result → Check premises → Guess if query was right
Accuracy: ~60% (many false "NOT_FOUND" from invalid queries)
```

**After:**
```
Empty result → Check schema validity first → Then check premises if valid
Accuracy: ~95% (clear distinction between invalid vs valid-but-empty)
```

### Fewer Wasted Iterations

**Before:**
```
Iteration 1: Invalid query (File→Function) → Empty → Interpret as "not found" → STOP
WRONG! Should have tried valid path first.
```

**After:**
```
Iteration 1: Invalid query (File→Function) → Empty → SCHEMA_INVALID → REFINE
Iteration 2: Valid query (File→Type→Function) → Empty → NOT_FOUND → STOP
CORRECT! Tried valid path, then concluded.
```

### Metric Tracking

1. **Invalid query detection rate**: % caught before Neo4j (40-55%)
2. **Correct empty interpretation**: % accurately classified (target: 95%+)
3. **Iterations to conclusion**: Average iterations per approach (target: -30%)
4. **False "not found"**: % reduced (target: -80%)
