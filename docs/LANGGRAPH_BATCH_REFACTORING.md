# LangGraph Batch Mode Refactoring Plan

## Current Problem

The current batch mode implementation (`_execute_single_approach_queries`) creates a **separate code path** that reimplements the entire `think → generate_query → execute_queries → rethink` workflow as a helper method. This violates LangGraph principles and creates multiple issues:

1. **Code duplication** - Logic exists in both workflow nodes AND helper methods
2. **Different execution paths** - Sequential uses nodes, batch uses helpers
3. **Bugs only appear in batch mode** - Because it's untested code
4. **State management violations** - Manual aggregation instead of reducers
5. **No LangGraph benefits** - Bypasses checkpointing, resumability, visualization

## LangGraph Design Principles

LangGraph is designed to handle parallelization by:
- **Reusing the same workflow nodes** for parallel branches
- **Using Send API** to fan out to multiple parallel paths
- **Using state reducers** to merge results from parallel branches
- **Maintaining consistent execution paths** between sequential and parallel modes

## Correct Architecture: Using LangGraph Send API

### Current (Incorrect) Flow
```
execute_batch_approaches (node)
  └── _execute_single_approach_queries (helper method)
       ├── think logic (duplicated)
       ├── generate logic (duplicated)
       ├── execute logic (duplicated)
       └── rethink logic (duplicated)
```

### Correct Flow with Send API
```
execute_batch_approaches (node)
  └── Send API: Fan out to N parallel branches
       ├── Branch 1: think → generate_query → execute_queries → rethink
       ├── Branch 2: think → generate_query → execute_queries → rethink
       ├── Branch 3: think → generate_query → execute_queries → rethink
       └── Branch 4: think → generate_query → execute_queries → rethink
            └── Converge: All results merged by state reducers
```

## Implementation Plan

### Step 1: Update State Schema with Proper Reducers

```python
# In models.py - AgentState
class AgentState(TypedDict):
    # ... existing fields ...

    # IMPORTANT: Fields that accumulate from parallel branches need reducers
    discovered_data: Annotated[List[Dict[str, Any]], operator.add]  # Append results
    query_history: Annotated[List[Dict[str, Any]], operator.add]   # Append queries
    approach_raw_results: Dict[int, List[Tuple[str, List[Dict]]]]  # Overwrite (manual merge)
    approach_statuses: Dict[int, str]  # Overwrite (manual merge)
    failed_approaches: Annotated[List[int], operator.add]  # Append failures
```

### Step 2: Refactor execute_batch_approaches to Use Send API

```python
from langgraph.types import Send, Command

async def execute_batch_approaches(self, state: AgentState) -> Command:
    """
    Node: Execute Batch Approaches - Fan out to parallel think→generate→execute→rethink cycles.

    Uses LangGraph's Send API to create parallel branches, each running through
    the SAME standard workflow nodes.
    """
    logger.info("⚡ Node: execute_batch_approaches")

    # Configuration
    batch_size = state.get('batch_size', 4)

    # Get approaches and current position
    discovery_research = state.get('discovery_research', {})
    approaches = discovery_research.get('data_collection_approaches', [])
    current_batch_start = state.get('current_approach_index', 0)
    total_approaches = len(approaches)

    # Determine batch end
    current_batch_end = min(current_batch_start + batch_size, total_approaches)
    batch_approaches = approaches[current_batch_start:current_batch_end]

    logger.info(f"🔄 Fanning out to {len(batch_approaches)} parallel branches...")

    # Fan out: Create parallel branches using Send API
    # Each branch gets its own approach index and runs through standard nodes
    return Command(
        goto=[
            Send(
                "think",  # Start each branch at 'think' node
                {
                    **state,  # Copy full state
                    "current_approach_index": current_batch_start + i,  # Set approach index
                    "batch_branch_id": i,  # Track which branch this is
                }
            )
            for i in range(len(batch_approaches))
        ]
    )
```

### Step 3: Update Workflow Graph to Handle Convergence

```python
# In adaptive_cpg_workflow.py

# After parallel branches complete, they converge back to rethink
workflow.add_conditional_edges(
    "execute_queries",
    self.workflow_nodes.should_continue_after_execute,
    {
        "rethink": "rethink_convergence",  # NEW: Convergence node
        "generate_query": "generate_query"  # Retry with syntax error feedback
    }
)

# NEW: Convergence node waits for all parallel branches
workflow.add_node("rethink_convergence", self.workflow_nodes.rethink_convergence)

workflow.add_conditional_edges(
    "rethink_convergence",
    self.workflow_nodes.should_continue_after_rethink,
    {
        "execute_batch_approaches": "execute_batch_approaches",  # Next batch
        "synthesize_response": "synthesize_response"  # Done
    }
)
```

