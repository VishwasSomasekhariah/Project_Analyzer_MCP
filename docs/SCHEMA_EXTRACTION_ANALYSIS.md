# Schema Extraction Analysis: Why SQ2 Failed

## Your Question
> "Shouldn't relative schema extraction have taken care of it when the cypher query was generated?"

**Answer**: YES, it should have! And it **did try**, but there's a critical gap in how it works.

---

## What Actually Happened

### Step 1: Subquery Definition (from Phase 0 Decomposition)
```
[SQ2] Retrieve all Statement nodes within Block nodes that instantiate classes using REFERENCES
```

This subquery **assumes** that:
- Statement nodes can REFERENCE Type nodes directly
- The REFERENCES relationship connects Statement→Type

### Step 2: Schema Extraction (DynamicSchemaManager)
```
🎯 Extracted for subquery: nodes=['Type', 'Statement', ...], rels=['REFERENCES', 'CONTAINS', 'CALLS']
🛤️  Discovering paths between 5 node types...
   ✅ Discovered 21 path patterns
```

The schema manager:
1. ✅ Extracted "Statement" and "Type" as relevant node types
2. ✅ Extracted "REFERENCES" as a relevant relationship
3. ✅ Discovered 21 total path patterns between the 5 node types

**KEY ISSUE**: The 21 paths include INDIRECT paths like:
- Statement → Function → Type (through CONTAINS)
- Statement → Variable → Type (through REFERENCES)

But the schema manager doesn't explicitly tell the LLM:
- ❌ "Statement -[REFERENCES]-> Type does NOT exist as a direct edge"
- ❌ "You must go through Variable or other intermediate nodes"

### Step 3: LLM Query Generation
The AdaptiveQueryAgent receives:
- Node types: Statement, Type
- Relationships: REFERENCES
- 21 "paths" (but no clear indication which are DIRECT vs INDIRECT)

So the LLM agent **reasonably assumes**:
```cypher
MATCH (s:Statement)-[:REFERENCES]->(t:Type)
```

"I have Statement nodes, Type nodes, and REFERENCES relationship - so I'll connect them!"

### Step 4: Query Execution → APOC Validation
```
📊 Sufficiency: INSUFFICIENT_DATA (premises invalid)
```

APOC validation runs and discovers: **"Statement -[REFERENCES]-> Type does NOT exist in Neo4j"**

But by this point, it's too late - we've already wasted time generating and executing an invalid query.

---

## The Gap

**Path Discovery Says**: "You CAN get from Statement to Type" (through intermediate nodes)

**LLM Interprets This As**: "Statement and Type are directly connected"

**Reality**: Statement → Variable → Type (REFERENCES goes through Variable)

---

## Why This Is A Design Issue

### Current Behavior:
1. Schema extraction provides **node types** and **relationship types**
2. Path discovery provides **indirect reachability** ("can you get from A to B somehow?")
3. LLM agent **assumes direct edges** exist if both nodes and relationships are present

### What's Missing:
**Explicit Direct Edge Validation**

The schema should provide:
```json
{
  "nodes": ["Statement", "Type", "Variable"],
  "relationships": {
    "REFERENCES": {
      "direct_edges": [
        {"from": "Variable", "to": "Type"},
        {"from": "Function", "to": "Type"}
      ],
      "NOT_VALID": [
        {"from": "Statement", "to": "Type"}  // ❌ Does not exist
      ]
    }
  }
}
```

---

## Why The OPTIMIZED Run Worked

**OPTIMIZED Subqueries:**
```
[SQ1] Locate the Type node for WorkerFactory
[SQ2] Retrieve the Function node CreateWorkers
[SQ3] Identify Type nodes instantiated by CreateWorkers
```

These subqueries asked for **Type nodes**, not Statement→Type relationships.
- SQ3 could find Types through Function→Type or other valid paths
- No invalid direct edge assumptions

**FRESH Run Subqueries:**
```
[SQ2] Retrieve Statement nodes that instantiate classes using REFERENCES
```

This subquery explicitly asked for `Statement -[REFERENCES]-> ?`
- LLM assumed Statement can REFERENCE Type directly
- This path doesn't exist → query failed

---

## The Root Cause Is Two-Fold

###1. **Non-Deterministic Decomposition** (Primary Issue)
GPT-4o generates different subqueries each time:
- Sometimes it asks for Type nodes (works!)
- Sometimes it asks for Statement→Type (fails!)

### 2. **Incomplete Schema Information** (Secondary Issue)
Even when given the "right" schema, the LLM agent can't distinguish:
- DIRECT edges (Variable→Type via REFERENCES exists)
- INDIRECT paths (Statement can reach Type through Variable)

The schema extraction provides **indirect reachability** but the LLM needs **direct edge validation**.

---

## Why "why were the schema invalidated?" (Your Second Question)

The schemas weren't "invalidated" in the sense of being marked wrong. What happened was:

1. We **cleared the cache** (APOC cache, path discovery cache)
2. The workflow rebuilt schemas **from scratch**
3. This fresh rebuild + non-deterministic decomposition → different subqueries
4. Different subqueries → one happened to ask for an invalid path

The cache clearing revealed the **non-determinism problem** because:
- First run: Lucky subqueries that matched valid paths
- Second run: Unlucky subqueries that requested invalid paths

---

## Recommended Fixes

### Fix 1: Deterministic Decomposition
```python
# In research_engine.py decomposition
result = await self.llm_service.generate_response(
    prompt,
    json_mode=True,
    model=LLMModel.GPT4O,
    max_tokens=10000,
    temperature=0  # ← ADD THIS
)
```

### Fix 2: Explicit Direct Edge Validation
```python
# In DynamicSchemaManager.get_filtered_schema()
def _validate_direct_edges(self, extracted_rels, cardinality_list):
    """
    For each relationship, specify which direct edges exist.
    """
    direct_edges = {}
    for rel_name in extracted_rels:
        direct_edges[rel_name] = [
            pair for pair in cardinality_list
            if pair['relationship'] == rel_name
        ]
    return direct_edges
```

### Fix 3: Pre-Validate Subqueries
```python
# After decomposition, before building approach packets
def _validate_subquery_paths(self, subquery, schema):
    """
    Check if the subquery's required paths exist as DIRECT edges.
    """
    # Parse subquery to extract assumed relationships
    # Check against direct_edges in schema
    # Reject or reformulate if path doesn't exist
```

---

## Conclusion

You were RIGHT to question this! The schema extraction **should** have prevented the invalid query, but:

1. It provides INDIRECT reachability, not DIRECT edge validation
2. The LLM agent can't distinguish between the two
3. Combined with non-deterministic decomposition, this causes unpredictable failures

The fix requires **both**:
- Making decomposition deterministic (temperature=0)
- Providing explicit direct edge information (not just indirect paths)
