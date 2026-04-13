# Rethink and Sufficiency Check Separation Plan

## Problem Statement

**Current Architecture Flaw:**
The current workflow has a single `rethink` node that happens AFTER collecting results from all batch approaches. This means:

1. ❌ Approach 1 runs queries → Approach 2 runs queries → Approach 3 runs queries
2. ❌ Then ONE rethink tries to handle refinement for ALL of them together
3. ❌ Query refinement can't loop back to individual approaches
4. ❌ Each approach can't independently refine and retry

**Why This Doesn't Make Sense:**
- If Approach 1's queries fail, we should refine and retry Approach 1 immediately
- We shouldn't wait for all other approaches to finish
- Each approach should be self-contained with its own refinement loop
- Mixing results from different approaches in one rethink node creates confusion

## Correct Architecture

### Two Separate Responsibilities:

#### 1. **`rethink_approach`** (Per-Approach Node)
**Purpose**: Handle query refinement and approach completion FOR ONE APPROACH

**Responsibilities**:
- Run diagnostics on failed queries (within this approach)
- Refine queries based on diagnostics
- Decide if refinement is needed → loop back to `generate_query` or `think`
- Mark approach as complete/failed when done
- Clean up citations and select final data for THIS approach only
- Add approach's final results to `discovered_data`

**Routing Options**:
- `generate_query` - If queries need refinement
- `think` - If approach strategy needs adjustment (rare)
- NEXT in batch or `check_sufficiency` - If approach is complete

#### 2. **`check_sufficiency`** (After-Batch Node)
**Purpose**: Decide if we have enough data to answer the question

**Responsibilities**:
- Check if accumulated `discovered_data` is sufficient
- Evaluate if we need more approaches
- Decide next batch or synthesis

**Routing Options**:
- `execute_batch_approaches` - Need more data, run next batch
- `synthesize_response` - Have enough data, generate answer

---

## New Workflow Flow

```
START
  ↓
discovery_research (generate all approaches)
  ↓
execute_batch_approaches (select batch of N approaches)
  ↓
  ┌─────────────────────────────────────────────────────┐
  │  FOR EACH APPROACH IN BATCH (parallel or sequential) │
  │                                                      │
  │  think                                               │
  │    ↓                                                 │
  │  generate_query                                      │
  │    ↓                                                 │
  │  execute_queries                                     │
  │    ↓                                                 │
  │  rethink_approach ←──────────────────┐              │
  │    ├─ Run diagnostics on failures    │              │
  │    ├─ Refine queries if needed       │              │
  │    ├─ Clean up citations            │              │
  │    └─ Mark approach complete         │              │
  │       │                              │              │
  │       ├─ If needs refinement ────────┘              │
  │       │   (back to generate_query)                  │
  │       │                                              │
  │       └─ If complete                                 │
  │          (add to discovered_data)                    │
  └──────────────────────────────────────────────────────┘
  ↓
check_sufficiency (after ALL approaches in batch complete)
  ├─ Evaluate discovered_data
  ├─ Check if sufficient
  │
  ├─ If insufficient → execute_batch_approaches (next batch)
  │
  └─ If sufficient → synthesize_response
```

---

## Implementation Plan

### Phase 1: Split Rethink Logic

#### Step 1: Create `rethink_approach` Node
**Location**: `src/core/workflow/nodes.py`

