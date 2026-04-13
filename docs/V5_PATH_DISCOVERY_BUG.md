# V5 Path Discovery Bug - Analysis

## Summary

V5 benchmark achieved 60% success (3/5 runs), but Run 1 failed despite correctly extracting Block from "Block nodes". The issue is **path discovery is missing the CONTAINS path** from Function to Statement through Block.

---

## Evidence from Run 1 SQ2

### Schema Extraction ✅ WORKING
```
Stage 1 - Explicit match: nodes=['Type', 'Statement', 'Function', 'Block']
Stage 2 - Cardinality-based rels (FINAL): rels=['REFERENCES', 'CONTAINS', 'IMPLEMENTS', 'CALLS']
✅ Discovered 20 path patterns
```

**Block WAS extracted**, plural matching fix is working!

### LLM Query Generation ✅ CORRECT
The LLM generated this query:
```cypher
MATCH (f:Function {name: 'CreateWorkers'})
      -[:CONTAINS]->(b:Block)
      -[:CONTAINS]->(s:Statement)
      -[:REFERENCES]->(t:Type)
RETURN s
```

The LLM **correctly used** `Function→Block→Statement` with CONTAINS relationships!

### Validation Feedback ❌ INCOMPLETE
But the validation feedback showed:
```
Function → Statement: (1 path(s) found)
  • Direct: -[REFERENCES]->

Statement → Type: NO PATH EXISTS (cannot be connected)
```

**Missing**: The `Function -[CONTAINS]-> Block -[CONTAINS]-> Statement` path!

---

## Root Cause

The APOC path discovery query in `_discover_path_on_demand` (lines 862-902) is **NOT finding the CONTAINS path** from Function to Statement through Block.

### Expected Paths
When querying Function → Statement with relationship filter `['REFERENCES', 'CONTAINS', 'IMPLEMENTS', 'CALLS']`, APOC should return:

1. **Direct REFERENCES**: `Function -[REFERENCES]-> Statement` (depth 1) ✅ **Found**
2. **Via Block**: `Function -[CONTAINS]-> Block -[CONTAINS]-> Statement` (depth 2) ❌ **MISSING**

### Actual Result
Only 1 path discovered (REFERENCES), not 2.

---

## Why This Causes Failure

1. LLM knows Block should be in the path (from schema extraction) ✓
2. LLM generates correct query using CONTAINS through Block ✓
3. Query fails validation because `Statement-[:REFERENCES]->Type` doesn't exist ✗
4. Validation feedback shows only REFERENCES path from Function to Statement ✗
5. LLM has no guidance about the CONTAINS path it just tried to use ✗
6. LLM retries with similar invalid patterns ✗
7. After 2 retries, agent gives up ✗

---

## Potential Root Causes

### 1. APOC relationshipFilter Bug
The relationship filter construction (lines 828-858) might not be correctly formatted:

```python
rel_filter_parts = []
for rel_type in relationship_types:
    if is_symmetric:
        rel_filter_parts.append(f"{rel_type}>")
        rel_filter_parts.append(f"<{rel_type}")
    else:
        rel_filter_parts.append(f"{rel_type}>")

rel_filter = '|'.join(rel_filter_parts)  # e.g. "CONTAINS>|REFERENCES>|<REFERENCES|..."
```

If CONTAINS is marked as hierarchical (one direction only), the filter would be `"CONTAINS>"`. But if the graph has `Block-[:CONTAINS]->Statement`, this should work. Unless...

### 2. Cache Contains Stale Data
The path cache at `/tmp/cpg_workflow_path_cache.json` might contain stale results:

```python
# Check cache first (line 774)
if source in self._path_cache and target in self._path_cache[source]:
    return cached_paths  # Returns WITHOUT re-querying APOC!
```

If Function→Statement was cached early (before Block was in the schema), only REFERENCES would be cached, and future requests return the incomplete cached result.

### 3. Graph Doesn't Actually Have the Relationship
The Neo4j CPG might not actually have `Block-[:CONTAINS]->Statement` relationships. This seems unlikely given the LLM's confidence in using this pattern, but possible.

---

## Recommended Fix

### Option 1: Add Debug Logging
Add logging to see exactly what APOC query is executed and what it returns:

```python
# In _discover_path_on_demand, line 862
logger.info(f"🔍 APOC query for {source} → {target}:")
logger.info(f"   Relationship filter: {rel_filter}")
logger.info(f"   Max depth: {max_depth}")

# After query execution, line 914
logger.info(f"   Found {len(paths)} paths:")
for path in paths:
    logger.info(f"      {path}")
```

### Option 2: Clear Path Cache
Delete `/tmp/cpg_workflow_path_cache.json` before V6 benchmark to force fresh discovery.

### Option 3: Validate Graph Structure
Run direct Cypher query to confirm the relationships exist:
```cypher
MATCH (f:Function)-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
RETURN count(*) as path_count
```

If this returns 0, the CPG doesn't have these relationships and we need to understand why.

---

## Impact Assessment

**V5 Results**: 60% success (3/5)
- Run 1: ❌ Failed (SQ2/SQ3 found 0 paths - path discovery issue)
- Run 2: ❌ Failed (queries executed but wrong patterns)
- Run 3: ✅ Success (used CALLS relationship)
- Run 4: ✅ Success (used SQ3 return statement analysis)
- Run 5: ✅ Success (used SQ2 successfully somehow)

**Hypothesis**: Runs 3-5 succeeded because they either:
1. Used different query patterns that didn't rely on the missing path
2. Had Block excluded from schema (different subquery phrasing), avoiding the path issue
3. Happened to have correct paths in cache from a previous run

**Expected with Fix**: 80-100% success rate (4-5/5 runs)

---

## Next Steps

1. ✅ Bug identified: Path discovery not finding CONTAINS path through Block
2. 🔄 Add debug logging to understand why APOC isn't finding it
3. 🔄 Test direct Cypher query to validate graph structure
4. 🔄 Clear path cache and re-run V6 benchmark
5. 📊 Compare V6 vs V5 results

---

## Files to Investigate

- `src/core/workflow/dynamic_schema_manager.py:802-927` - Path discovery implementation
- `/tmp/cpg_workflow_path_cache.json` - Cached path data (may be stale)
- `src/core/workflow/adaptive_query_agent.py:500-555` - Validation feedback generation

---

## Key Insight

**The bug is NOT in the fixes we made (plural matching/show all paths)**. Those are working correctly!

The bug is **upstream in path discovery** - APOC is not finding all valid paths between node types, which means validation feedback can't show them to the LLM even though we removed the path count limits.

**Fix priority**: HIGH - This is blocking correct query generation even when schema extraction is perfect.
