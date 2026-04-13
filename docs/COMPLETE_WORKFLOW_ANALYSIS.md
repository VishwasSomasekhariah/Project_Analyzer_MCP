# Complete Workflow Data Flow Analysis

## Overview
Tracing data flow from user query → final results in the V6 query plan workflow.

## Architecture: LangGraph Workflow with Worker Pool Pattern

### 1. Entry Point: `execute_adaptive_cpg_workflow()`
**File**: `src/core/workflow/adaptive_cpg_workflow.py`

```
User Query → AdaptiveCPGAgentWorkflow.run_workflow()
```

### 2. LangGraph Node Sequence

```
initialize_environment
  ↓
analyze_intent
  ↓
decompose_query (Phase 0)
  ↓
execute_batch_approaches (Worker Pool)
  ↓
check_sufficiency
  ↓
synthesize_response
  ↓
Final Result
```

### 3. Worker Pool Execution (`execute_batch_approaches`)
**File**: `src/core/workflow/nodes.py` (lines 435-573)

```python
# For each approach packet:
async def run_packet_worker(packet):
    server = await pool.acquire()  # Get dedicated cypher server

    result = await _run_approach_with_adaptive_agent(
        approach_index=packet['id'],
        cypher_server=server,
        approach_packet=packet
    )

    await pool.release(server)
    return result

# Launch ALL packets in parallel (semaphore limits concurrency)
packet_results = await asyncio.gather(*packet_tasks)

# Aggregate results
aggregated_state = _aggregate_approach_results(state, packet_results)
```

### 4. Single Approach Execution (`_run_approach_with_adaptive_agent`)
**File**: `src/core/workflow/nodes.py` (lines 1237-1319)

```python
# Create agent with dedicated server
agent = AdaptiveQueryAgent(
    approach_index=approach_index,
    cypher_server=cypher_server,
    use_query_plans=True  # V6 mode
)

# Run agent (CoT loop)
result = await agent.run()

return {
    'approach_index': approach_index,
    'status': 'success',
    'result': result  # Contains discovered_data, tokens, etc.
}
```

### 5. AdaptiveQueryAgent CoT Loop (`agent.run()`)
**File**: `src/core/workflow/adaptive_query_agent.py` (lines 268-457)

```python
for iteration in range(max_iterations):
    # Think: Should we continue?
    should_continue = await _cot_think_step()

    # Generate: Create query plan or single query
    query_result = await _cot_generate_query_step()

    if use_query_plans:
        # Execute multi-step plan
        plan_result = await _execute_query_plan(query_result['query_plan'])
        analysis_result = await _cot_analyze_plan_results(plan_result)
        execution_result = plan_result['data_step_result']
    else:
        # Execute single query
        execution_result = await _execute_query(query_result['cypher_query'])
        analysis_result = await _cot_analyze_results_step(query_result, execution_result)

    # Record execution
    self.state.queries_executed.append(query_record)

    # ⭐ KEY FIX #2: Add to partial_answers (lines 425-435)
    if execution_result.get('results'):
        partial_answer = {...}
        self.state.partial_answers.append(partial_answer)

        # ⭐ KEY FIX #3: Add to discovered_data (lines 437-447)
        for result in execution_result.get('results', []):
            enriched_result = {...}
            self.state.discovered_data.append(enriched_result)

# Build final result
return await _build_final_result()
```

### 6. Building Final Result (`_build_final_result()`)
**File**: `src/core/workflow/adaptive_query_agent.py` (lines 2656-2764)

```python
async def _build_final_result(self):
    # Synthesize approach-level answer
    approach_answer = await _synthesize_approach_answer()

    # ⚠️ CRITICAL FILTERING STEP
    data_points_used = approach_answer.get('data_points_used', [])
    if data_points_used:
        # Filter to only relevant indices
        relevant_data = [self.state.discovered_data[i]
                        for i in data_points_used
                        if i < len(self.state.discovered_data)]
        logger.info(f"🎯 Filtered to {len(relevant_data)}/{len(self.state.discovered_data)}")
    else:
        # ⚠️ No filtering - use all data
        relevant_data = self.state.discovered_data
        logger.warning("⚠️ No data point filtering (synthesis returned no indices)")

    return {
        'discovered_data': relevant_data,  # ← This goes back to worker
        'total_results': len(relevant_data),
        'total_discovered': len(self.state.discovered_data),
        'query_history': self.state.queries_executed,
        'partial_answers': self.state.partial_answers,
        ...
    }
```

### 7. Aggregating Worker Results (`_aggregate_approach_results()`)
**File**: `src/core/workflow/nodes.py` (lines 1321-1469)

```python
def _aggregate_approach_results(state, approach_results, batch_start_idx):
    all_discovered_data = list(state.get('discovered_data', []))

    for approach_result in approach_results:
        result = approach_result.get('result', {})

        # ⭐ EXTRACT discovered_data from agent result
        discovered_data = result.get('discovered_data', [])
        all_discovered_data.extend(discovered_data)  # ← Aggregate

    logger.info(f"Total data points: {len(all_discovered_data)}")

    return {
        'discovered_data': all_discovered_data,  # ← Back to state
        'final_results': all_discovered_data,  # Alias
        ...
    }
```

## Data Flow Summary

```
User Query
  ↓
[LangGraph Nodes: initialize → intent → decompose]
  ↓
execute_batch_approaches (Worker Pool)
  ↓
┌─────────────────────────────────────────┐
│ Worker 1: AdaptiveQueryAgent            │
│   • executes queries                    │
│   • self.state.discovered_data.append() │ ← Fix #3 adds here
│   • self.state.partial_answers.append() │ ← Fix #2 adds here
│   • returns {'discovered_data': [...]}  │
└─────────────────────────────────────────┘
  ↓
_aggregate_approach_results
  • all_discovered_data.extend(worker_result['discovered_data'])
  ↓
State updated: state['discovered_data'] = all_discovered_data
  ↓
check_sufficiency
  ↓
synthesize_response
  ↓
Final Result
```

## The Issue We're Debugging

### What We Expected:
1. ✅ Queries execute successfully (getting 100, 43, 9, 1, etc. results)
2. ✅ Data added to agent's `self.state.discovered_data` (logs show "Added X data points")
3. ✅ Partial answers built (logs show "Built partial answer")
4. ❌ **PROBLEM**: `_synthesize_approach_answer()` returns empty `data_points_used`
5. ❌ **RESULT**: `relevant_data` is set to all data, but...
6. ❌ **MYSTERY**: Aggregation shows "Total data points: 0"

### The Critical Question:
**WHY does aggregation show 0 data points when agent logs show data was added?**

Two possibilities:
1. **Synthesis Filter Problem**: `_synthesize_approach_answer()` is somehow clearing/filtering out all data
2. **State Return Problem**: `relevant_data` in `_build_final_result()` is returning empty despite `self.state.discovered_data` having data

Let me check `_synthesize_approach_answer()` next...
