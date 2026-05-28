# Parallel Workflow Architecture - Entry and Exit Points

## Overview

This document defines the complete workflow structure with clear entry/exit points for parallel execution. This ensures alignment on the architecture before implementation.

---

## Full Workflow Graph

```
START
  │
  ├─→ analyze_intent (GLOBAL - once)
  │     └─ Analyze user query intent (lookup vs architectural)
  │     └─ Helps inform query generation strategy
  │
  ├─→ discovery_research (GLOBAL - once)
  │     └─ Generates N approaches
  │     └─ Uses global intent to determine approach characteristics
  │
  ├─→ execute_batch_approaches (ENTRY POINT FOR PARALLEL)
  │     │
  │     ├─ Select batch of M approaches (e.g., M=4)
  │     │
  │     │   │
  │     │   ├─→ think (per-approach)
  │     │   │     └─ Analyze scope for THIS approach
  │     │   │
  │     │   ├─→ generate_query (per-approach)
  │     │   │     └─ Generate appropriate number of queries for THIS approach
  │     │   │
  │     │   ├─→ execute_queries (per-approach)
  │     │   │     └─ Execute queries for THIS approach
  │     │   │
  │     │   ├─→ rethink_approach (per-approach) ◄──────────┐
  │     │   │     │                                         │
  │     │   │     ├─ Run diagnostics on failures           │
  │     │   │     ├─ Decide: needs refinement?             │
  │     │   │     │                                         │
  │     │   │     ├─ YES: Loop back to generate_query ─────┘
  │     │   │     │       (with refined queries)
  │     │   │     │
  │     │   │     └─ NO: Mark approach complete
  │     │   │           Add to discovered_data
  │     │   │           EXIT from this approach
  │     │   │
  │     │   └─→ [Approach Complete]
  │     │
  │     └─ WAIT for all M approaches to complete (EXIT POINT FROM PARALLEL)
  │
  ├─→ check_sufficiency (CONVERGENCE POINT)
  │     │
  │     ├─ Evaluate all discovered_data so far
  │     ├─ Ask LLM: "Is this sufficient to answer the query?"
  │     │
  │     ├─ Decision:
  │     │   ├─ INSUFFICIENT + More approaches available
  │     │   │   └─→ Loop back to execute_batch_approaches (next batch)
  │     │   │
  │     │   └─ SUFFICIENT or All approaches exhausted
  │     │       └─→ Continue to synthesize_response
  │     │
  │     └─→ synthesize_response (final)
  │
  └─→ END
```

---

## Key Entry and Exit Points

### 1. Entry Point: `execute_batch_approaches`

**Purpose**: Select and dispatch a batch of approaches for parallel execution

**Input State**:
- `discovery_research.data_collection_approaches` - All available approaches
- `current_approach_index` - Where we left off
- `batch_size` - How many to execute in this batch

**Logic**:
```python
async def execute_batch_approaches(self, state: AgentState) -> AgentState:
    """
    ENTRY POINT for parallel execution.
    Selects next batch of approaches and dispatches them.
    """
    # Get configuration
    batch_size = state.get('batch_size', 4)
    current_start = state.get('current_approach_index', 0)
    approaches = state['discovery_research']['data_collection_approaches']
    total = len(approaches)

    # Calculate batch range
    batch_end = min(current_start + batch_size, total)
    batch = approaches[current_start:batch_end]

    logger.info(f"🚀 ENTRY: Executing batch {current_start}-{batch_end} ({len(batch)} approaches)")

    # Execute batch (sequential for now, parallel with Send API later)
    for i, approach in enumerate(batch):
        approach_index = current_start + i

        # Initialize approach trace
        state = self._init_approach_trace(state, approach_index, approach)

        # Set current approach
        state['current_approach_index'] = approach_index

        # Execute: think → generate → execute → rethink loop
        # This will be the actual workflow nodes
        state = await self.think(state)

        # Continue through workflow...
        # (think routes to generate_query, which routes to execute_queries,
        #  which routes to rethink_approach)

    # Update batch tracking
    state['current_approach_index'] = batch_end
    state['batches_completed'] += 1

    logger.info(f"🏁 EXIT: Batch complete, converging to check_sufficiency")

    return state
```

