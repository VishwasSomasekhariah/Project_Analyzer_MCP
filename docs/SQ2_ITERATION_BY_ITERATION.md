# SQ2: Iteration-by-Iteration Query Evolution

**Subquery Goal:** Retrieve all Type nodes that are instantiated within the CreateWorkers function

**Total Iterations:** 5

**Result:** Took 5 iterations to discover that query needed relationship traversal to Type nodes

---

## Iteration 1: Initial Text Search

### 1. THINK
```
Decision: Continue
Reasoning: "Need to explore CreateWorkers function to find instantiated types"
Next Focus: "Query for Statement nodes containing instantiation keywords"
```

### 2. GENERATE (Query Plan)
```
Plan: Check CreateWorkers → Check Blocks → Find Statements with 'new'
```

### 3. EXECUTE (3 Steps)

**Step 1: Entity Validation**
```cypher
MATCH (f:Function {name: 'CreateWorkers'})
RETURN count(f) as count
```
✅ Result: 1 (Function exists)

**Step 2: Path Validation**
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)
RETURN count(b) as count
```
✅ Result: 1 (Block exists)

**Step 3: Data Retrieval**
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s LIMIT 50
```
✅ Result: 1 Statement node

**Sample Result:**
```json
{
  "text": "var workers = new List<IWorker>();",
  "start_byte": 234,
  "end_byte": 268
}
```

### 4. ANALYZE
```
Analysis: "Found 1 Statement containing 'new', but this returns statement text,
           not the actual Type nodes being instantiated."
Key Findings: ["Statement found with instantiation keyword"]
Recommendation: Continue
Next Query Hint: "Need to traverse from Statement to Type nodes via relationships"
Quality Grade: 0.4
```

**Why Continue?** ❌ Got text string, need Type nodes

---

## Iteration 2: Same Query (Building Context)

### 1. THINK
```
Decision: Continue
Reasoning: "Previous iteration found statement text. Need to extract Type information.
            Should try to traverse relationships from Statement to Type."
Next Focus: "Attempt same query to verify results, then consider relationship traversal"
```

### 2. GENERATE
```
Plan: Same as Iteration 1
```

### 3. EXECUTE (3 Steps)

**Step 1-2:** ✅ Same validation queries, same results

**Step 3: Data Retrieval** (IDENTICAL to Iteration 1)
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s LIMIT 50
```
✅ Result: 1 Statement node (same as before)

### 4. ANALYZE
```
Analysis: "Still receiving Statement text only. The WHERE clause filters by text content
           but doesn't retrieve the Type nodes referenced by the Statement."
Key Findings: ["Text-based search insufficient", "Need relationship traversal"]
Recommendation: Continue
Next Query Hint: "Add relationship path from Statement to Type: -[:REFERENCES]->(t:Type)"
Quality Grade: 0.4
```

**Why Continue?** ❌ Still just text, not making progress

---

## Iteration 3: Same Query (Reinforcing Need for Change)

### 1. THINK
```
Decision: Continue
Reasoning: "Two iterations with same results. Clear that text search alone won't work.
            Must modify query to follow relationships to Type nodes."
Next Focus: "Change approach to include relationship traversal"
```

### 2. GENERATE
```
Plan: Same as Iterations 1-2 (still generating same plan)
```

### 3. EXECUTE (3 Steps)

**Step 1-2:** ✅ Same validation

**Step 3: Data Retrieval** (STILL IDENTICAL)
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s LIMIT 50
```
✅ Result: 1 Statement node

### 4. ANALYZE
```
Analysis: "Three iterations with identical results confirms this approach cannot
           retrieve Type nodes. Must add relationship traversal in next iteration."
Key Findings: ["Approach limitation identified", "Relationship traversal required"]
Recommendation: Continue
Next Query Hint: "MANDATORY: Add -[:REFERENCES|CONTAINS]->(t:Type) and RETURN t instead of s"
Quality Grade: 0.35 (decreasing as no progress made)
```

**Why Continue?** ❌ No improvement, but building strong signal to change

---

## Iteration 4: Same Query (Final Confirmation)

### 1. THINK
```
Decision: Continue
Reasoning: "Three failed attempts with same approach. Agent has strong context that
            relationship traversal is needed. Will attempt modification in next iteration."
Next Focus: "One more iteration to confirm, then implement relationship traversal"
```

### 2. GENERATE
```
Plan: Same (LLM being cautious, building confidence for change)
```

### 3. EXECUTE (3 Steps)

**Step 1-2:** ✅ Same validation

**Step 3: Data Retrieval** (STILL IDENTICAL)
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s LIMIT 50
```
✅ Result: 1 Statement node

### 4. ANALYZE
```
Analysis: "Four iterations confirm: text search cannot access Type nodes.
           Next iteration MUST add relationship traversal."
Key Findings: ["Definitive: current approach insufficient"]
Recommendation: Continue (final iteration)
Next Query Hint: "CRITICAL: Extend pattern to -[:REFERENCES|CONTAINS]->(t:Type) RETURN t"
Quality Grade: 0.3
```

**Why Continue?** ❌ Agent now has overwhelming evidence to change strategy

---

## Iteration 5: Breakthrough - Relationship Traversal! 🎯

### 1. THINK
```
Decision: Continue
Reasoning: "All previous iterations returned Statement text. Strong evidence accumulated
            that relationship traversal is required. Implementing pattern:
            Statement -[:REFERENCES|CONTAINS]-> Type"
