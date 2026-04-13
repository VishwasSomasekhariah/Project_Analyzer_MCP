# Synthesis Logical Form Integration - V12 Enhancement

**Date**: 2025-11-25
**Issue**: Synthesis doesn't use logical_form and dependencies for negative query reasoning
**Root Cause**: Data exists in state but isn't passed to synthesis prompt

---

## 🔍 Problem Summary

### Current Behavior (WorkerZ Query)

**Query**: "What are the exact two parameters passed to Helper.FormatMessage by WorkerZ?"

**Decomposition Creates**:
- **Logical Form**: `"Locate WorkerZ → Find Helper.FormatMessage call → Retrieve parameters"`
- **Dependencies**:
  - SQ1: Locate WorkerZ (foundational, no dependencies)
  - SQ2: Find call (depends on SQ1)
  - SQ3: Retrieve parameters (depends on SQ2)

**Current Synthesis**: Doesn't see logical_form or dependencies
**Result**: Generic "couldn't find" message (uncertain)

**Should Be**: "WorkerZ does not exist" (confident, based on logical reasoning)

---

## 📊 Data Flow Analysis

### Phase 0: Decomposition (WORKS)

```python
# src/core/workflow/nodes.py:418-420
return {
    **state,
    "query_decomposition": decomposition,      # ✅ Contains logical_form, premises, subqueries
    "dependency_analysis": dependency_analysis, # ✅ Contains dependencies
    "approach_packets": packet_collection,     # ✅ Contains depends_on_subqueries
}
```

**What's Created**:
```python
query_decomposition = {
    'intent': 'lookup',
    'logical_form': 'Locate WorkerZ → Find Helper.FormatMessage call → Retrieve parameters',
    'premises': [
        "The CPG contains Function nodes with a 'name' attribute",
        "Function nodes can have CALLS relationships to other Function nodes"
    ],
    'subqueries': [
        "Locate the Function node where name is 'WorkerZ'",
        "Find the Statement node within WorkerZ that calls Helper.FormatMessage",
        "Retrieve the parameters from the Statement"
    ]
}

dependency_analysis = {
    'subqueries': [
        {
            'id': 'SQ1',
            'text': "Locate the Function node where name is 'WorkerZ'",
            'depends_on_premises': ['P1'],
            'depends_on_subqueries': []  # Foundational
        },
        {
            'id': 'SQ2',
            'text': "Find the Statement...",
            'depends_on_premises': ['P1', 'P2'],
            'depends_on_subqueries': ['SQ1']  # Depends on WorkerZ existing
        },
        {
            'id': 'SQ3',
            'text': "Retrieve the parameters...",
            'depends_on_premises': ['P2'],
            'depends_on_subqueries': ['SQ2']  # Depends on call existing
        }
    ]
}
```

### Phase 1: Execution (WORKS)