**Output State**:
- `current_approach_index` - Updated to batch_end
- `batches_completed` - Incremented
- `approach_execution_traces` - Updated with batch results

**Routing**: Converges to `check_sufficiency`

---

### 2. Per-Approach Loop: `think → generate_query → execute_queries → rethink_approach`

#### Node: `think`
**Purpose**: Analyze scope for current approach

**Input**: `current_approach_index` points to approach to analyze

**Logic**:
```python
async def think(self, state: AgentState) -> AgentState:
    """
    Analyze scope for current approach.
    Tracks this in approach execution trace.
    """
    approach_index = state['current_approach_index']
    approach = state['discovery_research']['data_collection_approaches'][approach_index]

    # Call LLM to analyze scope
    scope_analysis = await self._analyze_approach_scope_with_llm(approach, state)

    # Record in approach trace
    self._record_think_step(state, approach_index, scope_analysis)

    return {
        **state,
        'thinking_results': scope_analysis,
        'current_node': 'think'
    }
```

**Routing**: Always → `generate_query`

#### Node: `generate_query`
**Purpose**: Generate queries for current approach (original or refined)

**Logic**:
```python
async def generate_query(self, state: AgentState) -> AgentState:
    """
    Generate queries for current approach.
    Handles both original generation and refinement.
    """
    approach_index = state['current_approach_index']

    # Check if this is a refinement cycle
    refined_queries = state.get('refined_queries', [])

    if refined_queries:
        # Use refined queries from rethink_approach
        queries = refined_queries
        cycle_type = 'refinement'
    else:
        # Generate original queries
        queries = await self._generate_queries_for_approach(...)
        cycle_type = 'original'

    # Record in approach trace
    self._record_generate_cycle(state, approach_index, queries, cycle_type)

    return {
        **state,
        'generated_queries': queries,
        'refined_queries': [],  # Clear for next time
        'current_node': 'generate_query'
    }
```

**Routing**: Always → `execute_queries`

#### Node: `execute_queries`
**Purpose**: Execute queries for current approach

**Logic**:
```python
async def execute_queries(self, state: AgentState) -> AgentState:
    """
    Execute queries for current approach.
    """
    approach_index = state['current_approach_index']
    queries = state['generated_queries']

    # Execute all queries
    results = []
    for query in queries:
        result = await self._execute_query_with_retry(query, ...)
        results.append(result)

    # Record in approach trace
    self._record_execute_cycle(state, approach_index, results)

    return {
        **state,
        'execution_results': results,
        'current_node': 'execute_queries'
    }
```

**Routing**: Always → `rethink_approach`

#### Node: `rethink_approach`
**Purpose**: Analyze results and decide: complete or refine?

