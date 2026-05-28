# Synthesis Prompt Issue Analysis - Negative Query Handling

**Date**: 2025-11-25
**Issue**: Synthesis doesn't distinguish between "definitively doesn't exist" vs "couldn't find"

---

## 🔍 Current Problem

### WorkerZ Test Case - Logical Dependencies

For query: "What are the exact two parameters passed to Helper.FormatMessage by WorkerZ?"

**Approach Structure** (from benchmark):
- **Approach_0**: "Find parameters from statement calling Helper.FormatMessage"
  - Goal: Extract parameter values
  - **Depends on**: WorkerZ existing and calling Helper.FormatMessage

- **Approach_1**: "Locate WorkerZ function"
  - Goal: Verify WorkerZ function exists
  - **FOUNDATIONAL CHECK** - doesn't depend on other approaches

- **Approach_2**: "Find statement in WorkerZ calling Helper.FormatMessage"
  - Goal: Locate specific call site
  - **Depends on**: WorkerZ existing

### Current Synthesis Prompt (lines 687-717 in nodes.py)

```python
if intent_type == 'lookup':
    synthesis_instructions = """
**SYNTHESIS RULES FOR LOOKUP QUERIES**:
1. **Choose ONE answer**: Pick the single most credible approach and use its answer - don't try to combine conflicting results
2. **Trust data over vagueness**: Prefer approaches that show actual data/values over those saying "not found" or giving abstract counts
3. **Be decisive - NO hedging**: Never use "difficult to determine", "conflicting findings", "somewhat ambiguous", or "it depends"
4. **Quality matters**: Higher quality scores (>0.6) indicate better answers - strongly prefer these
5. **Answer format**: State the answer directly in the first sentence, then optionally explain
6. **Track only used approaches**: Include only the ONE approach index you relied on"""
```

**Missing Guidance**:
- ❌ No instruction to identify foundational checks (existence verification)
- ❌ No instruction to understand logical dependencies
- ❌ No distinction between "doesn't exist" (confident) vs "not found" (uncertain)
- ❌ Rule #2 actually works AGAINST negative cases: "Prefer data over 'not found'"

---

## 📊 Current vs Desired Responses

### Current Behavior (Runs 2-5)

```
I searched the codebase but couldn't find any data matching your query:
'What are the exact two parameters passed to Helper.FormatMessage by WorkerZ?'.
This could mean:
1. The data doesn't exist in the project
2. The query needs to be more specific
3. The data exists but under different naming/structure
```

**Problems**:
- ⚠️ Uncertain tone: "couldn't find" (implies might still exist)
- ⚠️ Lists alternatives suggesting element might exist under different name
- ⚠️ Doesn't use logical reasoning from approach goals

### Desired Behavior

```
The class `WorkerZ` does not exist in the codebase.

The codebase contains only three worker classes:
- WorkerA
- WorkerB
- WorkerC

Since WorkerZ doesn't exist, it cannot call Helper.FormatMessage
or pass any parameters to it.
```

**Improvements**:
- ✅ Confident statement: "does not exist" (definitive)
- ✅ Uses logical reasoning: "Since WorkerZ doesn't exist, it cannot call..."
- ✅ Provides helpful alternatives (what DOES exist)
- ✅ Explains WHY query failed (foundational element missing)

---

## 🧠 Logical Dependencies Concept

### Example: WorkerZ Query

**Dependency Chain**:
```
Approach_1: "Does WorkerZ exist?"
    ↓ (if NO)
    ├→ Approach_0: "Find parameters" → MUST fail (can't get params from non-existent class)
    └→ Approach_2: "Find call site" → MUST fail (can't find call in non-existent class)
```

**Key Insight**:
- If **foundational check fails** → dependent approaches MUST fail
- Synthesis should recognize this pattern and make **confident negative statement**
- Not all "no results" are equal:
  - Foundational failure → "X doesn't exist" (confident)
  - Query failure → "couldn't find" (uncertain)

### Another Example: Method Call Query

Query: "Where is Foo.Bar() called?"

