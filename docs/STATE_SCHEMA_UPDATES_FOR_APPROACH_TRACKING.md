# State Schema Updates for Per-Approach Execution Tracking

## Overview

Updated the state schema to support **parallel-optimized architecture** with comprehensive per-approach execution tracking. This allows us to show users the complete journey each approach went through.

## Key Changes

### 1. New Pydantic Model: `LLMCallMetrics`

Tracks token usage and cost for each LLM call:

```python
class LLMCallMetrics(BaseModel):
    """Token usage and cost metrics for a single LLM call"""
    call_type: str  # 'think', 'generate', 'rethink', 'diagnostics', etc.
    timestamp: float
    model_name: str  # 'gpt-4', 'claude-3.5-sonnet', etc.

    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int  # Auto-calculated

    # Cost estimation
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float  # Auto-calculated

    # Timing
    latency_seconds: Optional[float]

    # Context
    call_purpose: Optional[str]
```

### 2. New Pydantic Model: `ApproachExecutionTrace`

Complete execution trace for a single approach - captures the full lifecycle:

```python
class ApproachExecutionTrace(BaseModel):
    """
    Complete execution trace for a single approach.
    Tracks: think → generate → execute → rethink (with refinement loops)
    """
    # Identification
    approach_index: int
    approach_name: str
    approach_strategy: str

    # Lifecycle
    start_time: float  # Unix timestamp
    end_time: Optional[float]
    duration_seconds: Optional[float]  # Auto-calculated

    # Step-by-step history
    think_step: Optional[Dict[str, Any]]
    generate_cycles: List[Dict[str, Any]]  # Original + refinements
    execute_cycles: List[Dict[str, Any]]  # All execution attempts
    rethink_cycles: List[Dict[str, Any]]  # All rethink analyses

    # Query tracking
    original_queries: List[Dict[str, Any]]
    refined_queries: List[Dict[str, Any]]
    all_executed_queries: List[Dict[str, Any]]

    # Results tracking
    successful_queries: List[Dict[str, Any]]
    failed_queries: List[Dict[str, Any]]
    diagnostic_results: List[Dict[str, Any]]

    # Refinement tracking
    refinement_attempts: int
    refinement_history: List[Dict[str, Any]]

    # Final status
    status: Literal['success', 'partial', 'failed', 'in_progress']
    final_data: List[Dict[str, Any]]  # Cleaned citations
    completion_reason: Optional[str]

    # Effectiveness
    effectiveness_score: Optional[float]
    data_quality_score: Optional[float]
```

### 2. New State Fields

Added to `AgentState` for parallel-optimized tracking:

```python
# Complete execution traces per approach
approach_execution_traces: Dict[int, Dict[str, Any]]  # approach_index -> trace

# Current approach refinement state
needs_refinement: bool
refinement_attempts: Dict[int, int]  # approach_index -> attempt_count
refined_queries: List[Dict[str, Any]]
diagnostics: List[Dict[str, Any]]

# Sufficiency checking (after batch)
is_sufficient: bool
sufficiency_confidence: float
sufficiency_reasoning: str

# Batch execution tracking
execution_mode: str  # 'sequential' or 'batch'
batch_size: int
current_batch_number: int
batches_completed: int

# Cypher server pool for parallel
cypher_server_pool: Optional[Any]
```

## What Users Will See

### Example: Approach 1 Execution Trace

