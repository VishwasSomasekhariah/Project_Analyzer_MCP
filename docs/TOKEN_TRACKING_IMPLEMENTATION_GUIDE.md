# Token Tracking Implementation Guide

## Overview

Token utilization tracking has been added to the workflow state schema, but the actual tracking logic needs to be integrated at each LLM call site in the workflow nodes.

## Helper Method Available

A helper method `_track_llm_call()` has been added to `WorkflowNodes` class (lines 2175-2259 in `/opt/genpod/src/core/workflow/nodes.py`):

```python
def _track_llm_call(
    self,
    llm_response: Any,
    call_type: str,
    approach_index: Optional[int] = None,
    call_purpose: Optional[str] = None
) -> Dict[str, Any]:
    """
    Track LLM call metrics and prepare state updates.

    Returns dictionary with state updates for token tracking.
    """
```

## How to Use

### Pattern 1: Simple LLM Call (No Approach Tracking)

**Before** (lines 2497-2506 in `_analyze_approach_scope_with_llm`):
```python
result = await llm_service.generate_response(
    prompt,
    json_mode=True,
    model=LLMModel.GPT4O,
    max_tokens=2000,
    temperature=0.2
)

if not result or result.error:
    raise Exception(f"LLM scope analysis failed: {result.error if result else 'No response'}")
```

**After** (add token tracking):
```python
result = await llm_service.generate_response(
    prompt,
    json_mode=True,
    model=LLMModel.GPT4O,
    max_tokens=2000,
    temperature=0.2
)

if not result or result.error:
    raise Exception(f"LLM scope analysis failed: {result.error if result else 'No response'}")

# Track token usage (no approach_index since think is global)
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='think',
    call_purpose='Analyze approach scope'
)
```

### Pattern 2: LLM Call with Approach Tracking

**Example from `generate_query` node**:
```python
# Get current approach index
approach_index = state.get('current_approach_index', 0)

# Make LLM call
result = await llm_service.generate_response(
    prompt,
    json_mode=True,
    model=LLMModel.GPT4O,
    max_tokens=3000
)

# Track with approach index
token_updates = self._track_llm_call(
    llm_response=result,
    call_type='generate',
    approach_index=approach_index,
    call_purpose=f'Generate queries for approach {approach_index}'
)

# Merge token updates into return state
return {
    **state,
    **token_updates,  # Add token tracking updates
    # ... other state updates
}
```

### Pattern 3: Multiple LLM Calls in One Node

If a node makes multiple LLM calls, track each one and merge the updates:

```python
# First LLM call
result1 = await llm_service.generate_response(prompt1, ...)
token_updates1 = self._track_llm_call(
    llm_response=result1,
    call_type='diagnostics',
    approach_index=approach_index,
    call_purpose='Run diagnostic queries'
)

# Second LLM call
result2 = await llm_service.generate_response(prompt2, ...)
token_updates2 = self._track_llm_call(
    llm_response=result2,
    call_type='refinement',
    approach_index=approach_index,
    call_purpose='Refine queries based on diagnostics'
)

# Merge all updates
return {
    **state,
    **token_updates1,
    **token_updates2,
    # ... other state updates
}
```

## State Fields Updated

The `_track_llm_call()` helper automatically updates these fields:

**Global Metrics** (reducers will sum across parallel branches):
- `total_input_tokens`
- `total_output_tokens`
- `total_tokens_used`
- `total_estimated_cost_usd`

**Per-Step Breakdowns** (reducers will sum):
- `think_tokens`
- `generate_tokens`
- `rethink_tokens`
- `diagnostics_tokens`
- `refinement_tokens`

**Per-Approach Tracking** (reducers will merge with collision detection):
- `tokens_per_approach[approach_index]`
- `cost_per_approach[approach_index]`

**Call History** (reducer will append):
- `llm_call_history` - List of all LLM calls with full metrics

**Model Tracking** (reducer will union):
- `models_used` - List of unique models used

## LLM Call Sites to Update

### Priority 1: Core Workflow Nodes

1. **`think` node** (line 275):
   - Call in `_analyze_approach_scope_with_llm` (line 2497)
   - Call type: `'think'`
   - No approach_index (global)