**Dependency Chain**:
```
Approach_1: "Does method Foo.Bar exist?"
    ↓ (if YES)
    └→ Approach_2: "Find all CALLS to Foo.Bar" → uncertain if empty
                                                   (method exists but maybe not called)
```

vs

```
Approach_1: "Does method Foo.Bar exist?"
    ↓ (if NO)
    └→ Approach_2: "Find all CALLS to Foo.Bar" → MUST be empty
                                                   (can't call non-existent method)
```

---

## 💡 Proposed Solution

### Enhanced Synthesis Instructions

Add new section for **Logical Dependency Analysis**:

```python
synthesis_instructions = """
**SYNTHESIS RULES FOR LOOKUP QUERIES**:
1. **Analyze logical dependencies**:
   - Identify foundational approaches (existence checks: "Does X exist?", "Locate Y")
   - If foundational approach finds "NO RESULTS" → dependent approaches MUST fail
   - Distinguish confident negatives from uncertain failures

2. **Confident negative statements**:
   - When foundational check fails → state definitively: "X does not exist in the codebase"
   - Explain logical consequence: "Since X doesn't exist, [dependent query] cannot succeed"
   - Provide helpful alternatives if available

3. **Uncertain statements** (only when appropriate):
   - Use "couldn't find" ONLY when element might exist but queries failed
   - When foundational check succeeds but dependent queries return empty → uncertain
   - Example: Method exists but no calls found → "No calls to X.Y() were found" (not "X.Y() doesn't exist")

4. **Choose ONE answer**: Pick the single most credible approach and use its answer
5. **Trust foundational checks**: If an approach explicitly checks existence and finds nothing → that's definitive
6. **Be decisive - NO hedging**: State findings with appropriate confidence level
7. **Quality matters**: Higher quality scores (>0.6) indicate better answers
8. **Answer format**: State the finding directly in the first sentence, then explain reasoning
9. **Track only used approaches**: Include only the approach index(es) you relied on
"""
```

### Enhanced Approach Summary Format

Current format (lines 734-739):
```python
approach_summaries.append(f"""
**Approach {i+1}: {ap['approach_name']}** (Quality: {ap['quality_grade']:.2f}/1.0)
Goal: {ap['approach_goal']}

Answer: {ap['answer']}{data_summary}
""")
```

Enhanced format to highlight foundational checks:
```python
# Classify approach type based on goal keywords
is_foundational = any(keyword in ap['approach_goal'].lower()
                     for keyword in ['locate', 'find', 'exist', 'verify', 'check if'])

foundational_marker = " **[FOUNDATIONAL CHECK]**" if is_foundational else ""

approach_summaries.append(f"""
**Approach {i+1}: {ap['approach_name']}{foundational_marker}** (Quality: {ap['quality_grade']:.2f}/1.0)
Goal: {ap['approach_goal']}
Answer: {ap['answer']}{data_summary}
""")
```

---

## 📝 Implementation Changes Needed

### 1. Update `synthesize_response` in `nodes.py`

**File**: `src/core/workflow/nodes.py`
**Method**: `synthesize_response` (lines 622-945)
**Location**: Lines 687-717 (synthesis_instructions)

**Changes**:
- Add logical dependency analysis to synthesis instructions
- Add foundational check marker to approach summaries
- Enhance "no data" fallback (lines 645-651) to analyze approach goals

### 2. Classify Approaches by Type

Add helper method to classify approaches:
```python
def _classify_approach_type(self, approach_goal: str) -> str:
    """
    Classify approach as foundational, dependent, or exploratory.

    Returns:
        'foundational' | 'dependent' | 'exploratory'
    """
    goal_lower = approach_goal.lower()

    # Foundational: existence checks, location queries
    if any(keyword in goal_lower for keyword in [
        'locate', 'find the', 'does', 'exist', 'verify',
        'check if', 'is there', 'get all', 'retrieve'
    ]):
        return 'foundational'

    # Dependent: queries that build on other findings
    if any(keyword in goal_lower for keyword in [
        'extract', 'parameter', 'argument', 'within',
        'from the', 'in the', 'called by'
    ]):
        return 'dependent'

    return 'exploratory'
```

