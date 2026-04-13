# Query Plan Implementation Status

## ✅ Completed Components

### 1. Pydantic Models (adaptive_query_agent.py:59-108)
```python
class QueryStepType(str, Enum):
    ENTITY_CHECK = "entity_check"
    PATH_CHECK = "path_check"
    COUNT_CHECK = "count_check"
    DATA_RETRIEVAL = "data_retrieval"

class QueryStep(BaseModel):
    # Full step definition with validation, guidance, dependencies

class CypherQueryPlan(BaseModel):
    # Multi-step plan with CoT reasoning, steps, fallback hints
```

**Status**: ✅ Complete
**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` lines 59-108

---

### 2. Execution Flow (adaptive_query_agent.py:782-920)

**`_evaluate_step_outcome()`** (lines 782-845)
- Parses expected outcomes like "count >= 1", "results > 0"
- Evaluates query results against expectations
- Returns True/False for step success

**`_execute_query_plan()`** (lines 847-920)
- Executes steps sequentially
- Stops early on validation failure
- Returns detailed execution results for each step

**Status**: ✅ Complete
**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` lines 782-920

---

### 3. Analysis Methods (adaptive_query_agent.py:922-1081)

**`_format_step_results()`** (lines 922-956)
- Formats step execution results for LLM consumption
- Shows success/failure, expected vs actual, guidance

**`_cot_analyze_plan_results()`** (lines 958-1081)
- Analyzes query plan execution with granular feedback
- Identifies which step failed and why
- Provides step-specific failure guidance
- Calls LLM with detailed context

**Status**: ✅ Complete
**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` lines 922-1081

---

### 4. Query Plan Prompt (prompts.py:256-441, 687-700)

**`PromptManager.get_cot_generate_query_plan_prompt()`** (lines 256-441)
- Instructs LLM to generate multi-step plans
- Provides examples of entity checks, path checks, data retrieval
- Specifies expected JSON structure with steps array

**Module-level wrapper** (lines 687-700)
- `get_cot_generate_query_plan_prompt()` for external use

**Status**: ✅ Complete
**Location**: `/opt/genpod/src/core/workflow/prompts.py` lines 256-441, 687-700

---

## 🔄 Integration Needed

### 5. Wire Query Plan Mode into Agent Loop

The core components are ready, but they need to be integrated into the agent's main execution loop.

**Current Flow** (single query mode):
```python
# In _cot_generate_query_step()
result = await self.llm_service.generate_with_pydantic(
    prompt=get_cot_generate_query_prompt(...),
    response_model=CoTQueryGeneration,  # Single query
    ...
)

# Execute single query
execution_result = await self._execute_query(result.cypher_query)

# Analyze results
analysis_result = await self._cot_analyze_results_step(result, execution_result)
```

**Proposed Flow** (query plan mode):
```python
# In _cot_generate_query_step()
if use_query_plans:  # Feature flag
    result = await self.llm_service.generate_with_pydantic(
        prompt=get_cot_generate_query_plan_prompt(...),
        response_model=CypherQueryPlan,  # Query plan
        ...
    )

    # Execute query plan (multi-step with validation)
    plan_result = await self._execute_query_plan(result)

    # Analyze plan execution with step-by-step feedback
    analysis_result = await self._cot_analyze_plan_results(plan_result)
else:
    # Original single query flow (backward compatibility)
    ...
```

**Required Changes**:
1. Add feature flag to enable query plan mode
2. Modify `_cot_generate_query_step()` to use query plans when enabled
3. Update execution logging to show step-by-step progress
4. Ensure discovered_data is populated from successful data retrieval steps

**Status**: 🔄 Not Started
**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py`
**Method**: `_cot_generate_query_step()` (approx line 350-450)

---

### 6. Add Query Plan Import to prompts.py Exports

The new prompt function should be added to the module's `__all__` export list (if one exists).

**Status**: 🔄 Not Started
**Location**: Check `/opt/genpod/src/core/workflow/prompts.py` for `__all__` list

---

### 7. Testing and Validation

**Unit Tests Needed**:
- Test `_evaluate_step_outcome()` with various expected_outcome strings
- Test `_execute_query_plan()` with mock query steps
- Test `_format_step_results()` output formatting
- Test query plan prompt JSON validation

