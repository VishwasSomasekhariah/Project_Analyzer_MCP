# Query Plan Design - Multi-Step Cypher Generation

## Current Problem

The current `CoTQueryGeneration` model produces a **single Cypher query** with reasoning:

```python
class CoTQueryGeneration(BaseModel):
    cot_reasoning: CoTReasoningSteps
    cypher_query: str  # Single query!
    query_purpose: str
    entity_constraints: List[EntityConstraint]
```

**Issues**:
1. If query fails, we don't know WHY (path doesn't exist? entities missing? wrong relationship?)
2. Rethink step has no granular feedback about what went wrong
3. Validation can only say "query failed" not "step 2 failed - Block entities don't exist"
4. All assumptions (paths exist, entities exist, relationships valid) are validated together

---

## New Design: Query Plan with Validation Steps

### Example Scenario (SQ2 from V5 Run 1)

**Goal**: Retrieve Statement nodes within Block nodes of CreateWorkers Function that instantiate Type nodes

**Current Approach** (single query):
```cypher
MATCH (f:Function {name: 'CreateWorkers'})
      -[:CONTAINS]->(b:Block)
      -[:CONTAINS]->(s:Statement)
      -[:REFERENCES]->(t:Type)
RETURN s
```

If this fails, we don't know if it's because:
- CreateWorkers function doesn't exist?
- Function doesn't contain Block nodes?
- Block doesn't contain Statement nodes?
- Statement doesn't reference Type?

**New Approach** (query plan with steps):
```python
QueryPlan:
  Step 1 (Validation):
    Purpose: "Verify CreateWorkers function exists"
    Query: "MATCH (f:Function {name: 'CreateWorkers'}) RETURN count(f) as count"
    Expected: "count >= 1"
    OnFailure: "Entity 'CreateWorkers' doesn't exist - check for typos or alternatives"

  Step 2 (Path Validation):
    Purpose: "Check if Function contains Block nodes"
    Query: "MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block) RETURN count(b) as count"
    Expected: "count >= 1"
    OnFailure: "Path Function→Block doesn't exist for this function - try alternative relationships"

  Step 3 (Path Validation):
    Purpose: "Check if Block contains Statement nodes"
    Query: "MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement) RETURN count(s) as count"
    Expected: "count >= 1"
    OnFailure: "Path Block→Statement doesn't exist - statements may be direct children of Function"

  Step 4 (Main Query):
    Purpose: "Retrieve Statement nodes that reference Type"
    Query: "MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)-[:REFERENCES]->(t:Type) RETURN s"
    Expected: "results > 0"
    OnFailure: "Statement→Type relationship doesn't exist - try filtering Statement.text for 'new' keyword instead"
```

---

## Pydantic Model Design

```python
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional

class QueryStepType(str, Enum):
    """Type of query step in the plan."""
    ENTITY_CHECK = "entity_check"      # Verify entity exists
    PATH_CHECK = "path_check"          # Verify relationship path exists
    COUNT_CHECK = "count_check"        # Verify result count expectations
    DATA_RETRIEVAL = "data_retrieval"  # Main data retrieval query

class QueryStep(BaseModel):
    """A single step in the query execution plan."""
    step_number: int = Field(..., description="Sequential step number (1-based)")
    step_type: QueryStepType = Field(..., description="Type of validation this step performs")
    purpose: str = Field(..., description="What this step validates or retrieves")
    cypher_query: str = Field(..., description="Cypher query for this step")
    expected_outcome: str = Field(..., description="What success looks like (e.g., 'count >= 1', 'results > 0')")
    on_failure_guidance: str = Field(..., description="What it means if this step fails and what to try instead")
    depends_on_steps: List[int] = Field(
        default_factory=list,
        description="Previous step numbers this depends on (empty if independent)"
    )

    # Entity tracking for diagnostics
    entities_validated: List[EntityConstraint] = Field(
        default_factory=list,
        description="Which entities are validated in this step"
    )

class CypherQueryPlan(BaseModel):
    """Multi-step query execution plan with validation steps."""

    # Overall reasoning
    cot_reasoning: CoTReasoningSteps = Field(..., description="High-level reasoning for query approach")
    plan_overview: str = Field(..., description="Overview of what this plan will accomplish")

    # Query steps
    steps: List[QueryStep] = Field(..., description="Sequential query steps with validation")
    data_retrieval_step: int = Field(..., description="Which step number retrieves the actual data (others are validation)")

    # Fallback strategy
    fallback_hints: List[str] = Field(
        default_factory=list,
        description="Alternative approaches if all steps fail"
    )

    # Entity constraints for diagnostics
    all_entity_constraints: List[EntityConstraint] = Field(
        default_factory=list,
        description="All entity constraints across all steps"
    )
```