### 3. Enhanced No-Data Fallback

Instead of generic message, analyze WHY approaches failed:

```python
if len(discovered_data) == 0:
    # Analyze approach goals to understand failure mode
    approach_traces = state.get('approach_execution_traces', {})

    # Check if any foundational approaches exist
    foundational_failed = []
    for idx, trace in approach_traces.items():
        goal = trace.get('approach_goal', '')
        approach_type = self._classify_approach_type(goal)

        if approach_type == 'foundational':
            foundational_failed.append({
                'goal': goal,
                'name': trace.get('approach_name', f'Approach {idx}')
            })

    if foundational_failed:
        # Confident negative: foundational check failed
        response = self._build_confident_negative_response(
            user_query,
            foundational_failed
        )
    else:
        # Uncertain: no foundational check performed
        response = f"I searched the codebase but couldn't find any data matching your query: '{user_query}'. This could mean:\n1. The data doesn't exist in the project\n2. The query needs to be more specific\n3. The data exists but under different naming/structure"

    return {
        **state,
        "response": response,
        "current_node": "synthesize_response"
    }
```

### 4. Build Confident Negative Response

New helper method:
```python
def _build_confident_negative_response(
    self,
    user_query: str,
    failed_foundational: List[Dict]
) -> str:
    """
    Build confident negative response when foundational checks fail.

    Args:
        user_query: Original user question
        failed_foundational: List of foundational approaches that found no results

    Returns:
        Confident negative response with reasoning
    """
    # Extract what was being searched for
    # Parse query for entity names (e.g., "WorkerZ", "Foo.Bar()")

    response_parts = []

    # State what doesn't exist
    for approach in failed_foundational:
        goal = approach['goal']
        # Extract entity name from goal (simple heuristic)
        # Could be enhanced with more sophisticated parsing
        response_parts.append(f"Based on analysis, the queried element was not found in the codebase.")

    response_parts.append(
        f"\n\nThis means the specific entities or relationships mentioned in your query "
        f"do not exist in the analyzed project."
    )

    return "\n".join(response_parts)
```

---

## 🎯 Expected Improvements

### Better Negative Query Responses

**Before**:
```
I searched the codebase but couldn't find any data...
```

**After**:
```
The class `WorkerZ` does not exist in the codebase. Analysis confirmed:
- Approach 1 (Locate WorkerZ function): No function named 'WorkerZ' found
- Approach 2 & 3 depend on WorkerZ existing, so they cannot succeed

The codebase contains only WorkerA, WorkerB, and WorkerC worker classes.
```

### More Accurate Distinction

| Scenario | Current | Improved |
|----------|---------|----------|
| **Element doesn't exist** | "couldn't find" (uncertain) | "does not exist" (confident) |
| **Element exists but no results** | "couldn't find" (uncertain) | "No calls to X found" (confident about data, not existence) |
| **Query might be wrong** | "couldn't find" (uncertain) | "couldn't find" (uncertain) ✓ |

---

## 📋 Testing Plan

### Test Cases

1. **WorkerZ (non-existent class)**
   - Expected: "WorkerZ does not exist"
   - Confidence: HIGH

2. **WorkerA.NonExistentMethod**
   - Expected: "Method NonExistentMethod does not exist in WorkerA"
   - Confidence: HIGH

3. **WorkerA.Process (exists but maybe not called)**
   - Expected: "No calls to WorkerA.Process were found" (uncertain if none actually exist)
   - Confidence: MEDIUM

4. **Architectural query with no specific entity**
   - Expected: Current behavior (exploratory, no foundational checks)
   - Confidence: Varies

---

## 🚀 Implementation Priority

**Priority**: HIGH

**Rationale**:
- Critical for user trust (confident negatives vs uncertain failures)
- Improves response quality for negative tests
- Leverages existing approach structure (goals already available)
- Relatively small code change with high impact

**Estimated Effort**: 2-3 hours
- Update synthesis instructions: 30 minutes
- Add approach classification helper: 30 minutes
- Enhance no-data fallback: 1 hour
- Testing and refinement: 1 hour
