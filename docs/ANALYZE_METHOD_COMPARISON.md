# Analysis Method Comparison: Current vs Perspective-Based

## Overview
Comparison of the current `_analyze_with_adaptive_context` method (unified approach) vs the old perspective-based analysis.

---

## Method Signature & Purpose

### Current: `_analyze_with_adaptive_context`
**Location**: `adaptive_query_agent.py:642-780`

**Purpose**: Analyze results with adaptive context management
- Optimistic: try with ALL results first
- If context error → provide feedback for next iteration
- If too large → chunk and analyze incrementally

**Signature**:
```python
async def _analyze_with_adaptive_context(
    self,
    query_result: Dict[str, Any],
    execution_result: Dict[str, Any],
    results: List[Dict[str, Any]],
    error: Optional[str],
    max_retries: int = 2
) -> Dict[str, Any]
```

### Old: Perspective-Based Analysis (Deprecated)
**Location**: `adaptive_query_agent.py:1556-1680` (prompt builder only)

**Purpose**: Analyze from a SPECIFIC PERSPECTIVE
- Focus on validating premises
- Detect ambiguity requiring new perspective
- Guide what perspective to query next

**Used deprecated prompt**: `_build_perspective_analyze_prompt`

---

## Key Differences

### 1. **Prompt Structure**

#### Current (Centralized):
```
**QUERY EXECUTED**: {cypher_query}
**QUERY PURPOSE**: {query_purpose}
**COT REASONING USED**:
- Path: {trace_path}
- Filters: {filters}

**EXECUTION RESULT**:
- Success: {success}
- Result Count: {count}
- Error: {error}

**RESULTS**: {json_results}

**ANALYZE**:
If ERROR occurred: What went wrong?
If EMPTY results: Check diagnostics, are filters too strict?
If SUCCESS: What did we discover?

recommendation: "Continue" | "Sufficient" | "Alternative" | "Stop" | "Refine"
```

**NO premises shown!** ❌
**NO perspective concept** ❌
**Focus**: Generic analysis of query success/failure

#### Old (Perspective-Based):
```
**SUBQUERY TO ANSWER**: {user_query}

**PREMISES** (what we're validating):
  1. {premise1}
  2. {premise2}
  ...

**PERSPECTIVE USED IN THIS QUERY**: {perspective_used}

**QUERY EXECUTED**: {cypher_query}
**QUERY PURPOSE**: {query_purpose}

**EXECUTION RESULT**: {results}

**ANALYSIS QUESTIONS**:
1. Did this perspective work?
2. Premise Validation: Does data validate/invalidate premises?
3. Data Quality: Is it COMPLETE? AMBIGUOUS?
4. Next Perspective Needed? What will DISAMBIGUATE?

next_query_hint: Should suggest NEW PERSPECTIVE, not "try again"
```

**Premises shown!** ✅
**Perspective-driven** ✅
**Focus**: Validate premises, detect ambiguity, guide next perspective

---

### 2. **Data Flow**

#### Current:
1. Get results from query execution
2. Use **centralized prompt** from `prompts.py:get_cot_analyze_results_prompt()`
3. **No premises** passed to prompt
4. LLM analyzes generic query success/failure
5. Returns: analysis, key_findings, recommendation, next_query_hint

#### Old (Perspective-Based):
1. Get results from query execution
2. Build **perspective-specific prompt** using `_build_perspective_analyze_prompt()`
3. **Extract premises** from `self.approach_packet['active_premises']`
4. **Extract perspective** from `cot_reasoning['step1_perspective']`
5. LLM analyzes: premise validation + ambiguity + next perspective
6. Returns: same fields + **ambiguity detection**

---

### 3. **Ambiguity Handling**

#### Current:
```python
# Lines 722-733 in _analyze_with_adaptive_context
if self.approach_packet and hasattr(result, 'is_ambiguous') and result.is_ambiguous is not None:
    if self.state.is_data_ambiguous and not result.is_ambiguous:
        logger.info(f"✅ AMBIGUITY RESOLVED")

    self.state.is_data_ambiguous = result.is_ambiguous
    self.state.ambiguity_reason = result.ambiguity_reason or ''
    self.state.disambiguation_perspective = result.disambiguation_perspective or ''

    if result.is_ambiguous:
        logger.warning(f"⚠️ AMBIGUITY DETECTED: {result.ambiguity_reason}")
```

**Ambiguity detection**: ✅ Still supported in code
**BUT**: Prompt doesn't ask about ambiguity! ❌
**Result**: LLM unlikely to return `is_ambiguous=True` without being prompted

#### Old (Perspective-Based):
```
**ANALYSIS QUESTIONS**:
3. Data Quality:
   - Is the data AMBIGUOUS or UNCLEAR?
   - Example: We found functions but can't tell which are constructors → AMBIGUOUS

4. Next Perspective Needed?:
   - If data is ambiguous: What perspective will DISAMBIGUATE?
```

**Ambiguity detection**: ✅ Explicitly prompted
**Result**: LLM actively detects and reports ambiguity

---

### 4. **Premise Validation**