```python
async def rethink_approach(self, state: AgentState) -> AgentState:
    """
    Node: Rethink Approach - Handle refinement and completion for ONE approach.

    This node runs WITHIN an approach's execution cycle to:
    1. Analyze query results for THIS approach only
    2. Run diagnostics on failed queries
    3. Decide if refinement is needed
    4. Clean up citations and final data for THIS approach
    5. Mark approach as complete or needs-refinement

    Routing:
    - generate_query: If queries need refinement (loop back)
    - think: If approach strategy needs change (rare)
    - NEXT: If approach is complete (continue batch or check_sufficiency)
    """
    logger.info("🤔 Node: rethink_approach")

    current_approach_index = state.get('current_approach_index', 0)
    approach_raw_results = state.get('approach_raw_results', {})

    # Get results for ONLY this approach
    approach_results = approach_raw_results.get(current_approach_index, [])

    # Step 1: Analyze results
    successful_queries = [r for r in approach_results if r['status'] == 'success']
    failed_queries = [r for r in approach_results if r['status'] in ['empty_result', 'error']]

    logger.info(f"📊 Approach {current_approach_index}: {len(successful_queries)} success, {len(failed_queries)} failed")

    # Step 2: If no failures, mark approach complete
    if not failed_queries:
        logger.info(f"✅ Approach {current_approach_index} complete - no refinement needed")

        # Clean up citations and add to discovered_data
        cleaned_data = self._clean_approach_data(successful_queries)

        return {
            **state,
            'discovered_data': state.get('discovered_data', []) + [cleaned_data],
            'approach_statuses': {
                **state.get('approach_statuses', {}),
                current_approach_index: 'success'
            },
            'needs_refinement': False,
            'current_node': 'rethink_approach'
        }

    # Step 3: Check if we've already tried refinement
    refinement_attempts = state.get('refinement_attempts', {}).get(current_approach_index, 0)
    max_refinement_attempts = 2

    if refinement_attempts >= max_refinement_attempts:
        logger.info(f"⚠️ Approach {current_approach_index} max refinements reached - marking failed")

        # Mark approach as failed, keep successful queries if any
        cleaned_data = self._clean_approach_data(successful_queries) if successful_queries else None

        return {
            **state,
            'discovered_data': state.get('discovered_data', []) + ([cleaned_data] if cleaned_data else []),
            'approach_statuses': {
                **state.get('approach_statuses', {}),
                current_approach_index: 'failed'
            },
            'failed_approaches': state.get('failed_approaches', []) + [current_approach_index],
            'needs_refinement': False,
            'current_node': 'rethink_approach'
        }

    # Step 4: Run diagnostics and prepare refinement
    logger.info(f"🔧 Approach {current_approach_index} needs refinement - running diagnostics")

    diagnostics = await self._run_diagnostics_batch(failed_queries, state)
    refined_queries = await self._generate_refined_queries(failed_queries, diagnostics, state)

    # Step 5: Set up state for refinement loop
    return {
        **state,
        'refined_queries': refined_queries,
        'diagnostics': diagnostics,
        'needs_refinement': True,
        'refinement_attempts': {
            **state.get('refinement_attempts', {}),
            current_approach_index: refinement_attempts + 1
        },
        'current_node': 'rethink_approach'
    }
```

#### Step 2: Create `check_sufficiency` Node
**Location**: `src/core/workflow/nodes.py`

```python
async def check_sufficiency(self, state: AgentState) -> AgentState:
    """
    Node: Check Sufficiency - Decide if we have enough data after batch completes.

    This node runs AFTER a batch of approaches completes to:
    1. Evaluate all accumulated discovered_data
    2. Determine if we have sufficient information
    3. Decide if we need to run another batch

    Routing:
    - execute_batch_approaches: Need more data (next batch)
    - synthesize_response: Have enough data (done)
    """
    logger.info("📊 Node: check_sufficiency")

    discovered_data = state.get('discovered_data', [])
    current_approach_index = state.get('current_approach_index', 0)
    total_approaches = len(state.get('discovery_research', {}).get('data_collection_approaches', []))

    logger.info(f"🔍 Checking sufficiency: {len(discovered_data)} data items from {current_approach_index}/{total_approaches} approaches")

    # Step 1: Check if we have any data
    if not discovered_data:
        logger.info("⚠️ No data collected yet")
        has_data = False
    else:
        has_data = True

    # Step 2: Call LLM to evaluate sufficiency
    sufficiency_result = await self._evaluate_data_sufficiency(
        user_query=state.get('user_query', ''),
        discovered_data=discovered_data,
        state=state
    )

    is_sufficient = sufficiency_result.get('is_sufficient', False)
    confidence = sufficiency_result.get('confidence', 0.0)
    reasoning = sufficiency_result.get('reasoning', '')

    logger.info(f"📊 Sufficiency: {is_sufficient} (confidence: {confidence})")
    logger.info(f"💭 Reasoning: {reasoning}")

    # Step 3: Decide routing
    if is_sufficient or current_approach_index >= total_approaches:
        logger.info("✅ Data is sufficient or all approaches exhausted → synthesize_response")
        return {
            **state,
            'is_sufficient': True,
            'sufficiency_confidence': confidence,
            'sufficiency_reasoning': reasoning,
            'current_node': 'check_sufficiency'
        }
    else:
        logger.info(f"⚠️ Data insufficient → execute next batch (starting at {current_approach_index})")
        return {
            **state,
            'is_sufficient': False,
            'sufficiency_confidence': confidence,
            'sufficiency_reasoning': reasoning,
            'current_node': 'check_sufficiency'
        }
```

### Phase 2: Update Routing Logic

#### Step 3: Add Routing Functions
**Location**: `src/core/workflow/nodes.py`

