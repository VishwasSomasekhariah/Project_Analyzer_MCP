# Cardinality Violation Analysis - Why Prompt Instructions Failed

## Executive Summary

**Problem:** SQ2 generated 5 invalid queries wasting **28,937 tokens** ($0.0579) by repeatedly violating cardinality constraints despite explicit prompt instructions.

**Root Cause:** Prompt-based cardinality validation is **insufficient** - the LLM ignored explicit instructions and repeatedly generated `Statement -[REFERENCES]-> Type`, which doesn't exist in the graph.

**Solution Required:** **Programmatic query validation** before execution to catch and prevent cardinality violations.

---

## Evidence: SQ2 Query Analysis

### SQ2 Goal
> "Retrieve all Statement nodes within the Block nodes contained in the CreateWorkers Function node that instantiate Type nodes."

### Results
- **Total Queries:** 5
- **Results Found:** 0
- **Tokens Wasted:** 28,937 tokens
- **Success Rate:** 0% (all queries returned empty)

### Queries Generated

#### Query #1
```cypher
MATCH (p:Project {name: 'HelloWorldApp'})
  -[:CONTAINS]->(f:File)
  -[:CONTAINS*1..2]->(t:Type)
  -[:CONTAINS]->(fn:Function {name: 'CreateWorkers'})
  -[:CONTAINS]->(b:Block)
  -[:CONTAINS]->(s:Statement)
  -[:REFERENCES]->(type:Type)  ❌ VIOLATION!
RETURN s.text, type.name LIMIT 50
```

**Violation:** `Statement -[REFERENCES]-> Type` does NOT exist in cardinality

**Valid Cardinality:**
- ✅ `Variable -[REFERENCES]-> Type`
- ✅ `Function -[REFERENCES]-> Type`
- ❌ `Statement -[REFERENCES]-> Type` (NOT IN CARDINALITY LIST)

#### Query #2
```cypher
MATCH (p:Project {name: 'HelloWorldApp'})
  -[:CONTAINS]->(f:File)
  -[:CONTAINS*1..2]->(t:Type)
  -[:CONTAINS]->(fn:Function {name: 'CreateWorkers'})
  -[:CALLS]->(callee:Function)
  -[:CONTAINS]->(b:Block)
  -[:CONTAINS]->(s:Statement)
  -[:REFERENCES]->(type:Type)  ❌ VIOLATION!
RETURN s.text, type.name LIMIT 50
```

**Same violation:** `Statement -[REFERENCES]-> Type`

#### Query #3
```cypher
MATCH ... (s:Statement)-[:REFERENCES]->(type:Type)  ❌ VIOLATION!
WHERE s.statement_type = 'instantiation'
...
```