All 3 subqueries execute in parallel and find NO results (WorkerZ doesn't exist).

### Phase 2: Synthesis (BROKEN)

```python
# src/core/workflow/nodes.py:639-681
discovered_data = state.get('discovered_data', [])
approach_traces = state.get('approach_execution_traces', {})

# ❌ MISSING: query_decomposition not accessed
# ❌ MISSING: dependency_analysis not accessed
# ❌ MISSING: approach_packets not accessed

# Result: No logical reasoning possible
```

---

## 💡 The Fix

### Change 1: Extract Decomposition Data in Synthesis

**File**: `src/core/workflow/nodes.py`
**Method**: `synthesize_response` (line 623)
**Location**: After line 642

```python
# Current (line 639-642)
discovered_data = state.get('discovered_data', [])
user_query = state.get('user_query', '')
approach_traces = state.get('approach_execution_traces', {})
approach_raw_results = state.get('approach_raw_results', {})

# ADD AFTER line 642:
query_decomposition = state.get('query_decomposition', {})
approach_packets = state.get('approach_packets', {})
logical_form = query_decomposition.get('logical_form', '')
premises = query_decomposition.get('premises', [])
```

### Change 2: Add Dependency Info to Approach Summaries

**Location**: Lines 662-681 (building approach_answers)

```python
# Current (line 673-681)
approach_answers.append({
    'approach_index': idx,
    'approach_name': trace.get('approach_name', f'Approach {idx}'),
    'approach_goal': trace.get('approach_goal', ''),
    'answer': approach_answer,
    'quality_grade': quality_grade,
    'data_count': len(approach_data),
    'discovered_data': approach_data
})

# ENHANCED:
# Get dependencies from approach_packets
packet_id = f"SQ{idx + 1}"
packet = approach_packets.get('packets', {}).get(packet_id, {})
depends_on = packet.get('depends_on_subqueries', [])

approach_answers.append({
    'approach_index': idx,
    'approach_name': trace.get('approach_name', f'Approach {idx}'),
    'approach_goal': trace.get('approach_goal', ''),
    'answer': approach_answer,
    'quality_grade': quality_grade,
    'data_count': len(approach_data),
    'discovered_data': approach_data,
    'depends_on_subqueries': depends_on  # ✅ NEW: Add dependencies
})
```

### Change 3: Include Logical Form in Synthesis Prompt

**Location**: Lines 741-754 (prompt building)

```python
# Current prompt
prompt = f"""
You are answering a code analysis query by synthesizing findings from multiple analysis approaches.

**USER QUERY**: {user_query}
**QUERY TYPE**: {intent_type}

**APPROACH ANSWERS** ({len(approach_answers)} approaches, sorted by quality):

{chr(10).join(approach_summaries)}

**YOUR TASK**: {task_description}

{synthesis_instructions}
"""

# ENHANCED prompt
# Build logical form visualization
logical_form_section = ""
if logical_form:
    logical_form_section = f"""
**LOGICAL QUERY STRUCTURE**:
{logical_form}

This shows the logical dependency flow. Arrows (→) indicate that later steps require earlier steps to succeed.
"""

# Build dependencies section
dependencies_section = ""
if any(ap.get('depends_on_subqueries') for ap in approach_answers):
    deps_lines = []
    for ap in approach_answers:
        deps = ap.get('depends_on_subqueries', [])
        if deps:
            deps_str = ", ".join(deps)
            deps_lines.append(f"  - {ap['approach_name']} depends on: {deps_str}")
        else:
            deps_lines.append(f"  - {ap['approach_name']} (foundational, no dependencies)")

    dependencies_section = f"""
**APPROACH DEPENDENCIES**:
{chr(10).join(deps_lines)}
"""

prompt = f"""
You are answering a code analysis query by synthesizing findings from multiple analysis approaches.

**USER QUERY**: {user_query}
**QUERY TYPE**: {intent_type}

{logical_form_section}
{dependencies_section}

**APPROACH ANSWERS** ({len(approach_answers)} approaches, sorted by quality):

{chr(10).join(approach_summaries)}

**YOUR TASK**: {task_description}

{synthesis_instructions}
"""
```

### Change 4: Update Synthesis Instructions for Logical Reasoning

**Location**: Lines 690-697 (lookup query instructions)

```python
# Current instructions
synthesis_instructions = """
**SYNTHESIS RULES FOR LOOKUP QUERIES**:
1. **Choose ONE answer**: Pick the single most credible approach and use its answer - don't try to combine conflicting results
2. **Trust data over vagueness**: Prefer approaches that show actual data/values over those saying "not found" or giving abstract counts
3. **Be decisive - NO hedging**: Never use "difficult to determine", "conflicting findings", "somewhat ambiguous", or "it depends"
4. **Quality matters**: Higher quality scores (>0.6) indicate better answers - strongly prefer these
5. **Answer format**: State the answer directly in the first sentence, then optionally explain
6. **Track only used approaches**: Include only the ONE approach index you relied on"""

# ENHANCED instructions
synthesis_instructions = """
**SYNTHESIS RULES FOR LOOKUP QUERIES**:

1. **Use logical reasoning with dependencies**:
   - Check if any approach is FOUNDATIONAL (no dependencies)
   - If a foundational approach finds NO RESULTS → dependent approaches MUST fail
   - Example: "Locate X" (foundational) returns no results → "Find Y in X" (dependent) cannot succeed
   - Make CONFIDENT negative statements when foundational checks definitively fail

2. **Distinguish confident vs uncertain negatives**:
   - **Confident**: "X does not exist" (when foundational check found nothing)
   - **Uncertain**: "Could not find X" (when queries might have failed for other reasons)
   - Use the logical form arrows (→) to understand dependencies

3. **Logical consequence reasoning**:
   - If Step 1 fails → Steps depending on Step 1 logically cannot succeed
   - State this explicitly: "Since X was not found, Y (which depends on X) cannot be retrieved"

4. **Choose ONE answer** (unless foundational failure makes reasoning necessary):
   - Pick the single most credible approach for positive findings
   - For negative findings, explain logical chain if dependencies exist

5. **Be decisive**: State findings with appropriate confidence level
   - Foundational failure → HIGH confidence ("does not exist")
   - Query failure → MEDIUM confidence ("could not find")

6. **Answer format**: State the finding directly, then explain logical reasoning if applicable

7. **Track approaches used**: Include approach indices that contributed to your conclusion
"""
```

### Change 5: Enhanced No-Data Fallback (for len(discovered_data) == 0)

**Location**: Lines 644-651

```python
# Current fallback
if len(discovered_data) == 0:
    logger.warning("⚠️ No data discovered, providing informative response")
    return {
        **state,
        "response": f"I searched the codebase but couldn't find any data matching your query: '{user_query}'. This could mean:\n1. The data doesn't exist in the project\n2. The query needs to be more specific\n3. The data exists but under different naming/structure",
        "current_node": "synthesize_response"
    }

# ENHANCED fallback with logical reasoning
if len(discovered_data) == 0:
    logger.warning("⚠️ No data discovered, analyzing approach dependencies for confident negative...")

    # Get decomposition data
    query_decomposition = state.get('query_decomposition', {})
    approach_packets = state.get('approach_packets', {})
    approach_traces = state.get('approach_execution_traces', {})
    logical_form = query_decomposition.get('logical_form', '')

    # Check if we have foundational approaches that failed
    foundational_failures = []
    packets_dict = approach_packets.get('packets', {})

    for packet_id, packet in packets_dict.items():
        depends_on = packet.get('depends_on_subqueries', [])
        if not depends_on:  # Foundational (no dependencies)
            # Check if this approach found no data
            packet_idx = int(packet_id.replace('SQ', '')) - 1
            if packet_idx in approach_traces:
                trace = approach_traces[packet_idx]
                data_count = trace.get('data_points_used', [])
                if not data_count:
                    foundational_failures.append({
                        'id': packet_id,
                        'goal': packet.get('text', ''),
                        'name': trace.get('approach_name', packet_id)
                    })

    if foundational_failures:
        # Confident negative: foundational check failed
        failure_list = "\n".join([
            f"- {f['name']}: {f['goal']} → No results found"
            for f in foundational_failures
        ])

        logical_explanation = ""
        if logical_form and '→' in logical_form:
            logical_explanation = f"\n\n**Logical Chain**: {logical_form}\n\nSince the foundational step(s) found no results, subsequent dependent steps cannot succeed."

        response = f"""Based on systematic analysis, the queried element(s) were not found in the codebase.

**Foundational Checks That Failed**:
{failure_list}
{logical_explanation}

This indicates that the specific entities or relationships mentioned in your query do not exist in the analyzed project."""

        logger.info(f"✅ Confident negative response generated based on {len(foundational_failures)} foundational failure(s)")
    else:
        # Uncertain: no foundational checks, or they succeeded but dependents failed
        response = f"I searched the codebase but couldn't find any data matching your query: '{user_query}'. This could mean:\n1. The data doesn't exist in the project\n2. The query needs to be more specific\n3. The data exists but under different naming/structure"

    return {
        **state,
        "response": response,
        "current_node": "synthesize_response"
    }
```

---

## 🎯 Expected Results

### WorkerZ Query - Before (V11)

```
I searched the codebase but couldn't find any data matching your query:
'What are the exact two parameters passed to Helper.FormatMessage by WorkerZ?'.
This could mean:
1. The data doesn't exist in the project
2. The query needs to be more specific
3. The data exists but under different naming/structure
```

**Confidence**: Uncertain (suggests element might exist elsewhere)

### WorkerZ Query - After (V12)

```
Based on systematic analysis, the queried element(s) were not found in the codebase.

**Foundational Checks That Failed**:
- Subquery SQ1: Locate the Function node where name is 'WorkerZ' → No results found

**Logical Chain**: Locate WorkerZ → Find Helper.FormatMessage call → Retrieve parameters

Since the foundational step(s) found no results, subsequent dependent steps cannot succeed.

This indicates that the specific entities or relationships mentioned in your query
do not exist in the analyzed project.
```

**Confidence**: High (definitive statement based on logical reasoning)

---

## 📋 Implementation Checklist

- [ ] **Change 1**: Extract decomposition data in synthesis (lines 643+)
- [ ] **Change 2**: Add dependency info to approach summaries (lines 673-681)
- [ ] **Change 3**: Include logical form in synthesis prompt (lines 741-754)
- [ ] **Change 4**: Update synthesis instructions with logical reasoning rules (lines 690-697)
- [ ] **Change 5**: Enhance no-data fallback with foundational failure detection (lines 644-651)
- [ ] **Test**: Run WorkerZ negative test and verify confident negative response
- [ ] **Test**: Run positive tests to ensure no regression
- [ ] **Document**: Update V12 analysis with before/after comparison

---

## 🔬 Testing Strategy

### Test Case 1: Negative Query (WorkerZ)
- **Input**: "What are the exact two parameters passed to Helper.FormatMessage by WorkerZ?"
- **Expected**: Confident "WorkerZ does not exist" with logical explanation
- **Validation**: Response should mention foundational failure and logical chain

### Test Case 2: Positive Query (WorkerA)
- **Input**: "What are the exact two parameters passed to Helper.FormatMessage by WorkerA?"
- **Expected**: Direct answer with parameter values
- **Validation**: No change from V11 behavior (regression test)

### Test Case 3: Architectural Query
- **Input**: "Analyze the overall architecture..."
- **Expected**: Comprehensive analysis
- **Validation**: Logical form should enhance context but not dominate response

---

## 💡 Key Insights

1. **Data Already Exists**: logical_form, dependencies, and premises are already computed in Phase 0
2. **Zero Execution Cost**: No additional LLM calls or computation needed
3. **Backward Compatible**: Only enhances responses, doesn't break existing behavior
4. **High Impact**: Transforms uncertain "couldn't find" into confident "doesn't exist"

---

## 🚀 Version Naming

**V12**: Logical Form Integration for Confident Negative Responses

**Improvements over V11**:
- ✅ Uses logical_form from decomposition
- ✅ Considers approach dependencies
- ✅ Makes confident negative statements when foundational checks fail
- ✅ Explains logical reasoning in responses
- ✅ Distinguishes confident vs uncertain negatives
