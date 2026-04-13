# State Reducer Audit and Potential Issues

## Overview

LangGraph reducers automatically merge state updates from parallel branches. Incorrectly designed reducers can cause:
- State corruption
- Data loss
- Memory issues
- Non-deterministic behavior

## Reducers Implemented

### 1. List Append Reducers

**Pattern**: `lambda x, y: x + y`

**Used For**:
- `discovered_data`
- `query_history`
- `llm_call_history`
- `iteration_summaries`
- `sufficiency_check_history`

**Potential Issues**:
- ❌ **Duplicate data**: If multiple branches discover the same item
- ❌ **Memory growth**: Unbounded list growth without cleanup
- ❌ **Order non-determinism**: Parallel branches may complete in any order

**Mitigations**:
- Use `_clean_approach_data()` for deduplication
- Implement size limits in synthesis phase
- Accept non-deterministic order (timestamp if needed)

### 2. Set Union Reducers

**Pattern**: `lambda x, y: list(set(x + y))`

**Used For**:
- `entities`
- `body_exploration_candidates`
- `failed_approaches`
- `models_used`

**Potential Issues**:
- ✅ **Type safety**: Assumes all items are hashable
- ⚠️ **Order loss**: Set conversion loses original order
- ❌ **Performance**: O(n) set conversion on every merge

**Mitigations**:
- Ensure only hashable items (strings, ints)
- Don't rely on order for these fields
- Consider using set fields directly instead of list

### 3. Dictionary Merge Reducers

**Pattern**: `lambda x, y: {**x, **y}`

**Used For**:
- `approach_raw_results` - Dict[int, List[Tuple]]
- `approach_statuses` - Dict[int, str]
- `approach_execution_traces` - Dict[int, Dict]
- `refinement_attempts` - Dict[int, int]
- `tokens_per_approach` - Dict[int, int]
- `cost_per_approach` - Dict[int, float]

**CRITICAL ISSUES**:
- ❌ **Key collision**: If both branches write to same key, second wins (data loss!)
- ❌ **Non-deterministic overwrites**: Order of merge affects which value survives
- ❌ **Silent data corruption**: No error, just lost updates

**Safety Requirements**:
1. **Keys MUST be non-overlapping** between parallel branches
2. Each branch must have unique approach_index
3. Never write to same dict key from multiple branches

**Current Safety**:
✅ In `execute_batch_approaches`, each Send gets unique `current_approach_index`:
```python
for i, approach in enumerate(batch_approaches):
    approach_index = current_batch_start + i  # UNIQUE per branch
    branch_state = {
        **updated_state,
        'current_approach_index': approach_index,  # Non-overlapping
    }
    send_list.append(Send("think", branch_state))
```

**Verification Needed**:
- ✅ Confirm no branch writes to another branch's approach_index
- ⚠️ Watch for bugs where `current_approach_index` is modified incorrectly
- ⚠️ Ensure refinement loops don't change approach_index

### 4. Integer Sum Reducers

**Pattern**: `lambda x, y: x + y`

**Used For**:
- `total_input_tokens`
- `total_output_tokens`
- `total_tokens_used`
- `total_estimated_cost_usd`
- `think_tokens`, `generate_tokens`, etc.

**Potential Issues**:
- ✅ **Type safety**: What if one branch returns None or string?
- ✅ **Overflow**: Very unlikely with Python's arbitrary precision ints
- ⚠️ **Float precision**: For cost_usd, floating point errors may accumulate

**Mitigations**:
- Initialize all fields to 0 in state (never None)
- Use Decimal for precise cost calculations if needed
- Validate token counts are non-negative

## Common Reducer Pitfalls

### Issue 1: Mutable Object Mutation

**BAD**:
```python
lambda x, y: x.update(y) or x  # Mutates x in place!
```

**GOOD**:
```python
lambda x, y: {**x, **y}  # Creates new dict
```

**Status**: ✅ All our reducers create new objects

### Issue 2: None Handling

**BAD**:
```python
lambda x, y: x + y  # Fails if x or y is None
```

**GOOD**:
```python
lambda x, y: (x or []) + (y or [])
```

**Status**: ⚠️ **RISK** - We assume state is always initialized
**Mitigation**: Verify state initialization in `adaptive_cpg_workflow.py:193-288`

### Issue 3: Non-Deterministic Order

**Issue**: Parallel branches complete in random order, affecting merge order

**Impact**:
- List append order varies between runs
- Dict merge `{**x, **y}` last-write-wins depends on order

**Status**: ⚠️ **ACCEPTED RISK** for lists (timestamps if needed)
**Status**: ❌ **CRITICAL** for dicts (must ensure non-overlapping keys)