**Logic**:
```python
async def rethink_approach(self, state: AgentState) -> AgentState:
    """
    CRITICAL NODE: Decides if approach needs refinement or is complete.
    This is where the per-approach loop happens.
    """
    approach_index = state['current_approach_index']
    results = state['execution_results']

    # Analyze results
    successful = [r for r in results if r['status'] == 'success']
    failed = [r for r in results if r['status'] in ['empty_result', 'error']]

    logger.info(f"📊 Approach {approach_index}: {len(successful)} success, {len(failed)} failed")

    # Check refinement attempts
    refinement_attempts = state.get('refinement_attempts', {})
    attempts = refinement_attempts.get(approach_index, 0)
    max_attempts = 2

    # Decision logic
    if not failed:
        # All queries successful - COMPLETE
        logger.info(f"✅ Approach {approach_index} COMPLETE - all queries successful")

        # Clean data and add to discovered_data
        cleaned = self._clean_approach_data(successful)

        # Complete approach trace
        self._complete_approach_trace(state, approach_index, 'success', cleaned)

        return {
            **state,
            'discovered_data': state['discovered_data'] + [cleaned],
            'approach_statuses': {
                **state.get('approach_statuses', {}),
                approach_index: 'success'
            },
            'needs_refinement': False,
            'current_node': 'rethink_approach'
        }

    elif attempts >= max_attempts:
        # Max refinements reached - COMPLETE (partial or failed)
        status = 'partial' if successful else 'failed'
        logger.info(f"⚠️ Approach {approach_index} {status.upper()} - max refinements reached")

        cleaned = self._clean_approach_data(successful) if successful else None
        self._complete_approach_trace(state, approach_index, status, cleaned)

        return {
            **state,
            'discovered_data': state['discovered_data'] + ([cleaned] if cleaned else []),
            'approach_statuses': {
                **state.get('approach_statuses', {}),
                approach_index: status
            },
            'failed_approaches': state.get('failed_approaches', []) + ([approach_index] if status == 'failed' else []),
            'needs_refinement': False,
            'current_node': 'rethink_approach'
        }

    else:
        # Need refinement - RUN DIAGNOSTICS
        logger.info(f"🔧 Approach {approach_index} needs refinement (attempt {attempts + 1})")

        # Run diagnostics
        diagnostics = await self._run_diagnostics_batch(failed, state)

        # Generate refined queries
        refined = await self._generate_refined_queries(failed, diagnostics, state)

        # Record refinement attempt
        self._record_refinement_attempt(state, approach_index, diagnostics, refined)

        return {
            **state,
            'refined_queries': refined,
            'diagnostics': diagnostics,
            'needs_refinement': True,
            'refinement_attempts': {
                **refinement_attempts,
                approach_index: attempts + 1
            },
            'current_node': 'rethink_approach'
        }
```

**Routing**:
- If `needs_refinement == True` → Loop back to `generate_query`
- If `needs_refinement == False` → Approach complete, continue batch

---

### 3. Exit Point and Convergence: `check_sufficiency`

**Purpose**: After batch completes, evaluate if we have enough data

**Input State**:
- `discovered_data` - All data collected so far
- `current_approach_index` - Where we are
- `total_approaches` - Total available

**Logic**:
```python
async def check_sufficiency(self, state: AgentState) -> AgentState:
    """
    CONVERGENCE POINT after batch execution.
    Decides: continue to next batch or synthesize?
    """
    discovered_data = state['discovered_data']
    current_index = state['current_approach_index']
    total = state['total_approaches']

    logger.info(f"🔍 CONVERGENCE: Checking sufficiency after {current_index}/{total} approaches")
    logger.info(f"    Collected {len(discovered_data)} data items")

    # Check if all approaches exhausted
    all_exhausted = current_index >= total

    if all_exhausted:
        logger.info(f"✅ All approaches exhausted → synthesize_response")
        return {
            **state,
            'is_sufficient': True,
            'sufficiency_reasoning': 'All approaches exhausted',
            'current_node': 'check_sufficiency'
        }

    # Ask LLM: Is this sufficient?
    sufficiency_result = await self._evaluate_data_sufficiency(
        user_query=state['user_query'],
        discovered_data=discovered_data,
        state=state
    )

    is_sufficient = sufficiency_result['is_sufficient']
    confidence = sufficiency_result['confidence']
    reasoning = sufficiency_result['reasoning']

    logger.info(f"    Sufficiency: {is_sufficient} (confidence: {confidence})")
    logger.info(f"    Reasoning: {reasoning}")

    return {
        **state,
        'is_sufficient': is_sufficient,
        'sufficiency_confidence': confidence,
        'sufficiency_reasoning': reasoning,
        'current_node': 'check_sufficiency'
    }
```

**Routing**:
- If `is_sufficient == False` → `execute_batch_approaches` (next batch)
- If `is_sufficient == True` → `synthesize_response`

---

## Routing Functions