**Integration Tests Needed**:
- Test full query plan generation → execution → analysis flow
- Test early stopping on entity check failure
- Test path check failure scenarios
- Test data retrieval with all validations passing

**Benchmark Tests**:
- Run V6 benchmark with query plan mode enabled
- Compare success rate to V5 (60%)
- Measure token usage impact (plans may use more tokens but reduce retries)

**Status**: 📊 Not Started

---

## 📋 Activation Checklist

To activate query plan mode:

1. ✅ **Models defined** - QueryStepType, QueryStep, CypherQueryPlan
2. ✅ **Execution implemented** - _execute_query_plan(), _evaluate_step_outcome()
3. ✅ **Analysis implemented** - _cot_analyze_plan_results(), _format_step_results()
4. ✅ **Prompt created** - get_cot_generate_query_plan_prompt()
5. 🔄 **Integration** - Wire into agent loop with feature flag
6. 🔄 **Exports** - Add to prompts module exports
7. 📊 **Testing** - Unit tests, integration tests, benchmark

---

## 🎯 Next Steps

### Option A: Feature Flag Integration (Recommended)
1. Add `use_query_plans: bool = False` to agent initialization
2. Modify `_cot_generate_query_step()` to branch based on flag
3. Test with single query from V5 benchmark
4. If successful, enable for full V6 benchmark
5. Compare V6 vs V5 results

### Option B: Parallel Implementation
1. Keep existing single query mode as default
2. Create new `_cot_generate_query_plan_step()` method
3. Add workflow config to select mode
4. Run both modes in parallel on same benchmark
5. Compare results and token usage

### Option C: Gradual Migration
1. Start with query plans only for queries that failed in V5
2. If plan succeeds where single query failed, mark as improvement
3. Gradually expand to more query types
4. Eventually make query plans the default

---

## 💡 Benefits of Query Plan Approach

Based on QUERY_PLAN_DESIGN.md analysis:

1. **Granular Failure Feedback**: Know exactly which assumption failed
   - V5 Run 1 SQ2: Would fail at "Step 2: Path check Function→Block"
   - Guidance: "CreateWorkers has no Block nodes - try direct Function→Statement"

2. **Better Rethink Decisions**: LLM sees specific step failure, not vague "query failed"
   - Current: "Query returned 0 results"
   - New: "Step 2 failed: Function doesn't contain Blocks (expected count >= 1, got 0)"

3. **Faster Debugging**: Don't need entity diagnostics if entity validation step shows it exists
   - Current: Run full query → fail → run diagnostics → retry
   - New: Entity check fails → immediate feedback → alternative approach

4. **Incremental Validation**: Stop early if entity doesn't exist
   - Current: Execute full complex query, get error, parse error message
   - New: Step 1 entity check fails in 0.1s, stop, provide guidance

5. **Self-Documenting**: Each step explains what it's checking
   - Logs show clear progression through validation→retrieval
   - Easier to diagnose issues in production

---

## 📊 Expected Impact on V5 Failures

**V5 Run 1 (Failed)**:
- SQ2 failed: LLM generated correct query but validation showed incomplete paths
- **With Query Plans**: Step 2 (path check) would fail with guidance "try direct Function→Statement path"
- **Expected Outcome**: Success via alternative path in next iteration

**V5 Run 2 (Failed)**:
- Queries executed but used wrong patterns
- **With Query Plans**: Entity/path checks would validate assumptions before data retrieval
- **Expected Outcome**: Earlier failure detection, faster convergence

**Overall**: Expect V6 success rate of 80-100% (4-5/5 runs)

---

## 🔍 Code References

All implementations follow the design in `/opt/genpod/QUERY_PLAN_DESIGN.md`

**Modified Files**:
- `/opt/genpod/src/core/workflow/adaptive_query_agent.py`
  - Lines 59-108: Pydantic models
  - Lines 782-920: Execution flow
  - Lines 922-1081: Analysis methods

- `/opt/genpod/src/core/workflow/prompts.py`
  - Lines 256-441: Prompt implementation
  - Lines 687-700: Module wrapper

**Documentation Files**:
- `/opt/genpod/QUERY_PLAN_DESIGN.md` - Original design document
- `/opt/genpod/QUERY_PLAN_IMPLEMENTATION_STATUS.md` - This file