```json
{
  "approach_index": 0,
  "approach_name": "File-Based Worker Search",
  "approach_strategy": "Search for files with 'worker' in name and check for worker variables",
  "start_time": 1760714100.5,
  "end_time": 1760714125.8,
  "duration_seconds": 25.3,

  "think_step": {
    "timestamp": 1760714100.5,
    "scope": "multi_file",
    "reasoning": "Workers are likely defined across multiple files",
    "confidence": 0.9
  },

  "generate_cycles": [
    {
      "cycle_number": 1,
      "type": "original",
      "timestamp": 1760714102.3,
      "queries_generated": 3,
      "queries": [
        {
          "query": "MATCH (p:Project)-[:CONTAINS]->(f:File) WHERE toLower(f.name) CONTAINS 'worker' RETURN f.name",
          "purpose": "Find worker files",
          "reasoning": "Search by filename pattern"
        },
        // ... more queries
      ]
    },
    {
      "cycle_number": 2,
      "type": "refinement",
      "timestamp": 1760714115.1,
      "queries_generated": 2,
      "queries": [
        {
          "query": "MATCH (p:Project)-[:CONTAINS]->(f:File)-[:CONTAINS]->(c:Class) WHERE f.name CONTAINS 'Worker' RETURN c.name",
          "purpose": "Find Worker classes",
          "reasoning": "Refined to look for Class nodes directly",
          "refined_from": "Query 1 (original)"
        }
      ]
    }
  ],

  "execute_cycles": [
    {
      "cycle_number": 1,
      "type": "original",
      "timestamp": 1760714105.2,
      "queries_executed": 3,
      "results": [
        {
          "query_index": 0,
          "status": "success",
          "results_count": 6,
          "execution_time": 0.12
        },
        {
          "query_index": 1,
          "status": "empty_result",
          "results_count": 0,
          "execution_time": 0.08
        },
        {
          "query_index": 2,
          "status": "error",
          "error": "SyntaxError: Invalid property access",
          "execution_time": 0.05
        }
      ]
    },
    {
      "cycle_number": 2,
      "type": "refinement",
      "timestamp": 1760714118.7,
      "queries_executed": 2,
      "results": [
        {
          "query_index": 0,
          "status": "success",
          "results_count": 3,
          "execution_time": 0.15,
          "note": "Found WorkerA, WorkerB, WorkerC classes"
        }
      ]
    }
  ],

  "rethink_cycles": [
    {
      "cycle_number": 1,
      "timestamp": 1760714110.5,
      "analysis": {
        "successful_queries": 1,
        "failed_queries": 2,
        "decision": "needs_refinement",
        "reasoning": "Query 1 found files but no detailed data. Query 2 failed due to missing Variable nodes."
      },
      "diagnostics_run": [
        {
          "purpose": "Check if Variable nodes exist",
          "query": "MATCH (v:Variable) RETURN count(v) LIMIT 1",
          "result": {"count": 0},
          "conclusion": "Variable nodes don't exist in graph"
        }
      ],
      "refinement_plan": {
        "strategy": "Look for Class nodes instead of Variable nodes",
        "confidence": 0.8
      }
    },
    {
      "cycle_number": 2,
      "timestamp": 1760714120.2,
      "analysis": {
        "successful_queries": 2,
        "failed_queries": 0,
        "decision": "complete",
        "reasoning": "All refined queries succeeded and found 3 Worker classes"
      }
    }
  ],

  "original_queries": [
    // 3 original queries
  ],

  "refined_queries": [
    // 2 refined queries
  ],

  "all_executed_queries": [
    // All 5 queries (3 original + 2 refined)
  ],

  "successful_queries": [
    // Queries that succeeded
  ],

  "failed_queries": [
    // Queries that failed
  ],

  "diagnostic_results": [
    // Results from diagnostic queries
  ],

  "refinement_attempts": 1,

  "refinement_history": [
    {
      "attempt": 1,
      "reason": "Empty results and missing node types",
      "changes_made": "Switched from Variable to Class nodes",
      "outcome": "success"
    }
  ],

  "status": "success",

  "final_data": [
    {"class_name": "WorkerA"},
    {"class_name": "WorkerB"},
    {"class_name": "WorkerC"}
  ],

  "completion_reason": "All queries successful after refinement",

  "effectiveness_score": 0.85,
  "data_quality_score": 0.9
}
```

### Example: Complete Workflow Trace

After all approaches complete, users see:

```json
{
  "user_query": "How many workers are there in HelloWorldApp?",
  "execution_mode": "batch",
  "batch_size": 4,
  "batches_completed": 2,

  "approach_execution_traces": {
    "0": {
      // Approach 0 trace (shown above)
    },
    "1": {
      // Approach 1 trace
      "approach_name": "Variable Declaration Count",
      "status": "failed",
      "completion_reason": "No Variable nodes in graph",
      "refinement_attempts": 2,
      "duration_seconds": 18.5
    },
    "2": {
      // Approach 2 trace
      "approach_name": "Worker Type Usage",
      "status": "partial",
      "completion_reason": "Some queries succeeded, others failed",
      "refinement_attempts": 1,
      "duration_seconds": 22.1
    }
    // ... more approaches
  },

  "sufficiency_checks": [
    {
      "check_number": 1,
      "timestamp": 1760714150.0,
      "after_batch": 1,
      "approaches_completed": 4,
      "is_sufficient": false,
      "confidence": 0.6,
      "reasoning": "Found worker files but not exact count. Need more data.",
      "decision": "continue_to_next_batch"
    },
    {
      "check_number": 2,
      "timestamp": 1760714200.0,
      "after_batch": 2,
      "approaches_completed": 7,
      "is_sufficient": true,
      "confidence": 0.85,
      "reasoning": "Found 3 Worker classes (WorkerA, WorkerB, WorkerC). Can answer with confidence.",
      "decision": "synthesize_response"
    }
  ],

  "final_answer": "There are 3 workers in HelloWorldApp: WorkerA, WorkerB, and WorkerC.",

  "total_duration": 125.3,
  "total_approaches_tried": 7,
  "successful_approaches": 5,
  "failed_approaches": [1, 2],
  "total_queries_executed": 23,
  "total_refinement_cycles": 8
}
```