```python
def should_continue_after_rethink_approach(self, state: AgentState) -> str:
    """
    Routing after rethink_approach node.

    If needs refinement: Loop back to generate_query
    If complete: Continue to next approach in batch (or exit batch)
    """
    needs_refinement = state.get('needs_refinement', False)

    if needs_refinement:
        return "generate_query"  # Loop back for refinement
    else:
        # Approach is complete
        # In batch mode: execute_batch_approaches handles moving to next approach
        # In sequential mode: go to check_sufficiency
        execution_mode = state.get('execution_mode', 'batch')

        if execution_mode == 'sequential':
            return "check_sufficiency"
        else:
            # In batch mode, this is handled by execute_batch_approaches loop
            # Should not reach here during batch execution
            return "check_sufficiency"

def should_continue_after_sufficiency_check(self, state: AgentState) -> str:
    """
    Routing after check_sufficiency node.

    If insufficient: Next batch
    If sufficient: Synthesize
    """
    is_sufficient = state.get('is_sufficient', False)
    current_index = state.get('current_approach_index', 0)
    total = state.get('total_approaches', 0)

    all_exhausted = current_index >= total

    if is_sufficient or all_exhausted:
        return "synthesize_response"
    else:
        return "execute_batch_approaches"  # Next batch
```

---

## State Flow Example

### Scenario: 7 approaches, batch size 3, query refinement needed

```
START
  ↓
discovery_research
  → Generates 7 approaches
  ↓
execute_batch_approaches (batch 1: approaches 0-2)
  ├─ Approach 0: think → generate → execute → rethink
  │    └─ All queries succeed → complete (status: success)
  ├─ Approach 1: think → generate → execute → rethink
  │    ├─ 2 queries fail → needs_refinement=True
  │    └─ Loop: generate (refined) → execute → rethink
  │         └─ All succeed → complete (status: success)
  └─ Approach 2: think → generate → execute → rethink
       └─ All fail after 2 refinements → complete (status: failed)
  ↓
check_sufficiency
  ├─ Discovered: 2 data items (approaches 0, 1)
  ├─ LLM: "Insufficient, need more data"
  └─ Decision: Continue to next batch
  ↓
execute_batch_approaches (batch 2: approaches 3-5)
  ├─ Approach 3: complete (success)
  ├─ Approach 4: complete (success)
  └─ Approach 5: complete (partial)
  ↓
check_sufficiency
  ├─ Discovered: 5 data items total
  ├─ LLM: "Sufficient to answer"
  └─ Decision: Synthesize
  ↓
synthesize_response
  ↓
END
```

---

## Key Design Principles

### 1. **Single Responsibility Per Node**
- `think`: Only analyze scope
- `generate_query`: Only generate queries
- `execute_queries`: Only execute
- `rethink_approach`: Only decide completion/refinement

### 2. **Explicit Entry/Exit Points**
- Entry: `execute_batch_approaches` (batch selection)
- Exit: After all approaches in batch complete
- Convergence: `check_sufficiency` (sufficiency evaluation)

### 3. **Clear Loop Boundaries**
- **Inner loop**: `generate_query → execute_queries → rethink_approach → generate_query` (refinement)
- **Outer loop**: `execute_batch_approaches → check_sufficiency → execute_batch_approaches` (batches)

### 4. **State Management**
- Each approach has its own `ApproachExecutionTrace`
- Refinement state is per-approach
- Global state aggregates across approaches

### 5. **No Code Duplication**
- Same nodes used for sequential and batch modes
- No separate helper methods duplicating node logic
- LangGraph manages the flow

---

## Implementation Order

1. ✅ Update state schema (done)
2. ⏳ Implement `rethink_approach` node
3. ⏳ Implement `check_sufficiency` node
4. ⏳ Add routing functions
5. ⏳ Update `execute_batch_approaches` to use actual nodes
6. ⏳ Update workflow graph edges
7. ⏳ Test with sample query

---

This architecture ensures:
- ✅ Each approach has independent refinement loops
- ✅ No code duplication between sequential and batch modes
- ✅ Clear entry/exit points for parallel execution
- ✅ Proper sufficiency checking after each batch
- ✅ Full observability with execution traces