```python
def should_continue_after_rethink_approach(self, state: AgentState) -> str:
    """
    Routing: After rethink_approach node completes.

    Options:
    - generate_query: Approach needs refinement (loop back)
    - think: Approach strategy needs change (rare, not implemented yet)
    - check_sufficiency: Approach complete AND last in batch
    - execute_batch_approaches: Approach complete BUT more in batch (NOT USED - batch handles this)

    Note: In batch mode, when approach completes, we don't route anywhere -
    the batch execution continues to next approach automatically.
    """
    needs_refinement = state.get('needs_refinement', False)

    if needs_refinement:
        logger.info("🔄 Decision: generate_query - Approach needs refinement")
        return "generate_query"

    # Approach is complete - in batch mode, batch handler continues automatically
    # In sequential mode, we check sufficiency
    execution_mode = state.get('execution_mode', 'batch')

    if execution_mode == 'sequential':
        logger.info("✅ Decision: check_sufficiency - Approach complete (sequential mode)")
        return "check_sufficiency"
    else:
        # In batch mode, the approach is done - batch handler continues
        # This should not be reached in batch mode
        logger.info("✅ Decision: check_sufficiency - Approach complete (batch mode)")
        return "check_sufficiency"

def should_continue_after_sufficiency_check(self, state: AgentState) -> str:
    """
    Routing: After check_sufficiency node completes.

    Options:
    - execute_batch_approaches: Need more data (next batch)
    - synthesize_response: Have enough data (done)
    """
    is_sufficient = state.get('is_sufficient', False)
    current_approach_index = state.get('current_approach_index', 0)
    total_approaches = len(state.get('discovery_research', {}).get('data_collection_approaches', []))

    # Check if all approaches exhausted
    all_exhausted = current_approach_index >= total_approaches

    if is_sufficient or all_exhausted:
        logger.info("✅ Decision: synthesize_response - Sufficient data or all approaches exhausted")
        return "synthesize_response"
    else:
        logger.info("🔄 Decision: execute_batch_approaches - Need more data")
        return "execute_batch_approaches"
```

### Phase 3: Update Workflow Graph

#### Step 4: Update Graph Construction
**Location**: `src/core/workflow/adaptive_cpg_workflow.py`

```python
# OLD: Single rethink node
workflow.add_node("rethink", self.workflow_nodes.rethink)

# NEW: Two separate nodes
workflow.add_node("rethink_approach", self.workflow_nodes.rethink_approach)
workflow.add_node("check_sufficiency", self.workflow_nodes.check_sufficiency)

# Update edges from execute_queries
workflow.add_conditional_edges(
    "execute_queries",
    self.workflow_nodes.should_continue_after_execute,
    {
        "rethink_approach": "rethink_approach",  # Changed from "rethink"
        "generate_query": "generate_query"  # Syntax error retry
    }
)

# NEW: Edges from rethink_approach
workflow.add_conditional_edges(
    "rethink_approach",
    self.workflow_nodes.should_continue_after_rethink_approach,
    {
        "generate_query": "generate_query",  # Refinement loop
        "check_sufficiency": "check_sufficiency"  # Approach complete
    }
)

# NEW: Edges from check_sufficiency
workflow.add_conditional_edges(
    "check_sufficiency",
    self.workflow_nodes.should_continue_after_sufficiency_check,
    {
        "execute_batch_approaches": "execute_batch_approaches",  # Next batch
        "synthesize_response": "synthesize_response"  # Done
    }
)
```

---

## State Schema Updates

### New State Fields

```python
class AgentState(TypedDict):
    # ... existing fields ...

    # NEW: Per-approach refinement tracking
    needs_refinement: bool  # Does current approach need refinement?
    refinement_attempts: Dict[int, int]  # approach_index -> attempt_count
    refined_queries: List[Dict]  # Refined queries for current approach
    diagnostics: List[Dict]  # Diagnostic results for current approach

    # NEW: Sufficiency tracking
    is_sufficient: bool  # Is accumulated data sufficient?
    sufficiency_confidence: float  # LLM confidence in sufficiency
    sufficiency_reasoning: str  # Why sufficient/insufficient
```

---

## Migration Strategy

### Phase 1: Preparation (Non-Breaking)
1. ✅ Add new nodes (`rethink_approach`, `check_sufficiency`) alongside old `rethink`
2. ✅ Add new routing functions
3. ✅ Add new state fields
4. ✅ Keep old `rethink` node working

### Phase 2: Sequential Mode Migration
1. Update sequential execution to use new nodes
2. Test thoroughly
3. Verify refinement loops work

### Phase 3: Batch Mode Migration
1. Update batch execution to use new nodes
2. Each approach in batch uses `rethink_approach` independently
3. Test thoroughly

### Phase 4: Cleanup
1. Remove old `rethink` node
2. Remove old routing logic
3. Update documentation

---

## Benefits of This Architecture