## Benefits for Users

### 1. **Complete Transparency**
Users see exactly what the agent tried:
- Which approaches were executed
- What queries were generated
- Why queries failed
- How queries were refined
- Final decision reasoning

### 2. **Debugging Support**
Users can identify:
- Which approach found the answer
- Why other approaches failed
- What refinements were attempted
- Where the agent got stuck

### 3. **Trust Building**
Users understand:
- The agent's reasoning process
- How thoroughly the agent searched
- Why the agent is confident (or not)
- What data the answer is based on

### 4. **Performance Insights**
Users see:
- How long each approach took
- Which approaches were most effective
- How many refinement cycles were needed
- Overall execution timeline

## Implementation Notes

### Approach Trace Initialization

When an approach starts:

```python
import time

def _initialize_approach_trace(approach_index: int, approach_data: Dict) -> Dict:
    """Initialize execution trace for an approach"""
    return {
        'approach_index': approach_index,
        'approach_name': approach_data['approach_name'],
        'approach_strategy': approach_data.get('approach', ''),
        'start_time': time.time(),
        'end_time': None,
        'duration_seconds': None,
        'think_step': None,
        'generate_cycles': [],
        'execute_cycles': [],
        'rethink_cycles': [],
        'original_queries': [],
        'refined_queries': [],
        'all_executed_queries': [],
        'successful_queries': [],
        'failed_queries': [],
        'diagnostic_results': [],
        'refinement_attempts': 0,
        'refinement_history': [],
        'status': 'in_progress',
        'final_data': [],
        'completion_reason': None,
        'effectiveness_score': None,
        'data_quality_score': None
    }
```

### Updating Trace During Execution

```python
def _update_trace_think_step(trace: Dict, think_results: Dict) -> Dict:
    """Update trace with think step results"""
    trace['think_step'] = {
        'timestamp': time.time(),
        'scope': think_results.get('scope'),
        'reasoning': think_results.get('reasoning'),
        'confidence': think_results.get('confidence')
    }
    return trace

def _update_trace_generate_cycle(trace: Dict, queries: List, cycle_type: str) -> Dict:
    """Update trace with generate cycle"""
    cycle = {
        'cycle_number': len(trace['generate_cycles']) + 1,
        'type': cycle_type,  # 'original' or 'refinement'
        'timestamp': time.time(),
        'queries_generated': len(queries),
        'queries': queries
    }
    trace['generate_cycles'].append(cycle)
    return trace

# Similar helpers for execute, rethink, etc.
```

### Completing an Approach

```python
def _complete_approach_trace(trace: Dict, status: str, reason: str, final_data: List) -> Dict:
    """Mark approach trace as complete"""
    trace['end_time'] = time.time()
    trace['duration_seconds'] = round(trace['end_time'] - trace['start_time'], 2)
    trace['status'] = status
    trace['completion_reason'] = reason
    trace['final_data'] = final_data
    return trace
```

## State Management Strategy

### Sequential Mode

Each approach completes fully before next one starts:

```python
# Approach 0: think → generate → execute → rethink → complete
# Then Approach 1: think → generate → execute → rethink → complete
# Then check_sufficiency
# If insufficient: continue to Approach 2, 3, etc.
```

### Batch Mode (Current Implementation)

All approaches in batch execute together, but **should be updated** to use new architecture:

```python
# Current (needs update):
# Batch of 4 approaches run in parallel → collect results → rethink once

# Future (with Send API):
# Fan out to 4 parallel branches:
#   Branch 0: Approach 0 complete cycle (think → generate → execute → rethink)
#   Branch 1: Approach 1 complete cycle
#   Branch 2: Approach 2 complete cycle
#   Branch 3: Approach 3 complete cycle
# Converge → check_sufficiency
```