---

## Execution Flow

```python
async def _execute_query_plan(self, plan: CypherQueryPlan) -> Dict[str, Any]:
    """Execute a multi-step query plan."""

    execution_results = []

    for step in plan.steps:
        logger.info(f"📍 Executing Step {step.step_number}: {step.purpose}")

        # Execute query
        result = await self.cypher_server.execute_query(step.cypher_query)

        # Evaluate outcome
        success = self._evaluate_step_outcome(result, step.expected_outcome)

        execution_results.append({
            'step_number': step.step_number,
            'step_type': step.step_type,
            'purpose': step.purpose,
            'query': step.cypher_query,
            'success': success,
            'result': result,
            'expected': step.expected_outcome
        })

        if not success:
            logger.warning(f"⚠️ Step {step.step_number} failed!")
            logger.warning(f"💡 Guidance: {step.on_failure_guidance}")

            # If this is a validation step and it failed, no point continuing
            if step.step_type != QueryStepType.DATA_RETRIEVAL:
                logger.info(f"🛑 Stopping execution - validation failed at step {step.step_number}")
                break

    return {
        'plan': plan,
        'execution_results': execution_results,
        'final_step_success': execution_results[-1]['success'] if execution_results else False,
        'failed_at_step': next((r['step_number'] for r in execution_results if not r['success']), None)
    }
```

---

## Rethink Integration

During the rethink step, we now have granular failure information:

```python
async def _cot_rethink_step(self, plan_result: Dict[str, Any]) -> CoTAnalysisResult:
    """Analyze query plan execution with detailed step-by-step feedback."""

    failed_step = plan_result.get('failed_at_step')

    if failed_step:
        failed_step_info = plan_result['execution_results'][failed_step - 1]

        analysis_context = f"""
        Query plan failed at Step {failed_step}:

        Purpose: {failed_step_info['purpose']}
        Type: {failed_step_info['step_type']}
        Query: {failed_step_info['query']}
        Expected: {failed_step_info['expected']}

        Guidance: {failed_step_info['on_failure_guidance']}

        All steps executed:
        {self._format_step_results(plan_result['execution_results'])}
        """
    else:
        analysis_context = "All validation steps passed but no data returned..."

    # Send to LLM for analysis
    return await self._call_llm_analysis(analysis_context)
```

---

## Prompt Updates

The LLM prompt needs to instruct the model to generate a plan instead of a single query:

```
Generate a QUERY EXECUTION PLAN with multiple validation steps.

Your plan should include:
1. Entity Validation Steps: Verify entities mentioned exist (e.g., Function named 'CreateWorkers')
2. Path Validation Steps: Verify relationship paths exist (e.g., Function→Block→Statement)
3. Data Retrieval Step: The main query to get the actual data

For EACH step, provide:
- Purpose: What this step validates
- Cypher Query: The query to run
- Expected Outcome: What success looks like (e.g., "count >= 1")
- On Failure Guidance: What it means if this fails and what to try instead

Example for query "Find statements in CreateWorkers that instantiate types":

Step 1 (Entity Check):
  Purpose: Verify CreateWorkers function exists
  Query: MATCH (f:Function {name: 'CreateWorkers'}) RETURN count(f) as count
  Expected: count >= 1
  OnFailure: Entity doesn't exist - try fuzzy match or alternative names

Step 2 (Path Check):
  Purpose: Check Function contains Block nodes
  Query: MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block) RETURN count(b) as count
  Expected: count >= 1
  OnFailure: Function has no blocks - statements may be direct children

Step 3 (Data Retrieval):
  Purpose: Get statements within blocks
  Query: MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement) WHERE s.text CONTAINS 'new' RETURN s
  Expected: results > 0
  OnFailure: No 'new' statements found - try different text filter
```