### Issue 4: Memory Growth

**Issue**: Unbounded list growth without cleanup

**Status**: ⚠️ **MONITOR**
- `discovered_data` could grow very large
- `query_history` accumulates all queries
- `llm_call_history` tracks every LLM call

**Mitigation**:
- Implement size limits in `check_sufficiency`
- Consider using progressive summarization
- Clear old data after synthesis

## Recommended Improvements

### 1. ✅ COMPLETED: Add Defensive Reducer for Dicts

**Status**: Implemented in `/opt/genpod/src/core/workflow/models.py` (lines 17-71)

Created three defensive merger functions:
- `_safe_dict_merge`: General dict merger with collision detection
- `_safe_int_dict_merge`: For integer-valued dicts (tokens_per_approach, refinement_attempts)
- `_safe_float_dict_merge`: For float-valued dicts (cost_per_approach)

All dictionary fields in `AgentState` now use defensive reducers:
- `approach_raw_results` → `_safe_dict_merge` (line 673)
- `approach_statuses` → `_safe_dict_merge` (line 693)
- `approach_execution_traces` → `_safe_dict_merge` (line 704)
- `refinement_attempts` → `_safe_int_dict_merge` (line 711)
- `tokens_per_approach` → `_safe_int_dict_merge` (line 754)
- `cost_per_approach` → `_safe_float_dict_merge` (line 755)

### 2. Add None-Safe List Reducer

Replace:
```python
discovered_data: Annotated[List[Dict[str, Any]], lambda x, y: x + y]
```

With:
```python
discovered_data: Annotated[
    List[Dict[str, Any]],
    lambda x, y: (x if x is not None else []) + (y if y is not None else [])
]
```

### 3. Add Type Validation

Add runtime validation in reducers:
```python
def _validated_int_sum(x: int, y: int) -> int:
    """Sum integers with type validation."""
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        logger.error(f"Invalid types for int sum: {type(x)}, {type(y)}")
        return 0
    return int(x + y)
```

### 4. Add Size Limits

Monitor and limit unbounded growth:
```python
def _bounded_list_append(x: list, y: list, max_size: int = 10000) -> list:
    """Append with size limit."""
    result = x + y
    if len(result) > max_size:
        logger.warning(f"List exceeded max_size {max_size}, truncating")
        return result[-max_size:]  # Keep most recent
    return result
```

## Testing Checklist

- [ ] Verify all state fields initialized in `adaptive_cpg_workflow.py`
- [ ] Test with batch_size=1 (sequential)
- [ ] Test with batch_size=2 (minimal parallel)
- [ ] Test with batch_size=4 (full parallel)
- [ ] Monitor for dict key collisions in logs
- [ ] Check memory usage with large datasets
- [ ] Verify token counts sum correctly
- [ ] Test with failures in some branches
- [ ] Verify state after convergence

## Monitoring

Add logging to detect reducer issues:

```python
# In nodes.py after convergence
def _validate_merged_state(state: AgentState):
    """Validate state after parallel merge."""
    # Check for duplicates
    approach_indices = list(state['approach_raw_results'].keys())
    if len(approach_indices) != len(set(approach_indices)):
        logger.error("Duplicate approach indices detected!")

    # Check token counts
    total_tokens = state['total_tokens_used']
    sum_tokens = (state['total_input_tokens'] + state['total_output_tokens'])
    if total_tokens != sum_tokens:
        logger.warning(f"Token count mismatch: {total_tokens} != {sum_tokens}")

    # Check approach count
    expected_approaches = state['current_approach_index']
    actual_approaches = len(state['approach_statuses'])
    if actual_approaches != expected_approaches:
        logger.warning(f"Approach count mismatch: {actual_approaches} != {expected_approaches}")
```

## Conclusion

**Current Status**: ✅ **DEFENSIVE REDUCERS IMPLEMENTED**

**Completed**:
1. ✅ Defensive dict mergers with collision detection and logging
2. ✅ All dictionary fields use safe reducers

**Remaining Risks**:
1. ⚠️ No None handling in list reducers (assumes state initialization)
2. ⚠️ No bounds on memory growth for unbounded lists
3. ⚠️ No validation of merged state after convergence

**Recommended Next Actions**:
1. Add state validation after convergence in `check_sufficiency`
2. Monitor logs for collision warnings during testing
3. Consider adding size limits for unbounded lists if memory issues arise
4. Test extensively with parallel execution (batch_size > 1)

**Testing Priority**:
- Run with batch_size=2 and batch_size=4 to verify collision detection
- Monitor `/opt/genpod/logs/workflow_error.log` for collision warnings
- Verify token counts and costs sum correctly across parallel branches