## Usage Example

```python
# Access approach trace
approach_traces = state.get('approach_execution_traces', {})
approach_0_trace = approach_traces.get(0, {})

# Show user the journey
print(f"Approach: {approach_0_trace['approach_name']}")
print(f"Duration: {approach_0_trace['duration_seconds']}s")
print(f"Status: {approach_0_trace['status']}")
print(f"Refinements: {approach_0_trace['refinement_attempts']}")

# Show queries
for cycle in approach_0_trace['generate_cycles']:
    print(f"  Cycle {cycle['cycle_number']} ({cycle['type']})")
    for query in cycle['queries']:
        print(f"    - {query['purpose']}")

# Show results
for cycle in approach_0_trace['execute_cycles']:
    print(f"  Execution Cycle {cycle['cycle_number']}")
    for result in cycle['results']:
        print(f"    Query {result['query_index']}: {result['status']} ({result['results_count']} results)")
```

## Next Steps

See **RETHINK_SUFFICIENCY_SEPARATION_PLAN.md** for full implementation plan of:
1. `rethink_approach` node (per-approach refinement)
2. `check_sufficiency` node (after-batch evaluation)
3. Updated workflow graph
4. Batch mode refactoring

The state schema is now ready to support this architecture!

## Token Utilization Tracking

### Per-Approach Token Metrics

Each approach tracks its own token usage:

```python
{
  "approach_index": 0,
  "approach_name": "File-Based Worker Search",

  # ... other fields ...

  # Token utilization
  "llm_calls": [
    {
      "call_type": "think",
      "timestamp": 1760714100.5,
      "model_name": "gpt-4-turbo",
      "input_tokens": 1250,
      "output_tokens": 180,
      "total_tokens": 1430,
      "input_cost_usd": 0.0125,
      "output_cost_usd": 0.0054,
      "total_cost_usd": 0.0179,
      "latency_seconds": 2.3,
      "call_purpose": "Analyze approach scope and strategy"
    },
    {
      "call_type": "generate",
      "timestamp": 1760714102.3,
      "model_name": "gpt-4-turbo",
      "input_tokens": 2100,
      "output_tokens": 420,
      "total_tokens": 2520,
      "input_cost_usd": 0.0210,
      "output_cost_usd": 0.0126,
      "total_cost_usd": 0.0336,
      "latency_seconds": 3.8,
      "call_purpose": "Generate 3 queries for worker search"
    },
    {
      "call_type": "diagnostics",
      "timestamp": 1760714112.1,
      "model_name": "gpt-4-turbo",
      "input_tokens": 1800,
      "output_tokens": 250,
      "total_tokens": 2050,
      "input_cost_usd": 0.0180,
      "output_cost_usd": 0.0075,
      "total_cost_usd": 0.0255,
      "latency_seconds": 2.9,
      "call_purpose": "Generate diagnostic queries for empty results"
    },
    {
      "call_type": "refinement",
      "timestamp": 1760714115.5,
      "model_name": "gpt-4-turbo",
      "input_tokens": 2500,
      "output_tokens": 350,
      "total_tokens": 2850,
      "input_cost_usd": 0.0250,
      "output_cost_usd": 0.0105,
      "total_cost_usd": 0.0355,
      "latency_seconds": 3.2,
      "call_purpose": "Refine failed queries based on diagnostics"
    },
    {
      "call_type": "rethink",
      "timestamp": 1760714120.2,
      "model_name": "gpt-4-turbo",
      "input_tokens": 1600,
      "output_tokens": 220,
      "total_tokens": 1820,
      "input_cost_usd": 0.0160,
      "output_cost_usd": 0.0066,
      "total_cost_usd": 0.0226,
      "latency_seconds": 2.5,
      "call_purpose": "Analyze approach effectiveness and completion"
    }
  ],

  "total_input_tokens": 9250,
  "total_output_tokens": 1420,
  "total_tokens": 10670,
  "total_cost_usd": 0.1351,

  # Efficiency metrics
  "tokens_per_query_generated": 2134,  # 10670 tokens / 5 queries
  "tokens_per_successful_result": 3557,  # 10670 tokens / 3 successful results
  "cost_per_data_point": 0.0450  # $0.1351 / 3 data points
}
```

### Global Token Metrics

Track total usage across all approaches:

```json
{
  "user_query": "How many workers are there in HelloWorldApp?",

  // ... other fields ...

  // Global LLM call history (chronological)
  "llm_call_history": [
    {
      "call_type": "discovery_research",
      "timestamp": 1760714050.0,
      "model_name": "gpt-4-turbo",
      "input_tokens": 3500,
      "output_tokens": 850,
      "total_tokens": 4350,
      "total_cost_usd": 0.0605,
      "node": "discovery_research",
      "purpose": "Generate all research approaches"
    },
    // ... all LLM calls from all approaches ...
  ],

  // Global token metrics
  "total_input_tokens": 45230,
  "total_output_tokens": 8750,
  "total_tokens_used": 53980,
  "total_estimated_cost_usd": 0.7245,

  // Per-step breakdown
  "discovery_research_tokens": 4350,
  "think_tokens": 8750,  // Across all 7 approaches
  "generate_tokens": 15240,  // All query generation
  "rethink_tokens": 9100,  // All rethink analyses
  "diagnostics_tokens": 8500,  // All diagnostic queries
  "refinement_tokens": 5890,  // All query refinement
  "sufficiency_check_tokens": 1500,  // 2 sufficiency checks
  "synthesis_tokens": 650,  // Final answer synthesis

  // Per-approach breakdown
  "tokens_per_approach": {
    "0": 10670,
    "1": 6200,
    "2": 5800,
    "3": 9100,
    "4": 8500,
    "5": 4200,
    "6": 5150
  },

  "cost_per_approach": {
    "0": 0.1351,
    "1": 0.0812,
    "2": 0.0754,
    "3": 0.1183,
    "4": 0.1105,
    "5": 0.0546,
    "6": 0.0671
  },

  // Efficiency metrics
  "tokens_per_data_point": 1234.3,  // 53980 tokens / 43 data points
  "cost_per_data_point": 0.0168,  // $0.7245 / 43 data points

  // Model tracking
  "models_used": ["gpt-4-turbo", "gpt-3.5-turbo"],
  "primary_model": "gpt-4-turbo"
}
```

### Token Efficiency Dashboard

Show users cost-effectiveness of different approaches:

```
╔══════════════════════════════════════════════════════════════╗
║          TOKEN UTILIZATION SUMMARY                           ║
╠══════════════════════════════════════════════════════════════╣
║  Total Tokens: 53,980                                        ║
║  Total Cost: $0.72                                           ║
║  Duration: 125.3 seconds                                     ║
╠══════════════════════════════════════════════════════════════╣
║  PER-STEP BREAKDOWN:                                         ║
║    Discovery Research:  4,350 tokens ($0.06)  8%            ║
║    Think Steps:         8,750 tokens ($0.12)  16%           ║
║    Generate Queries:   15,240 tokens ($0.21)  28%           ║
║    Execute Queries:         0 tokens ($0.00)  0%            ║
║    Diagnostics:         8,500 tokens ($0.11)  16%           ║
║    Refinement:          5,890 tokens ($0.08)  11%           ║
║    Rethink Steps:       9,100 tokens ($0.12)  17%           ║
║    Sufficiency Checks:  1,500 tokens ($0.02)  3%            ║
║    Synthesis:             650 tokens ($0.01)  1%            ║
╠══════════════════════════════════════════════════════════════╣
║  TOP 3 MOST EFFICIENT APPROACHES:                            ║
║    1. Approach 5 (Worker Type Usage)                         ║
║       - 4,200 tokens, $0.05, 3 results                       ║
║       - 1,400 tokens/result, $0.018/result                   ║
║    2. Approach 6 (Constructor Search)                        ║
║       - 5,150 tokens, $0.07, 2 results                       ║
║       - 2,575 tokens/result, $0.034/result                   ║
║    3. Approach 2 (Variable Count)                            ║
║       - 5,800 tokens, $0.08, 1 result                        ║
║       - 5,800 tokens/result, $0.075/result                   ║
╠══════════════════════════════════════════════════════════════╣
║  MOST EXPENSIVE APPROACHES:                                  ║
║    1. Approach 0 (File-Based Search) - $0.14                 ║
║    2. Approach 3 (Class Hierarchy) - $0.12                   ║
║    3. Approach 4 (Relationship Traversal) - $0.11            ║
╠══════════════════════════════════════════════════════════════╣
║  OVERALL EFFICIENCY:                                         ║
║    Cost per data point: $0.017                               ║
║    Tokens per data point: 1,234                              ║
║    Successful approaches: 5/7 (71%)                          ║
╚══════════════════════════════════════════════════════════════╝
```

## Helper Functions for Token Tracking

