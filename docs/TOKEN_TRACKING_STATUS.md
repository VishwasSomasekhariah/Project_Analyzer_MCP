# Token Tracking Implementation Status

## ✅ Completed

### 1. Helper Method Created (`/opt/genpod/src/core/workflow/nodes.py:2175-2259`)

Created `_track_llm_call()` helper method that:
- Extracts token usage from `LLMResponse` objects
- Handles both OpenAI and Anthropic response formats
- Calculates input/output token costs
- Prepares state updates for all token tracking fields
- Returns a dictionary ready to merge into state

**Usage**:
```python
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='think',  # or 'generate', 'rethink', 'diagnostics', etc.
    approach_index=approach_index,  # optional, for per-approach tracking
    call_purpose='Description of this LLM call'
)

return {
    **state,
    **token_updates,  # Merge token tracking into returned state
    # ... other state updates
}
```

### 2. Implemented in `think` Node (`/opt/genpod/src/core/workflow/nodes.py:275-366`)

**What was done**:
- Updated `_analyze_approach_scope_with_llm` (lines 2508-2528) to track LLM call
- Return token updates in `_token_updates` field
- Updated `think` node (lines 321-345) to extract and merge token updates

**Result**: Think node now fully tracks token usage for scope analysis LLM calls

## ⚠️ TODO: Remaining LLM Call Sites

### Priority 1: Core Workflow Nodes

#### 1. `generate_query` Node
**Location**: Line 596
**LLM Call**: In query generation logic around line 2804 (in `_retry_llm_with_validation`)
**What to add**:
```python
# After generating queries
approach_index = state.get('current_approach_index', 0)
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='generate',
    approach_index=approach_index,
    call_purpose=f'Generate Cypher queries for approach {approach_index}'
)

# In return statement
return {
    **state,
    **token_updates,
    # ... other updates
}
```

#### 2. `rethink_approach` Node
**Location**: Line 1392
**LLM Calls**:
- Diagnostic queries (via `_analyze_empty_result`)
- Query refinement (via `_refine_queries_using_diagnostics`)

**What to add**: Track both diagnostic and refinement LLM calls separately with appropriate `call_type`

#### 3. `check_sufficiency` Node
**Location**: Line 1575
**LLM Call**: In `_evaluate_data_sufficiency_with_llm`
**What to add**:
```python
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='sufficiency_check',
    call_purpose='Evaluate data sufficiency'
)
```

#### 4. `synthesize_response` Node
**LLM Call**: Final synthesis
**What to add**:
```python
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='synthesis',
    call_purpose='Synthesize final response'
)
```

#### 5. `analyze_intent` Node
**Location**: Line 2096
**What to add**:
```python
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='intent_analysis',
    call_purpose='Analyze user query intent'
)
```

### Priority 2: Helper Methods

These methods contain LLM calls but are called from multiple places:

#### 1. `_analyze_empty_result`
**Contains**: Diagnostic query generation and analysis
**Call type**: `'diagnostics'`
**Note**: Need to pass through approach_index from caller

#### 2. `_refine_queries_using_diagnostics`
**Contains**: Query refinement based on diagnostics
**Call type**: `'refinement'`
**Note**: Need to pass through approach_index from caller

#### 3. `_retry_llm_with_validation`
**Location**: Lines 2773-2878
**Contains**: Generic LLM retry logic with validation
**Challenge**: Used by multiple callers, needs context-aware tracking
**Solution**: Add optional `call_metadata` parameter to pass through call_type and approach_index

### Priority 3: Non-Critical Calls

- Body exploration LLM calls (if any)
- Fallback synthesis calls
- Schema validation/correction calls

## State Fields Being Tracked

When token tracking is fully implemented, these fields will be populated:

### Global Metrics (summed across all branches)
- `total_input_tokens`: Total input tokens across all LLM calls
- `total_output_tokens`: Total output tokens
- `total_tokens_used`: Total tokens (input + output)
- `total_estimated_cost_usd`: Total estimated cost

### Per-Step Breakdowns (summed across all branches)
- `think_tokens`: Tokens used in think steps
- `generate_tokens`: Tokens used in generate steps
- `rethink_tokens`: Tokens used in rethink steps
- `diagnostics_tokens`: Tokens used in diagnostics
- `refinement_tokens`: Tokens used in query refinement
- `sufficiency_check_tokens`: Tokens used in sufficiency checks (global)
- `synthesis_tokens`: Tokens used in final synthesis (global)

### Per-Approach Tracking (merged with collision detection)
- `tokens_per_approach[approach_index]`: Total tokens for each approach
- `cost_per_approach[approach_index]`: Total cost for each approach

### Call History (appended from all branches)
- `llm_call_history`: List of all LLM calls with full details

### Model Tracking (union across branches)
- `models_used`: List of unique model names used

## Testing Token Tracking

### 1. Run a Simple Test Query
```bash
# Run workflow with token tracking enabled
python test_single_query_refinement.py
```

### 2. Check Logs
Look for token tracking debug messages:
```
Tracked think call: 1234 tokens (in:800, out:434), cost: $0.012340, model: gpt-4o
Tracked generate call: 2345 tokens (in:1500, out:845), cost: $0.023450, model: gpt-4o
```

### 3. Inspect Final State
After workflow completes, verify state contains token data:
```python
print(f"Total tokens used: {state['total_tokens_used']}")
print(f"Total cost: ${state['total_estimated_cost_usd']:.6f}")
print(f"Per-step breakdown: think={state['think_tokens']}, generate={state['generate_tokens']}")
print(f"Tokens per approach: {state['tokens_per_approach']}")
print(f"Models used: {state['models_used']}")
print(f"Call history entries: {len(state['llm_call_history'])}")
```

### 4. Check for Collisions (Parallel Mode)
When running with `batch_size > 1`, check `/opt/genpod/logs/workflow_error.log` for:
```
⚠️ CRITICAL: Dict key collision detected in parallel merge!
```

If collisions occur, it indicates a bug in approach index assignment.

## Implementation Strategy

### Immediate Next Steps
1. Add token tracking to `generate_query` node (highest priority)
2. Add token tracking to `rethink_approach` node
3. Add token tracking to `check_sufficiency` node
4. Add token tracking to `synthesize_response` node
5. Update `_analyze_empty_result` and `_refine_queries_using_diagnostics` to support token tracking

### Testing Approach
- Test with `batch_size=1` (sequential) first
- Verify all token fields are populated correctly
- Then test with `batch_size=2` and `batch_size=4` (parallel)
- Verify reducers merge correctly without collisions

### Validation
- Run end-to-end test query
- Check that sum of per-step tokens equals total_tokens_used
- Check that sum of per-approach tokens matches total_tokens_used
- Verify cost calculations are reasonable
- Confirm no key collisions in parallel execution

## Summary

**Status**: 1 of ~8 core LLM call sites implemented (think node)

**Next Actions**:
1. Continue implementing token tracking in remaining core nodes
2. Update helper methods to support token tracking
3. Test thoroughly in both sequential and parallel modes
4. Monitor for any reducer issues or key collisions

**Files Modified**:
- `/opt/genpod/src/core/workflow/nodes.py` - Added `_track_llm_call()` helper and updated `think` node
- `/opt/genpod/src/core/workflow/models.py` - Already has all token tracking fields with reducers