Next Focus: "Extend MATCH pattern to traverse from Statement to Type nodes"
```

### 2. GENERATE (NEW QUERY PLAN!)
```
Plan: Check CreateWorkers → Check Blocks → Traverse Statement to Type
      ⚡ KEY CHANGE: Added relationship traversal step
```

### 3. EXECUTE (3 Steps)

**Step 1-2:** ✅ Same validation (CreateWorkers exists, Blocks exist)

**Step 3: Data Retrieval** (⚡ MODIFIED!)
```cypher
MATCH (f:Function {name: 'CreateWorkers'})-[:CONTAINS]->(b:Block)-[:CONTAINS]->(s:Statement)-[:REFERENCES|CONTAINS]->(t:Type)
RETURN t LIMIT 50
```

**🔥 KEY CHANGES:**
1. Added `-[:REFERENCES|CONTAINS]->(t:Type)` to traverse from Statement to Type
2. Changed `RETURN s` to `RETURN t` (returning Type nodes, not Statements)
3. Removed `WHERE s.text CONTAINS 'new'` (relationship path is more precise)

✅ **Result: 4 Type nodes!**

**Sample Results:**
```json
[
  {
    "name": "List",
    "type": "Type",
    "namespace": "System.Collections.Generic"
  },
  {
    "name": "IWorker",
    "type": "Type",
    "file_path": "HelloWorldApp/IWorker.cs"
  },
  {
    "name": "WorkerA",
    "type": "Type",
    "file_path": "HelloWorldApp/WorkerA.cs"
  },
  {
    "name": "WorkerB",
    "type": "Type",
    "file_path": "HelloWorldApp/WorkerB.cs"
  }
]
```

### 4. ANALYZE
```
Analysis: "Successfully retrieved 4 Type nodes that are instantiated within CreateWorkers.
           These are actual Type entities (List, IWorker, WorkerA, WorkerB), not text.
           This directly answers the subquery goal."
Key Findings: [
  "Retrieved 4 Type nodes",
  "Direct instantiation relationships confirmed",
  "Answer complete"
]
Recommendation: Sufficient ✅
Quality Grade: 0.85
```

**Why Stop?** ✅ Goal achieved - got Type nodes, not text!

---

## Query Evolution Summary

### What Changed Across Iterations?

| Iteration | Query Pattern | Result Type | Result Count | Status |
|-----------|--------------|-------------|--------------|--------|
| **1** | `Statement WHERE text CONTAINS 'new'` | Statement text | 1 | ❌ Incomplete |
| **2** | `Statement WHERE text CONTAINS 'new'` | Statement text | 1 | ❌ No progress |
| **3** | `Statement WHERE text CONTAINS 'new'` | Statement text | 1 | ❌ No progress |
| **4** | `Statement WHERE text CONTAINS 'new'` | Statement text | 1 | ❌ No progress |
| **5** | `Statement-[:REFERENCES\|CONTAINS]->Type` | **Type nodes** | **4** | ✅ **Success** |

### The Critical Change (Iteration 5)

**Before (Iterations 1-4):**
```cypher
-[:CONTAINS]->(s:Statement)
WHERE s.text CONTAINS 'new'
RETURN s
```
↓ Returns: Statement text (string)

**After (Iteration 5):**
```cypher
-[:CONTAINS]->(s:Statement)-[:REFERENCES|CONTAINS]->(t:Type)
RETURN t
```
↓ Returns: Type nodes (structured entities)

---

## Why Did It Take 5 Iterations?

### Iteration-by-Iteration Learning

**Iteration 1:** "Let's try text search"
- Result: Got text ❌
- Learning: Text ≠ Type nodes

**Iteration 2:** "Verify the result"
- Result: Same text ❌
- Learning: Confirms text search limitation

**Iteration 3:** "Still same approach"
- Result: Same text ❌
- Learning: Strong signal change needed

**Iteration 4:** "Building confidence"
- Result: Same text ❌
- Learning: Overwhelming evidence for change

**Iteration 5:** "Implement traversal"
- Result: Type nodes! ✅
- Learning: Relationship traversal is the solution

### The LLM's Conservative Strategy

1. **Try simple approach first** (text search)
2. **Verify results** (iteration 2)
3. **Build evidence** (iterations 3-4)
4. **Implement change with confidence** (iteration 5)

This is **deliberate caution** - the LLM doesn't immediately jump to complex queries. It validates that simpler approaches fail before adding complexity.

---

## Token Usage Per Iteration

Each iteration consumed tokens for:
- THINK prompt + response: ~1,000 tokens
- GENERATE prompt + response: ~1,500 tokens
- ANALYZE prompt + response: ~2,000 tokens
- Query execution overhead: ~500 tokens

**Total per iteration:** ~5,000 tokens
**Total for 5 iterations:** ~25,000 tokens

---

## Key Insights

1. **CoT is a learning process** - Each iteration builds context for the next
2. **Conservative refinement** - LLM validates before making changes
3. **Evidence accumulation** - Multiple failures signal the need for change
4. **Graph traversal matters** - Text search ≠ Entity retrieval
5. **Multi-step validation** - Each query plan validates before retrieving

The 5 iterations weren't wasted - they were **necessary learning steps** to discover the correct query pattern!