**Same violation** + added WHERE filter (still won't work)

#### Query #4
```cypher
MATCH ... (s:Statement)-[:REFERENCES]->(type:Type)  ❌ VIOLATION!
WHERE s.statement_type = 'instantiation'
...
```

**Same violation** (trying different path but same invalid relationship)

#### Query #5
```cypher
MATCH (p:Project {name: 'HelloWorldApp'})
  -[:CONTAINS]->(f:File)
  -[:CONTAINS*1..2]->(t:Type)
  -[:CONTAINS]->(fn:Function {name: 'CreateWorkers'})
  -[:CONTAINS]->(b:Block)
  -[:CONTAINS]->(s:Statement)
WHERE s.statement_type = 'instantiation'
RETURN s.text, s.statement_type, b, fn.name LIMIT 50
```

**No REFERENCES** but query still returns 0 results (path doesn't exist)

---

## Why Prompt Instructions Failed

### What We Added to the Prompt (lines 184-190 in prompts.py)

```
**CRITICAL - VALIDATE AGAINST CARDINALITY**:
- BEFORE using any relationship, CHECK if the specific (from→to) pair exists in its 'cardinality' list
- The 'cardinality' field shows EXACTLY which node pairs can connect via each relationship
- Example: If REFERENCES has cardinality [{from: Variable, to: Type}], then ONLY Variable→Type is valid
- If you want to use Statement-[REFERENCES]->Type, you MUST verify {from: Statement, to: Type} is in REFERENCES.cardinality
- If the pair is NOT in cardinality, that direct edge DOES NOT EXIST - you must find an alternate path
- This is ground truth from Neo4j - do not assume paths exist if they're not in cardinality
```

### Why It Didn't Work

1. **Passive Instructions:** The prompt tells the LLM "you should check" but doesn't enforce it
2. **No Structural Constraint:** LLM can still generate any Cypher query syntactically
3. **Complex JSON Parsing:** The cardinality list is buried in a large JSON blob of relationships
4. **Cognitive Load:** LLM must simultaneously:
   - Understand user query
   - Parse schema JSON
   - Generate Cypher syntax
   - Remember to validate each relationship pattern
   - Cross-reference cardinality list
5. **No Feedback Loop:** Invalid queries are only caught AFTER execution by APOC validation

---

## The Real Problem: Subquery Decomposition

### The Deeper Issue

The **root problem** isn't just query generation - it's that **Phase 0 decomposition creates impossible subqueries**.

SQ2 asks for:
> "Retrieve all Statement nodes... that instantiate Type nodes"

This **implies** Statement nodes can directly connect to Type nodes, but they can't!

**The decomposition agent doesn't know the cardinality constraints** - it creates logical subqueries based on natural language understanding, not graph structure.

---

## Solution: Three-Tier Validation

### Tier 1: Decomposition-Time Validation (Preventive)
**When:** During Phase 0 subquery generation
**Action:** Validate that subquery relationships exist in schema before creating approach packets

```python
def validate_subquery_feasibility(subquery_text: str, schema: Dict) -> bool:
    """
    Check if relationships mentioned in subquery text exist in cardinality.
    Example: "Statement nodes that REFERENCE Type nodes" → check if Statement→Type in REFERENCES.cardinality
    """
    # Parse natural language for entity pairs
    # Cross-reference with cardinality
    # Return False if implied relationship doesn't exist
```

### Tier 2: Query Generation-Time Validation (Enforcement)
**When:** After Cypher query generation, before execution
**Action:** Parse query and validate all relationship patterns

```python
def validate_cypher_cardinality(cypher_query: str, schema: Dict) -> ValidationResult:
    """
    Extract relationship patterns from Cypher and validate against cardinality.

    Returns:
      - valid: True/False
      - violations: List of invalid (from, rel, to) triples
      - suggestion: Alternative valid path if available
    """
    # Parse Cypher using regex or AST parser
    # Extract all (from_label, rel_type, to_label) patterns
    # Check each against schema['relationships'][rel_type]['cardinality']
    # Return detailed violation report
```

### Tier 3: Execution-Time Validation (Detection)
**When:** After query execution (current APOC validation)
**Action:** Diagnose why query returned empty and provide hints

*(This already exists but comes too late)*

---

## Recommended Implementation Priority

### Phase 1: Query-Level Validation (Immediate Fix)
**Goal:** Stop invalid queries from wasting tokens

**Implementation:**
1. Create `CypherCardinalityValidator` class
2. Add validation step in `AdaptiveQueryAgent` after query generation
3. If invalid, either:
   - **Option A:** Reject and ask LLM to regenerate with specific fix
   - **Option B:** Auto-fix by replacing invalid path with nearest valid path

**Impact:** Prevents 100% of cardinality violations in query execution

**Effort:** ~200 lines of code, 2-3 hours

### Phase 2: Decomposition Validation (Long-term Fix)
**Goal:** Prevent impossible subqueries from being created

**Implementation:**
1. Add schema awareness to Phase 0 decomposition
2. Validate subquery feasibility before creating approach packets
3. Reject or reformulate impossible subqueries

**Impact:** Prevents root cause - no invalid subqueries generated

**Effort:** ~500 lines, 1-2 days (requires deeper integration)

---

## Cost Analysis

### Current Cost of Invalid Queries

**SQ2 Failure:**
- Queries: 5
- Tokens: 28,937
- Cost: ~$0.058
- Success: 0%

**Per-Run Impact:**
- Fresh run: 127s, 1/3 approaches failed → 33% approach failure rate
- Optimized run: 81s, 3/3 succeeded → 0% failure rate

**If 33% of approaches have invalid paths:**
- 33% token waste
- 33% time waste
- Lower quality results (missing data)

### ROI of Validation

**Programmatic validation:**
- Parsing overhead: ~10ms per query
- Prevents: 28K+ tokens per invalid approach
- Payback: After preventing just 1 invalid query

---

## Comparison: Prompt vs Programmatic Validation

| Approach | Prompt Instructions | Programmatic Validation |
|----------|-------------------|------------------------|
| **Enforcement** | None (advisory) | Strict (blocking) |
| **Accuracy** | 0% (all 5 queries violated) | 100% (catches all violations) |
| **Feedback** | After execution | Before execution |
| **Token Waste** | High (28K+) | Zero |
| **Cognitive Load** | High (LLM must remember) | Zero (automatic) |
| **Determinism** | Non-deterministic | Deterministic |
| **Debuggability** | Hard (hidden in LLM reasoning) | Easy (explicit violation report) |

---

## Conclusion

**Prompt-based validation is fundamentally insufficient** because:
1. It's advisory, not enforced
2. It relies on LLM memory and attention
3. It catches violations too late (after execution)
4. It provides no structured feedback

**We must implement programmatic query validation** to:
1. Parse generated Cypher queries
2. Extract relationship patterns
3. Cross-reference with cardinality constraints
4. Reject or auto-fix invalid patterns
5. Provide specific feedback to LLM for regeneration

This will **eliminate 100% of cardinality violations** and save ~33% of wasted tokens on invalid approaches.