#### Current:
- **No premises** shown in analyze prompt
- Cannot validate premises during analysis
- Premises only validated by APOC after query FAILURE (in `_validate_premises_with_apoc`)
- **Reactive validation only**

#### Old (Perspective-Based):
- **Premises explicitly shown** in analyze prompt
- LLM asked: "Does this data validate or invalidate any premises?"
- **Proactive + Reactive validation**
- Example: If query finds data, premises are validated; if not, premises questioned

---

### 5. **Next Query Guidance**

#### Current:
```
"next_query_hint": "If continuing, what should the next query do differently?"
```
- Generic refinement suggestions
- No perspective concept
- Focus on query mechanics (filters, paths)

#### Old (Perspective-Based):
```
**IMPORTANT**:
- Your `next_query_hint` should suggest a NEW PERSPECTIVE, not just "try again"
- Be specific about WHAT angle/property/relationship to query next
- Example good hint: "Check the 'type_kind' property to disambiguate between classes and interfaces"
- Example bad hint: "Try a different query"
```
- Perspective-driven guidance
- Focus on what angle/aspect to explore next
- More strategic than tactical

---

## Current Issues

### Issue 1: Premises Not Available in Analysis ❌
**Current code** (line 670):
```python
base_prompt = get_cot_analyze_results_prompt(
    cypher_query=query_result['cypher_query'],
    query_purpose=query_result.get('query_purpose', 'Unknown'),
    cot_reasoning=query_result.get('cot_reasoning', {}),
    execution_result={...},
    diagnostic_info=None
)
```
**No premises passed!**

**Fix needed**: Add `approach_packet` parameter to `get_cot_analyze_results_prompt`, similar to what we just did for generate prompt.

### Issue 2: Ambiguity Detection Not Prompted ❌
Current analyze prompt (lines 307-322) doesn't ask about ambiguity:
```
If ERROR occurred: What went wrong?
If EMPTY results: Check diagnostics...
If SUCCESS: What did we discover?
```

**Missing**:
- "Is the data ambiguous or unclear?"
- "What perspective would disambiguate?"

**Result**: LLM won't populate `is_ambiguous`, `ambiguity_reason`, `disambiguation_perspective` fields

### Issue 3: No Perspective Concept ❌
Current prompt is query-focused, not perspective-focused:
- "What went wrong with the query?"
- "Should we refine the query?"

Old prompt was perspective-focused:
- "Did this perspective work?"
- "What OTHER perspective fills the gaps?"
- "What perspective will DISAMBIGUATE?"

---

## Recommendations

### Option 1: Keep Current (No Premises in Analysis)
**Pros**:
- Simpler, unified prompt
- Works for independent parallel execution
- Premises validated reactively by APOC when needed

**Cons**:
- ❌ Cannot validate premises proactively during analysis
- ❌ Ambiguity detection won't work (not prompted)
- ❌ Less strategic "next query" guidance

### Option 2: Add Premises to Analysis (Like We Just Did for Generate)
**Pros**:
- ✅ LLM can validate premises against actual results
- ✅ Can report "Premise P5 invalidated - no REFERENCES found"
- ✅ More context for better analysis

**Implementation**:
1. Add `approach_packet` parameter to `get_cot_analyze_results_prompt`
2. Extract and show premises in prompt
3. Ask: "Does this data validate or invalidate any premises?"
4. Update call site (line 670) to pass `approach_packet`

### Option 3: Restore Ambiguity Detection
**Pros**:
- ✅ LLM can detect ambiguous data
- ✅ Supports multi-iteration disambiguation flow

**Implementation**:
1. Add ambiguity questions to analyze prompt:
   - "Is the data AMBIGUOUS or UNCLEAR?"
   - "What would DISAMBIGUATE the data?"
2. LLM will populate `is_ambiguous`, `ambiguity_reason`, `disambiguation_perspective`
3. Code already handles these fields (lines 722-733)

---

## Summary Table

| Feature | Current | Old Perspective | Recommended |
|---------|---------|-----------------|-------------|
| **Premises shown** | ❌ No | ✅ Yes | ✅ Add back |
| **Premise validation** | ❌ Reactive only (APOC) | ✅ Proactive + Reactive | ✅ Add proactive |
| **Ambiguity detection** | ⚠️ Code exists but not prompted | ✅ Yes | ✅ Add to prompt |
| **Perspective concept** | ❌ No | ✅ Yes | ⚠️ Optional (depends on parallel vs sequential) |
| **Parallel execution** | ✅ Yes | ⚠️ Unclear | ✅ Keep |
| **Context management** | ✅ Adaptive chunking | ❌ No | ✅ Keep |

---

## Conclusion

The current `_analyze_with_adaptive_context` is **functionally sound** but **missing context**:
1. ✅ Good: Adaptive context management, parallel-friendly, unified prompts
2. ❌ Missing: Premises, ambiguity detection, premise validation
3. ⚠️ Code exists for ambiguity handling but prompt doesn't trigger it

**Quick Win**: Add premises to analyze prompt (same pattern we just used for generate prompt) and restore ambiguity questions.