2. **`generate_query` node** (line 596):
   - Call in `_generate_cypher_queries_with_llm` (line 2701)
   - Call type: `'generate'`
   - Include approach_index

3. **`rethink_approach` node** (line 1392):
   - Calls in `_run_diagnostics_on_failed_queries` and `_generate_refined_queries_from_diagnostics`
   - Call types: `'diagnostics'`, `'refinement'`
   - Include approach_index

4. **`check_sufficiency` node** (line 1575):
   - Call in `_evaluate_data_sufficiency_with_llm`
   - Call type: `'sufficiency_check'`
   - No approach_index (global)

5. **`synthesize_response` node**:
   - Synthesis LLM call
   - Call type: `'synthesis'`
   - No approach_index (global)

### Priority 2: Helper Methods

1. **`_analyze_empty_result`** (contains diagnostic LLM calls)
2. **`_refine_queries_using_diagnostics`** (contains refinement LLM calls)
3. **`analyze_intent`** (line 2096)

## Verification

After adding token tracking, verify it works by:

1. **Check logs** for debug messages:
   ```
   Tracked think call: 1234 tokens (in:800, out:434), cost: $0.012340, model: gpt-4o
   ```

2. **Check state after workflow** for populated token fields:
   ```python
   state['total_tokens_used']  # Should be > 0
   state['llm_call_history']   # Should have records
   state['tokens_per_approach']  # Should have per-approach data
   ```

3. **Check for collision warnings** in logs if using parallel execution:
   ```
   ⚠️ CRITICAL: Dict key collision detected in parallel merge!
   ```

## Example: Complete Implementation

Here's a complete example showing how to add token tracking to the `think` node:

```python
async def think(self, state: AgentState) -> AgentState:
    """Node: Think - Analyze current approach and determine scope."""
    logger.info("🧠 Node: think")

    try:
        # ... existing logic ...

        # Analyze scope using LLM
        scope_analysis = await self._analyze_approach_scope_with_llm(current_approach, state)
        current_scope = scope_analysis['scope']
        retrieval_strategy = scope_analysis['retrieval_strategy']

        # Get token tracking updates from the scope analysis
        token_updates = scope_analysis.get('_token_updates', {})

        # Prepare thinking results
        thinking_results = {
            "approach_name": approach_name,
            "approach_index": current_approach_index,
            "scope": current_scope,
            "retrieval_strategy": retrieval_strategy,
            "scope_reasoning": scope_analysis['reasoning'],
            "status": "ready_for_generation"
        }

        return {
            **state,
            **token_updates,  # ADDED: Merge token tracking updates
            "current_approach_details": current_approach,
            "current_scope": current_scope,
            "thinking_results": thinking_results,
            "current_node": "think"
        }

    except Exception as e:
        logger.error(f"❌ Thinking phase failed: {e}")
        # ... error handling ...
```

And the helper method that was called:

```python
async def _analyze_approach_scope_with_llm(self, approach: Dict[str, Any], state: AgentState) -> Dict[str, Any]:
    """Use LLM to analyze approach scope."""

    # ... build prompt ...

    result = await llm_service.generate_response(
        prompt,
        json_mode=True,
        model=LLMModel.GPT4O,
        max_tokens=2000,
        temperature=0.2
    )

    if not result or result.error:
        raise Exception(f"LLM scope analysis failed")

    # ADDED: Track token usage
    token_updates = self._track_llm_call(
        llm_response=result,
        call_type='think',
        call_purpose='Analyze approach scope'
    )

    # Parse and validate response
    scope_data = await self._retry_llm_with_validation(
        llm_service=llm_service,
        initial_prompt=prompt,
        model_class=ScopeAnalysis,
        max_retries=3,
        temperature=0.2,
        initial_response=result
    )

    # ADDED: Include token updates in return
    return {
        **scope_data,
        '_token_updates': token_updates  # Include for merging
    }
```

## Next Steps

1. Add token tracking to all LLM call sites listed above
2. Test with a simple query to verify tracking works
3. Monitor logs for token tracking debug messages
4. Verify state updates are correctly merged in parallel execution