### ✅ **Self-Contained Approaches**
- Each approach has its own think → generate → execute → rethink loop
- Refinement happens immediately within the approach
- No cross-approach contamination

### ✅ **Clear Separation of Concerns**
- `rethink_approach`: Handle ONE approach's refinement
- `check_sufficiency`: Decide if ALL approaches' data is enough

### ✅ **Better Parallelization**
- Each approach can refine independently
- No need to synchronize refinement across approaches
- Cleaner state management

### ✅ **Easier Debugging**
- Can trace one approach's complete lifecycle
- Clear boundaries between approach execution and batch coordination
- Refinement loops are obvious in workflow graph

### ✅ **LangGraph Best Practices**
- Each node has single responsibility
- Clear routing logic
- Proper loop handling within approach

---

## Example Flow: Single Approach with Refinement

```
Approach 1:
  think
    ↓
  generate_query (generates 3 queries)
    ↓
  execute_queries (2 succeed, 1 fails)
    ↓
  rethink_approach
    ├─ Diagnose why query 3 failed
    ├─ Generate refined query 3'
    ├─ needs_refinement = True
    └─ ROUTE: generate_query
    ↓
  generate_query (uses refined query 3')
    ↓
  execute_queries (refined query succeeds!)
    ↓
  rethink_approach
    ├─ All queries successful
    ├─ Clean up citations
    ├─ Add to discovered_data
    ├─ needs_refinement = False
    └─ ROUTE: check_sufficiency (or next approach in batch)
```

---

## Testing Plan

### Unit Tests
1. Test `rethink_approach` with all-successful queries
2. Test `rethink_approach` with failed queries → refinement
3. Test `rethink_approach` with max refinement attempts
4. Test `check_sufficiency` with sufficient data
5. Test `check_sufficiency` with insufficient data

### Integration Tests
1. Test single approach with refinement loop (sequential)
2. Test batch of approaches where each refines independently
3. Test sufficiency check after batch
4. Test multiple batches until sufficient

### End-to-End Tests
1. Run real query with approaches that need refinement
2. Verify each approach's refinement happens independently
3. Verify sufficiency check works after batch
4. Verify next batch runs if insufficient

---

## Implementation Checklist

### Phase 1: Core Nodes
- [ ] Create `rethink_approach` node
- [ ] Create `check_sufficiency` node
- [ ] Add helper method `_clean_approach_data`
- [ ] Add helper method `_run_diagnostics_batch`
- [ ] Add helper method `_generate_refined_queries`
- [ ] Add helper method `_evaluate_data_sufficiency`

### Phase 2: Routing
- [ ] Create `should_continue_after_rethink_approach`
- [ ] Create `should_continue_after_sufficiency_check`
- [ ] Update `should_continue_after_execute` to route to `rethink_approach`

### Phase 3: State Schema
- [ ] Add `needs_refinement` field
- [ ] Add `refinement_attempts` field
- [ ] Add `refined_queries` field
- [ ] Add `diagnostics` field
- [ ] Add `is_sufficient` field
- [ ] Add `sufficiency_confidence` field
- [ ] Add `sufficiency_reasoning` field

### Phase 4: Graph Updates
- [ ] Add `rethink_approach` node to graph
- [ ] Add `check_sufficiency` node to graph
- [ ] Update edges from `execute_queries`
- [ ] Add edges from `rethink_approach`
- [ ] Add edges from `check_sufficiency`

### Phase 5: Batch Mode Updates
- [ ] Update `_execute_single_approach_queries` to use `rethink_approach` logic
- [ ] Ensure each approach completes independently
- [ ] Update batch completion to route to `check_sufficiency`

### Phase 6: Testing
- [ ] Unit tests for new nodes
- [ ] Integration tests for refinement loops
- [ ] End-to-end test with real query
- [ ] Verify server logs clean

### Phase 7: Cleanup
- [ ] Remove old `rethink` node
- [ ] Remove old routing logic
- [ ] Update documentation
- [ ] Archive old implementation

---

## Timeline Estimate

- **Phase 1-2 (Nodes + Routing)**: 2-3 hours
- **Phase 3-4 (State + Graph)**: 1-2 hours
- **Phase 5 (Batch Updates)**: 2-3 hours
- **Phase 6 (Testing)**: 2-3 hours
- **Phase 7 (Cleanup)**: 1 hour

**Total**: ~10-14 hours of focused development

---

## Notes

1. This refactoring aligns with LangGraph best practices for loops and branching
2. Each approach becomes truly independent
3. Sufficiency checking becomes explicit and clear
4. The workflow graph will be much easier to visualize and understand
5. This sets up the foundation for eventual LangGraph Send API migration (from LANGGRAPH_BATCH_REFACTORING.md)
