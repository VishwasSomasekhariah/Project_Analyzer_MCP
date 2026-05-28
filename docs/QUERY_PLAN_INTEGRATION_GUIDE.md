# Query Plan Integration Guide

This guide shows exactly how to integrate the new query plan mode into the adaptive query agent.

## Quick Start

The query plan infrastructure is **fully implemented** and ready to use. To activate it:

1. Import the new prompt function
2. Add feature flag to agent initialization
3. Modify query generation step to use plans
4. Run benchmark

---

## Step 1: Add Import to adaptive_query_agent.py

At the top of the file where prompts are imported:

```python
from .prompts import (
    get_cot_think_prompt,
    get_cot_generate_query_prompt,
    get_cot_generate_query_plan_prompt,  # ADD THIS
    get_cot_analyze_results_prompt,
    get_approach_synthesis_prompt
)
```

**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` line 18

---

## Step 2: Add Feature Flag to Agent Initialization

In the `AdaptiveQueryAgent.__init__()` method:

```python
class AdaptiveQueryAgent:
    def __init__(
        self,
        llm_service,
        cypher_server,
        state: AdaptiveQueryAgentState,
        approach_packet: Optional[Dict[str, Any]] = None,
        use_query_plans: bool = False  # ADD THIS PARAMETER
    ):
        self.llm_service = llm_service
        self.cypher_server = cypher_server
        self.state = state
        self.approach_packet = approach_packet
        self.use_query_plans = use_query_plans  # ADD THIS ATTRIBUTE
```

**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` approx line 147-160

---

## Step 3: Modify Query Generation Step

Find the `_cot_generate_query_step()` method and modify it:

```python
async def _cot_generate_query_step(self, previous_queries: str) -> Dict[str, Any]:
    """
    CoT Step: Generate next Cypher query or query plan.
    """
    try:
        if self.use_query_plans:
            # NEW: Generate multi-step query plan
            base_prompt = get_cot_generate_query_plan_prompt(
                user_query=self.state.user_query,
                approach_details=self.state.approach_details,
                project_name=self.state.project_name,
                schema=self.state.schema,
                previous_queries=previous_queries,
                last_analysis_hint=self.state.last_analysis_hint,
                approach_packet=self.approach_packet
            )

            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are a Cypher query plan expert.",
                user_prompt=base_prompt,
                response_model=CypherQueryPlan,  # Query plan model
                model_name="gpt-4o",
                call_type="cot_generate_plan",
                approach_index=self.state.approach_index,
                call_purpose=f"Generate query plan - iteration {self.state.iteration}"
            )

            # Track tokens
            self._update_token_tracking_from_result('generate_plan', result)

            # Return query plan result
            return {
                'query_plan': result,
                'plan_overview': result.plan_overview,
                'cot_reasoning': result.cot_reasoning,
                'steps': result.steps,
                'data_retrieval_step': result.data_retrieval_step,
                'fallback_hints': result.fallback_hints
            }

        else:
            # ORIGINAL: Generate single query (backward compatible)
            base_prompt = get_cot_generate_query_prompt(
                user_query=self.state.user_query,
                approach_details=self.state.approach_details,
                project_name=self.state.project_name,
                schema=self.state.schema,
                previous_queries=previous_queries,
                last_analysis_hint=self.state.last_analysis_hint,
                approach_packet=self.approach_packet
            )

            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are a Cypher query expert.",
                user_prompt=base_prompt,
                response_model=CoTQueryGeneration,
                model_name="gpt-4o",
                call_type="cot_generate",
                approach_index=self.state.approach_index,
                call_purpose=f"Generate query - iteration {self.state.iteration}"
            )

            # Track tokens
            self._update_token_tracking_from_result('generate', result)

            # Return single query result
            return {
                'cypher_query': result.cypher_query,
                'query_purpose': result.query_purpose,
                'cot_reasoning': result.cot_reasoning,
                'entity_constraints': result.entity_constraints
            }

    except ValidationError as e:
        # ... existing error handling ...
```

**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` approx line 390-450

---

## Step 4: Modify Main Agent Loop

In the `execute_approach()` method, handle both query modes:

```python
async def execute_approach(self) -> Dict[str, Any]:
    """Main agent loop."""

    while self.state.iteration < self.state.max_iterations and not self.state.is_sufficient:
        self.state.iteration += 1

        # Generate query or plan
        query_result = await self._cot_generate_query_step(previous_queries)

        if self.use_query_plans:
            # Execute query plan (multi-step validation)
            plan_result = await self._execute_query_plan(query_result['query_plan'])

            # Analyze plan execution
            analysis_result = await self._cot_analyze_plan_results(plan_result)

            # Extract data from successful retrieval step
            if plan_result['final_step_success']:
                data_step = plan_result['execution_results'][query_result['data_retrieval_step'] - 1]
                execution_result = data_step['result']
            else:
                execution_result = {'results': [], 'error': None, 'success': False}

        else:
            # Execute single query (original flow)
            execution_result = await self._execute_query(query_result['cypher_query'])

            # Analyze results
            analysis_result = await self._cot_analyze_results_step(query_result, execution_result)

        # Store query history (unified format)
        self.state.queries_executed.append({
            'iteration': self.state.iteration,
            'mode': 'plan' if self.use_query_plans else 'single',
            'query': query_result.get('query_plan') or query_result.get('cypher_query'),
            'reasoning': query_result['cot_reasoning'],
            'results': execution_result.get('results', []),
            'error': execution_result.get('error'),
            'result_count': len(execution_result.get('results', [])),
            'analysis': analysis_result
        })

        # Check sufficiency
        if analysis_result['recommendation'] == RecommendationType.SUFFICIENT:
            self.state.is_sufficient = True
            self.state.sufficiency_reason = analysis_result['analysis']
        elif analysis_result['recommendation'] == RecommendationType.STOP:
            break

    # Synthesize final answer
    return await self._synthesize_approach_answer()
