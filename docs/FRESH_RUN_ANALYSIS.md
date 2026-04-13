# Fresh Run Analysis - Non-Deterministic Decomposition Issue

## Executive Summary

**Problem**: The fresh run with cleared cache generated **different subqueries** than the optimized run, causing one subquery (SQ2) to fail completely, resulting in degraded performance and incomplete results.

---

## Comparison: Optimized vs Fresh Run

### OPTIMIZED Run (Previous - Successful)
**Query Decomposition:**
- [SQ1] Locate the **Type node** for WorkerFactory
- [SQ2] Retrieve the **Function node** CreateWorkers contained within WorkerFactory
- [SQ3] Identify **Type nodes** that are instantiated and returned by CreateWorkers

**Results:**
- ✅ All 3 subqueries succeeded
- ✅ 3/3 approaches used (100% utilization)
- ✅ Total time: 81 seconds
- ✅ Phase 0: 25.2s (decomposition: 5.6s, dependencies: 19.6s)
- ✅ Worker pool: 20.6s

---

### FRESH Run (After Cache Clear - Degraded)
**Query Decomposition:**
- [SQ1] Locate the **Function node** for CreateWorkers within the Type node WorkerFactory
- [SQ2] Retrieve all **Statement nodes** within Block nodes that **instantiate classes** using REFERENCES
- [SQ3] Retrieve all **Statement nodes** within Block nodes that **return classes** using REFERENCES

**Results:**
- ⚠️ **SQ1: SUCCESS** - 1 result, 1 query, 5,724 tokens (completed in ~14s)
- ❌ **SQ2: FAILED** - 0 results, 4 queries, 28,235 tokens (wasted ~100s trying different approaches)
- ✅ **SQ3: SUCCESS** - 1 result, 1 query, 5,866 tokens (completed in ~26s)
- ⚠️ Only 2/3 approaches used (66% utilization)
- ⚠️ Total time: **~127 seconds** (57% slower than optimized)
- Phase 0: 23.5s (decomposition: 6.5s, dependencies: 17s)
- Worker pool: **126.6s** (6x slower due to SQ2 failure)

---

## Root Cause: Non-Deterministic Decomposition

### Why Different Subqueries Were Generated

1. **GPT-4o Non-Determinism**: Despite using the same prompt, GPT-4o generated different logical decompositions on each run
2. **Fresh Cache State**: Without cached APOC and path discovery data, the schema context was slightly different during initialization
3. **No Temperature=0**: The LLM likely uses default temperature, introducing randomness

### Why SQ2 Failed

**SQ2 Goal**: "Retrieve Statement nodes that instantiate classes using REFERENCES"

**Problem**: The subquery assumed that:
- Statement nodes directly REFERENCE Type nodes for instantiation
- This relationship exists in the CPG cardinality list

**Reality**:
- The CPG may not have a direct `Statement→Type` via REFERENCES for all instantiation patterns
- SQ2 tried 4 different query formulations, all returning 0 results
- Spent 100+ seconds and 28,235 tokens failing repeatedly

**Path Discovery Issues**:
```
🔍 Cache miss: discovering paths Statement → File
⚠️ WARNING: No paths found: Statement → File

🔍 Cache miss: discovering paths Statement → Namespace
⚠️ WARNING: No paths found: Statement → Namespace
```

These warnings show the schema doesn't support some of the paths SQ2 needed.

---

## Impact Analysis

### Performance Degradation
| Metric | OPTIMIZED | FRESH | Delta |
|--------|-----------|-------|-------|
| **Total Time** | 81s | 127s | **+57% slower** |
| **Worker Pool Time** | 20.6s | 126.6s | **+515% slower** |
| **Subquery Utilization** | 100% (3/3) | 67% (2/3) | **-33%** |
| **Failed Subqueries** | 0 | 1 | **+1** |
| **Wasted Tokens** | 0 | 28,235 | **+28K** |
| **Data Points Collected** | 3 | 2 | **-33%** |

### Quality Degradation
- **Response length**: 741 chars (optimized) vs 843 chars (fresh) - different content
- **Completeness**: Fresh run missing data from SQ2 (instantiation statements)
- **Confidence**: Lower due to failed subquery

---

## Why This Is Critical

1. **Inconsistent Behavior**: Same query, same system, different results based on cache state
2. **Unreliable Decomposition**: Cannot predict which subqueries will be generated
3. **Silent Failures**: SQ2 failed gracefully but reduced answer quality
4. **Cost Explosion**: Failed subquery wasted 28K tokens trying multiple approaches
5. **Latency Spikes**: 100+ seconds wasted on a query that couldn't succeed

---

## Implications for Optimization Claims

The "65% speedup" from the optimized run may not be reproducible because:
1. **Different subqueries generated each time** (non-deterministic decomposition)
2. **Success depends on which subqueries GPT-4o generates** (luck factor)
3. **Cardinality-aware prompts don't guarantee valid paths** (still generates impossible queries)

The optimized run happened to generate **better subqueries** by chance, not by design.

---

## Recommended Fixes

### 1. Deterministic Decomposition
- Set `temperature=0` for decomposition LLM calls
- Add explicit seeding or use a more structured decomposition approach
- Consider rule-based decomposition for common query patterns

### 2. Improved Cardinality Validation
- **Pre-validate subqueries** before execution using cardinality list
- Reject subqueries that use relationships not in the validated pairs
- Add explicit check: "Does Statement→Type via REFERENCES exist in cardinality?"

### 3. Early Failure Detection
- If a subquery's required paths don't exist in discovered paths, **mark it as invalid immediately**
- Don't waste 100+ seconds trying 4 different query formulations
- Add path existence check before sending to AdaptiveQueryAgent

### 4. Fallback Strategies
- If a subquery fails after 1-2 attempts, try **reformulating it** using different node types/relationships
- Example: If "Statement→Type via REFERENCES" fails, try "Function→Type" or "Block contains Statement with type information"

### 5. Better Decomposition Prompts
Add explicit examples of **bad decompositions** to avoid:
```
BAD: "Retrieve Statement nodes that reference Type nodes"
REASON: Statement→Type via REFERENCES may not exist in cardinality

GOOD: "Retrieve Type nodes referenced by the Function or its children"
REASON: Function→Type and Type nodes are both validated in schema
```

---

## Testing Recommendations

1. **Run 10 identical queries** with cache cleared each time
2. **Measure decomposition variance**: How often do subqueries differ?
3. **Measure success rate**: How often do all subqueries succeed?
4. **Track failure patterns**: Which subquery types fail most often?
5. **Establish baseline**: What's the "real" average performance (not cherry-picked best run)?

---

## Conclusion

The **pickling fix worked perfectly** (✅ STATE.pkl generated successfully, 71KB).

However, we discovered a more fundamental issue: **non-deterministic decomposition causes unpredictable performance and quality**. The optimized run's impressive results (65% speedup, 100% utilization) appear to be partly due to **lucky subquery generation** rather than systematic improvement.

To claim reliable optimization, we need to address the non-determinism and ensure consistent subquery quality across runs.
