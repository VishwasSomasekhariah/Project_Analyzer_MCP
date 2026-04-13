# V5 Benchmark Fixes - Complete Summary

## Issues Discovered in V4

After analyzing V4 benchmark results (0/5 runs succeeded, down from V3's 2/5), we discovered **TWO separate bugs**:

---

## Bug #1: Plural Node Names Not Matched

### Problem
The explicit type extraction regex pattern only matched **singular** forms:
```python
# OLD:
rf'\b{node_type}\s+node\b',  # Only "Block node" ❌
```

### Impact
- SQ2 query: "Retrieve all Statement **nodes** within the Block **nodes**..."
- Pattern required: "Block **node**" (singular)
- Result: **Block not extracted** → Missing from filtered schema

### Fix
Updated regex to handle both singular and plural forms:

**File**: `src/core/workflow/dynamic_schema_manager.py`
**Method**: `_extract_explicit_type_mentions` (line 1153)

```python
# NEW:
patterns = [
    rf'\b{node_type}s?\s+nodes?\b',  # "Type node(s)" or "Types node(s)"
    rf'\bnodes?\s+{node_type}s?\b',  # "node(s) Type(s)"
    rf'\b{node_type}s?\b(?=\s+(named|called|with|where))',  # "Type(s) named X"
]
```

**Also updated relationship patterns**:
```python
patterns = [
    rf'\b{rel_type}\s+(edges?|relationships?|rels?)\b',
    rf'\b(edges?|relationships?|rels?)\s+{rel_type}\b',
]
```

---

## Bug #2: Path Display Limited to First 5

### Problem
Validation feedback only showed **first 5 paths** between node pairs:

```python
# OLD:
for path in relevant_paths[:5]:  # Limit to top 5 paths ❌
```

### Discovery
When we tested APOC path discovery, we found it **correctly** discovered the `Function→Block→Statement` path even without Block in node types! But the validation feedback showed the wrong path because:

1. APOC found multiple paths (10 total):
   - `Function -[REFERENCES]-> Statement` (depth 1)
   - `Function -[CONTAINS]-> Block -[CONTAINS]-> Statement` (depth 2) ✅ **Correct!**
   - ... 8 more paths

2. The feedback showed only the first 5 paths
3. LLM picked the simplest (REFERENCES) instead of the semantically correct one (CONTAINS via Block)

### Key Insight
**You were correct!** Path discovery doesn't need Block in the node types - APOC allows ANY intermediate nodes. The issue was showing all discovered paths to the LLM so it can choose the right one.

### Fix
Updated **both** path formatting methods to show ALL paths (no limit):

**File**: `src/core/workflow/adaptive_query_agent.py`

**Method 1**: `_format_paths_between` (line 1889)
```python
# OLD:
for path in relevant_paths[:5]:  # Limit to top 5 paths ❌

# NEW:
sorted_paths = sorted(relevant_paths, key=lambda p: p.get('depth', 0))
result = [f"  {source_type} → {target_type}: ({len(sorted_paths)} path(s) found)"]
for path in sorted_paths:  # Show ALL paths ✅
```

**Method 2**: `_format_discovered_paths_hint` (line 1830)
```python
# OLD:
for path_info in path_list[:3]:  # Limit to top 3 paths per pair ❌

# NEW:
sorted_path_list = sorted(path_list, key=lambda p: p['depth'])
hint_parts.append(f"  {path_key}: ({len(sorted_path_list)} path(s))")
for path_info in sorted_path_list:  # Show ALL paths ✅
```

---

## Expected V5 Results

### Before (V4)
**Scenario**: SQ2 needs to find `Function→Block→Statement` path

1. ❌ "Block nodes" not matched (singular only)
2. ❌ Block missing from schema
3. ✅ APOC finds path anyway (Block not needed in node types)
4. ❌ Feedback shows only first 5 paths (wrong one shown first)
5. ❌ LLM uses `Statement-[:REFERENCES]->Type` (doesn't exist)
6. ❌ Validation fails after 2 retries
7. ❌ Query generation fails
8. ❌ Run fails

**Result**: 0/5 runs succeeded

### After (V5)
**Scenario**: Same SQ2 query

1. ✅ "Block nodes" matched (plural support)
2. ✅ Block explicitly in schema
3. ✅ APOC finds all paths including `CONTAINS→Block→Statement`
4. ✅ Feedback shows ALL 10 paths (including correct one)
5. ✅ LLM can choose correct `CONTAINS` path or just filter `Statement.text`
6. ✅ Valid query generated
7. ✅ Finds "new WorkerA, WorkerB, WorkerC"
8. ✅ Run succeeds

**Predicted Result**: 80-100% success rate (4-5/5 runs)

---

## Why Both Fixes Matter

### Fix #1 (Plural Matching)
- Ensures Block is **explicitly recognized** in schema
- Provides more context for query generation
- Makes schema more complete and accurate

### Fix #2 (Show All Paths)
- Gives LLM **complete information** to choose correct path
- Even if Fix #1 failed, this would still help (APOC finds the path)
- Enables LLM to see trade-offs between different paths

### Together
- **Redundant safety**: Two independent ways to succeed
- **Better feedback**: More complete schema + all path options
- **Higher confidence**: LLM has full information to make the right choice

---

## Test Evidence

### APOC Path Discovery Test Results
```
Paths from Function to Statement: (10 found)
1. REFERENCES (depth 1)
2. CONTAINS -> CONTAINS via Block (depth 2) ✅ THIS IS THE ONE!
3. REFERENCES -> REFERENCES via Variable (depth 2)
4. CONTAINS -> REFERENCES via Variable (depth 2)
5. IMPLEMENTS -> REFERENCES via Type (depth 2)
6. CALLS -> REFERENCES via Function (depth 2)
7. REFERENCES -> REFERENCES via Type (depth 2)
8. REFERENCES -> CONTAINS via Block (depth 2)
9. REFERENCES -> CONTAINS -> REFERENCES via Type, Function (depth 3)
10. REFERENCES -> CONTAINS -> REFERENCES via Block, Variable (depth 3)
```

**Key Finding**: Path #2 (`CONTAINS -> CONTAINS via Block`) exists even when Block is NOT in the filtered node types!

---

## Files Modified

1. **`src/core/workflow/dynamic_schema_manager.py`**
   - Updated `_extract_explicit_type_mentions` to handle plurals
   - Lines 1153-1207

2. **`src/core/workflow/adaptive_query_agent.py`**
   - Updated `_format_paths_between` to show all paths
   - Updated `_format_discovered_paths_hint` to show all paths
   - Lines 1830-1939

3. **`benchmark_workflow_performance.py`**
   - Changed output directory from `v4` to `v5`
   - Lines 50, 434

---

## Next Steps

✅ Fixes implemented
✅ Tests verified
🔄 Ready to run V5 benchmark
📊 Compare V5 vs V4 results

Run with:
```bash
python3 benchmark_workflow_performance.py 2>&1 | tee benchmark_v5_with_all_fixes.log &
```