```

**Location**: `/opt/genpod/src/core/workflow/adaptive_query_agent.py` approx line 220-380

---

## Step 5: Update Workflow to Enable Query Plans

In the workflow that creates the agent:

```python
# In research_workflow.py or wherever agents are created
agent = AdaptiveQueryAgent(
    llm_service=llm_service,
    cypher_server=cypher_server,
    state=agent_state,
    approach_packet=approach_packet,
    use_query_plans=True  # ENABLE QUERY PLANS
)
```

---

## Testing the Integration

### Test 1: Single Query Generation
```python
# With use_query_plans=False
result = await agent._cot_generate_query_step("")
assert 'cypher_query' in result  # Should generate single query
```

### Test 2: Query Plan Generation
```python
# With use_query_plans=True
result = await agent._cot_generate_query_step("")
assert 'query_plan' in result
assert 'steps' in result
assert len(result['steps']) >= 2  # At least entity check + data retrieval
```

### Test 3: Plan Execution
```python
# With use_query_plans=True
query_result = await agent._cot_generate_query_step("")
plan_result = await agent._execute_query_plan(query_result['query_plan'])

assert 'execution_results' in plan_result
assert 'failed_at_step' in plan_result
for step_result in plan_result['execution_results']:
    assert 'success' in step_result
    assert 'on_failure_guidance' in step_result
```

### Test 4: Plan Analysis
```python
# With use_query_plans=True
query_result = await agent._cot_generate_query_step("")
plan_result = await agent._execute_query_plan(query_result['query_plan'])
analysis = await agent._cot_analyze_plan_results(plan_result)

assert 'analysis' in analysis
assert 'recommendation' in analysis
if plan_result['failed_at_step']:
    assert 'failed_at_step' in analysis
```

---

## Running V6 Benchmark

Modify the benchmark script to enable query plans:

```python
# In benchmark_workflow_performance.py or similar

# Original V5 mode
agent_v5 = AdaptiveQueryAgent(
    llm_service=llm_service,
    cypher_server=cypher_server,
    state=state,
    approach_packet=packet,
    use_query_plans=False  # V5: Single queries
)

# New V6 mode
agent_v6 = AdaptiveQueryAgent(
    llm_service=llm_service,
    cypher_server=cypher_server,
    state=state,
    approach_packet=packet,
    use_query_plans=True  # V6: Query plans
)

# Run both and compare
v5_result = await agent_v5.execute_approach()
v6_result = await agent_v6.execute_approach()

print(f"V5 Success: {v5_result['is_sufficient']}")
print(f"V6 Success: {v6_result['is_sufficient']}")
print(f"V5 Tokens: {v5_result['tokens_used']}")
print(f"V6 Tokens: {v6_result['tokens_used']}")
```

---

## Monitoring and Debugging

### Enable Debug Logging

The execution flow already includes detailed logging:

```
📋 Executing query plan: Validate CreateWorkers exists, check paths, retrieve statements
   Total steps: 3, Data retrieval at step 3

📍 Executing Step 1/3: Verify CreateWorkers function exists
   Type: entity_check
   Expected: count >= 1
   ✅ Step 1 succeeded

📍 Executing Step 2/3: Check if Function contains Block nodes
   Type: path_check
   Expected: count >= 1
   ⚠️ Step 2 failed!
   💡 Guidance: CreateWorkers has no Block nodes - try direct Function→Statement path
   🛑 Stopping execution - validation failed at step 2

📊 Query plan execution complete:
   Steps executed: 2/3
   Final step success: False
   Failed at step: 2
```

### Check Execution Results

```python
plan_result = await agent._execute_query_plan(query_plan)

for step_result in plan_result['execution_results']:
    print(f"Step {step_result['step_number']}: {step_result['purpose']}")
    print(f"  Success: {step_result['success']}")
    if not step_result['success']:
        print(f"  Guidance: {step_result['on_failure_guidance']}")
```

---

## Rollback Plan

If query plans cause issues:

1. Set `use_query_plans=False` in agent initialization
2. Agent will revert to original single query mode
3. All V5 functionality remains intact

The implementation is **fully backward compatible**.

---

## Expected Results

Based on V5 analysis:

**V5 (Single Query Mode)**: 60% success (3/5 runs)
- Run 1: Failed (path discovery issue)
- Run 2: Failed (wrong query patterns)
- Runs 3-5: Succeeded

**V6 (Query Plan Mode)**: Expected 80-100% success (4-5/5 runs)
- Better failure diagnostics
- Granular step-by-step validation
- Clearer guidance for retries

---

## Files Modified

All implementation is already complete in:

- ✅ `/opt/genpod/src/core/workflow/adaptive_query_agent.py`
- ✅ `/opt/genpod/src/core/workflow/prompts.py`

Only integration changes needed:
- 🔄 Add import
- 🔄 Add feature flag
- 🔄 Modify generation step
- 🔄 Modify main loop
- 🔄 Enable in workflow

**Estimated Time**: 30-60 minutes for integration + testing