### Recording LLM Calls

```python
def _record_llm_call(
    state: AgentState,
    call_type: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    model_pricing: Dict[str, float],
    call_purpose: Optional[str] = None,
    latency: Optional[float] = None
) -> AgentState:
    """Record an LLM call and update token metrics"""
    import time

    # Calculate costs based on model pricing
    input_cost = (input_tokens / 1_000_000) * model_pricing.get('input_per_1m', 0)
    output_cost = (output_tokens / 1_000_000) * model_pricing.get('output_per_1m', 0)
    total_cost = input_cost + output_cost

    # Create LLM call record
    llm_call = {
        'call_type': call_type,
        'timestamp': time.time(),
        'model_name': model_name,
        'input_tokens': input_tokens,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens + output_tokens,
        'input_cost_usd': input_cost,
        'output_cost_usd': output_cost,
        'total_cost_usd': total_cost,
        'latency_seconds': latency,
        'call_purpose': call_purpose
    }

    # Update global metrics
    new_total_input = state.get('total_input_tokens', 0) + input_tokens
    new_total_output = state.get('total_output_tokens', 0) + output_tokens
    new_total_cost = state.get('total_estimated_cost_usd', 0.0) + total_cost

    # Update per-step metrics
    step_token_field = f"{call_type}_tokens"
    step_tokens = state.get(step_token_field, 0) + (input_tokens + output_tokens)

    # Update current approach trace
    approach_traces = state.get('approach_execution_traces', {})
    current_approach_index = state.get('current_approach_index')

    if current_approach_index is not None and current_approach_index in approach_traces:
        trace = approach_traces[current_approach_index]
        trace['llm_calls'].append(llm_call)
        trace['total_input_tokens'] += input_tokens
        trace['total_output_tokens'] += output_tokens
        trace['total_tokens'] += (input_tokens + output_tokens)
        trace['total_cost_usd'] += total_cost

    return {
        **state,
        'llm_call_history': state.get('llm_call_history', []) + [llm_call],
        'total_input_tokens': new_total_input,
        'total_output_tokens': new_total_output,
        'total_tokens_used': new_total_input + new_total_output,
        'total_estimated_cost_usd': new_total_cost,
        step_token_field: step_tokens,
        'approach_execution_traces': approach_traces
    }
```

### Model Pricing Configuration

```python
MODEL_PRICING = {
    'gpt-4-turbo': {
        'input_per_1m': 10.00,  # $10 per 1M input tokens
        'output_per_1m': 30.00  # $30 per 1M output tokens
    },
    'gpt-3.5-turbo': {
        'input_per_1m': 0.50,
        'output_per_1m': 1.50
    },
    'claude-3.5-sonnet': {
        'input_per_1m': 3.00,
        'output_per_1m': 15.00
    },
    'claude-3-haiku': {
        'input_per_1m': 0.25,
        'output_per_1m': 1.25
    }
}
```

### Calculate Efficiency Metrics

```python
def _calculate_approach_efficiency_metrics(trace: Dict) -> Dict:
    """Calculate efficiency metrics for an approach"""
    total_tokens = trace['total_tokens']
    total_cost = trace['total_cost_usd']

    # Count queries and results
    all_queries = trace['all_executed_queries']
    successful_results = len(trace['final_data'])

    # Calculate per-query metrics
    tokens_per_query = total_tokens / len(all_queries) if all_queries else None

    # Calculate per-result metrics
    tokens_per_result = total_tokens / successful_results if successful_results > 0 else None
    cost_per_result = total_cost / successful_results if successful_results > 0 else None

    trace['tokens_per_query_generated'] = tokens_per_query
    trace['tokens_per_successful_result'] = tokens_per_result
    trace['cost_per_data_point'] = cost_per_result

    return trace
```

## Benefits of Token Tracking

### 1. **Cost Transparency**
- Users see exact costs per approach
- Can identify expensive vs. efficient approaches
- Helps justify costs for complex queries

### 2. **Optimization Insights**
- Identify which steps consume most tokens
- Find approaches that are token-efficient
- Optimize prompts based on usage patterns

### 3. **Budget Management**
- Track cumulative costs across queries
- Set cost limits per query
- Alert when approaching budget limits

### 4. **Model Selection**
- Compare costs across different models
- Identify when cheaper models could work
- Justify use of expensive models

### 5. **Performance Analysis**
- Correlate tokens with execution time
- Find bottlenecks in workflow
- Optimize parallel execution strategies