---

## Benefits

1. **Granular Failure Feedback**: Know exactly which assumption failed
2. **Better Rethink Decisions**: LLM can see which validation step failed and why
3. **Faster Debugging**: Don't need entity diagnostics if entity validation step shows it exists
4. **Incremental Validation**: Stop early if entity doesn't exist, don't run full query
5. **Self-Documenting**: Each step explains what it's checking

---

## Migration Path

1. ✅ Define new Pydantic models (above)
2. 🔄 Update query generation prompt to request plans
3. 🔄 Update execution flow to run steps sequentially
4. 🔄 Update rethink to analyze step-by-step results
5. 🔄 Update validation to check each step's schema compliance
6. 📊 Test with V6 benchmark

---

## Example Plan Output

For SQ2: "Retrieve all Statement nodes contained within the Block nodes of the 'CreateWorkers' Function node that instantiate Type nodes"

```json
{
  "cot_reasoning": {
    "step1_perspective": "Find statements in CreateWorkers blocks that create type instances",
    "step2_premise_validation": "Using P1 (CreateWorkers in WorkerFactory) and P2 (statements instantiate types)",
    "step3_path_trace": "Function→Block→Statement, looking for 'new' keyword",
    "step4_filters": "Function.name='CreateWorkers', Statement.text CONTAINS 'new'",
    "step5_return": "Statement nodes with text property",
    "step6_optimize": "No ordering needed, limit results if many"
  },
  "plan_overview": "Validate CreateWorkers exists, check Function→Block→Statement path, then retrieve statements with 'new' keyword",
  "steps": [
    {
      "step_number": 1,
      "step_type": "entity_check",
      "purpose": "Verify CreateWorkers function exists in database",
      "cypher_query": "MATCH (f:Function {name: 'CreateWorkers'}) RETURN count(f) as count",
      "expected_outcome": "count >= 1",
      "on_failure_guidance": "Function 'CreateWorkers' not found - try fuzzy matching or check for typos",
      "depends_on_steps": [],
      "entities_validated": [{"var": "f", "label": "Function", "property": "name", "value": "CreateWorkers"}]
    },
    {
      "step_number": 2,
      "step_type": "path_check",
      "purpose": "Verify Function contains Block nodes",
      "cypher_query": "MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block) RETURN count(b) as count",
      "expected_outcome": "count >= 1",
      "on_failure_guidance": "CreateWorkers has no Block nodes - statements may be direct children of Function",
      "depends_on_steps": [1],
      "entities_validated": []
    },
    {
      "step_number": 3,
      "step_type": "data_retrieval",
      "purpose": "Retrieve Statement nodes within Blocks that contain 'new' keyword",
      "cypher_query": "MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement) WHERE s.text CONTAINS 'new' RETURN s",
      "expected_outcome": "results > 0",
      "on_failure_guidance": "No statements with 'new' keyword found - try different text patterns or check Statement→Type relationship",
      "depends_on_steps": [1, 2],
      "entities_validated": []
    }
  ],
  "data_retrieval_step": 3,
  "fallback_hints": [
    "If Block path doesn't exist, try direct Function→Statement path",
    "If 'new' keyword filter returns nothing, try Statement→Type REFERENCES relationship",
    "Consider using CALLS relationship to find constructor functions instead"
  ]
}
```

This gives the agent:
- **3 clear steps** to execute
- **Validation before data retrieval**
- **Specific guidance** if each step fails
- **Fallback strategies** if the whole approach fails

---

## Next Steps

Would you like me to:
1. Implement the new Pydantic models?
2. Update the query generation prompt?
3. Modify the execution flow to handle plans?
4. Update rethink to analyze step-by-step results?