### Step 4: Create Convergence Node

```python
async def rethink_convergence(self, state: AgentState) -> AgentState:
    """
    Node: Wait for all parallel branches to complete and merge results.

    This is automatically called after all parallel branches from Send API complete.
    State reducers have already merged:
    - discovered_data (via operator.add)
    - query_history (via operator.add)
    - failed_approaches (via operator.add)

    We just need to check if we have enough data to synthesize.
    """
    logger.info("🤔 Node: rethink_convergence")

    # All parallel results have been merged by state reducers
    total_results = len(state.get('discovered_data', []))
    current_batch_end = state.get('current_approach_index', 0) + state.get('batch_size', 4)

    logger.info(f"📊 Batch completed: {total_results} total results accumulated")

    # Update current_approach_index to next batch
    return {
        **state,
        "current_approach_index": current_batch_end,
        "current_node": "rethink_convergence"
    }
```

### Step 5: Update Existing Nodes to Support Both Modes

The beauty of this approach: **No changes needed!** The existing `think`, `generate_query`, `execute_queries`, and `rethink` nodes work for both:
- Sequential mode: Called one at a time
- Batch mode: Called in parallel via Send API

The only difference is state management:
- Sequential: Each node updates state sequentially
- Batch: Each parallel branch updates its own copy, then reducers merge

## Benefits of This Approach

1. ✅ **Single code path** - Sequential and batch use SAME nodes
2. ✅ **No code duplication** - All logic in workflow nodes
3. ✅ **Bugs fixed once** - Fixes apply to both modes automatically
4. ✅ **Proper state management** - LangGraph reducers handle merging
5. ✅ **Checkpointing works** - Can resume mid-batch
6. ✅ **Visualization works** - Can see parallel branches in LangGraph Studio
7. ✅ **Easier to test** - Test nodes once, works everywhere

## Migration Steps

### Phase 1: Preparation
- [ ] Add state reducers to AgentState for parallel fields
- [ ] Create rethink_convergence node
- [ ] Update workflow graph to use convergence

### Phase 2: Refactor
- [ ] Replace _execute_single_approach_queries with Send API in execute_batch_approaches
- [ ] Remove _execute_approaches_in_parallel helper
- [ ] Remove _generate_queries_for_approach helper (use generate_query node)

### Phase 3: Testing
- [ ] Test sequential mode (should work unchanged)
- [ ] Test batch mode with Send API
- [ ] Verify state merging with reducers
- [ ] Verify cypher server pool acquisition/release

### Phase 4: Cleanup
- [ ] Remove all batch-specific helper methods
- [ ] Update documentation
- [ ] Remove temporary compatibility code

## Key Differences from Current Implementation

| Aspect | Current (Wrong) | Correct (Send API) |
|--------|----------------|-------------------|
| Code path | Different for batch | Same for both modes |
| Nodes used | Helper methods | Standard workflow nodes |
| State merging | Manual aggregation | LangGraph reducers |
| Cypher server | Acquired in helper | Acquired in node |
| Error handling | Duplicated logic | Single source of truth |
| Debugging | Hard (2 paths) | Easy (1 path) |

## Example: How Send API Works

```python
# When execute_batch_approaches returns Command with 4 Send objects:
Command(
    goto=[
        Send("think", {**state, "current_approach_index": 0}),
        Send("think", {**state, "current_approach_index": 1}),
        Send("think", {**state, "current_approach_index": 2}),
        Send("think", {**state, "current_approach_index": 3}),
    ]
)

# LangGraph automatically:
# 1. Creates 4 parallel branches
# 2. Each branch runs: think → generate_query → execute_queries → rethink
# 3. Each branch has its own state snapshot
# 4. When all branches complete, reducers merge their state updates
# 5. Converged state moves to rethink_convergence node
```

## Testing Strategy

1. **Unit test state reducers** - Verify merging works correctly
2. **Test sequential mode** - Should work unchanged
3. **Test batch mode** - Verify parallel execution
4. **Test convergence** - Verify all results merged
5. **Test server pool** - Verify servers acquired/released correctly
6. **Integration test** - End-to-end with real query

## References

- LangGraph Send API: https://langchain-ai.github.io/langgraph/how-tos/map-reduce/
- State Reducers: https://langchain-ai.github.io/langgraph/concepts/low_level/#state-reducers
- Parallel Execution: https://langchain-ai.github.io/langgraph/concepts/low_level/#parallel-execution
