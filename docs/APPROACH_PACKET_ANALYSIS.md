# Approach Packet Structure Analysis

## Overview
Extracted 3 approach packets from previous workflow run for query:
> "What classes are instantiated and returned from CreateWorkers function in WorkerFactory?"

---

## SQ1: Locate Function Node
**Goal**: `"Locate the Function node for CreateWorkers within the Type node WorkerFactory."`

**Premises**:
- P1: "WorkerFactory is a Type node."
- P2: "CreateWorkers is a Function node contained within WorkerFactory."

**Dependencies**: None (runs first)

**Analysis**:
- Straightforward lookup task
- Clear containment path: Type → Function
- Should use: `MATCH (wf:Type {name: 'WorkerFactory'})-[:CONTAINS]->(fn:Function {name: 'CreateWorkers'})`

---

## SQ2: Retrieve Instantiated Classes
**Goal**: `"Retrieve all Statement nodes within the Block nodes contained in the CreateWorkers Function node that instantiate Type nodes."`

**Premises**:
- P3: "Function nodes can contain Block nodes."
- P4: "Block nodes can contain Statement nodes."
- P5: **"Statement nodes can reference Type nodes."** ⚠️ KEY!

**Dependencies**: `["SQ1"]` (needs CreateWorkers function first)

**Analysis**:
- Complex path: Function → Block → Statement → Type
- **Premise P5 mentions "reference"** - implies REFERENCES relationship
- But schema extraction might not return REFERENCES!
- This is the subquery that failed with 0 results!

---

## SQ3: Retrieve Returned Classes
**Goal**: `"Retrieve all Statement nodes within the Block nodes contained in the CreateWorkers Function node that return Type nodes."`

**Premises**: Same as SQ2 (P3, P4, P5)

**Dependencies**: `["SQ1"]`

**Analysis**:
- Similar to SQ2 but looking for return statements
- Also relies on P5 about Statement → Type relationship
- May also fail if REFERENCES not available

---

## Key Insights for Prompt Design

### 1. **Premises Are Valuable Context**
Premises provide:
- **Structural assumptions**: "Function contains Block", "Block contains Statement"
- **Relationship hints**: "Statement can reference Type"
- **Validation targets**: LLM should verify these against actual schema

**Recommendation**: Include premises in prompts but with clear instruction to validate against schema cardinality.

### 2. **Dependency Tracking**
- SQ2 and SQ3 depend on SQ1
- `input_data` is empty (should contain SQ1 results but doesn't)
- Current parallel execution ignores dependencies

**Recommendation**:
- Either: Make dependencies truly independent (don't reference SQ1 results)
- Or: Populate `input_data` before execution (sequential for dependencies)

### 3. **Logical Form Provides Context**
`"Locate WorkerFactory.CreateWorkers() → Retrieve instantiated classes → Retrieve returned classes"`

Shows the overall query flow - could be useful context for LLM.

### 4. **The REFERENCES Problem**
- P5 says "Statement nodes can reference Type nodes"
- LLM sees this premise
- LLM generates: `(s:Statement)-[:REFERENCES]->(t:Type)`
- But REFERENCES not in extracted schema!

**This explains the hallucination!**

---

## Proposed Prompt Structure

### **Think Prompt** - Add premises
```
**PREMISES TO VALIDATE** (from Phase 0 decomposition):
- P3: Function nodes can contain Block nodes.
- P4: Block nodes can contain Statement nodes.
- P5: Statement nodes can reference Type nodes.

⚠️ These are ASSUMPTIONS from query decomposition.
Your queries MUST verify these against actual schema cardinality.
```

### **Generate Prompt** - Add premises + emphasize validation
```
**PREMISES TO VALIDATE** (assumptions to verify):
{premises_list}

**CRITICAL**: These premises may use relationship names that don't exist in the schema!
- P5 says "reference" but check if REFERENCES relationship exists in schema
- If not in schema cardinality, find alternative path or declare premise invalid
```

### **Analyze Prompt** - Check premise validation
```
**PREMISES WE'RE VALIDATING**:
{premises_list}

**ANALYSIS**:
- Which premises did this query successfully validate?
- Which premises couldn't be validated (relationship/path not available)?
- If premise invalid, should we try alternative interpretation?
```

---

## Recommendations

1. **Restore premises to prompts** - they provide valuable structural context
2. **Add premise validation step** - explicitly check against schema cardinality
3. **Handle invalid premises** - if premise assumes relationship not in schema, guide LLM to find alternative
4. **Dependencies**:
   - Option A: Make truly independent (don't use SQ1 results in SQ2/SQ3)
   - Option B: Populate input_data sequentially for dependencies
5. **Logical form**: Consider adding as high-level context

---

## Example: How Premises Would Help SQ2

**Without Premises** (current centralized prompt):
```
SUBQUERY GOAL: Retrieve Statement nodes in CreateWorkers that instantiate Type nodes
SCHEMA: CONTAINS, CALLS (no REFERENCES)
```
LLM generates: `(s:Statement)-[:REFERENCES]->(t:Type)` ❌ (hallucination based on training data)

**With Premises** (improved prompt):
```
SUBQUERY GOAL: Retrieve Statement nodes in CreateWorkers that instantiate Type nodes

PREMISES TO VALIDATE:
- P5: "Statement nodes can reference Type nodes"

SCHEMA: CONTAINS, CALLS (no REFERENCES)

VALIDATION STEP:
- P5 assumes "reference" relationship
- Check schema: REFERENCES not in available relationships
- Premise P5 CANNOT be validated with current schema
- Alternative: Analyze Statement.text property for instantiation patterns
  OR declare this subquery cannot be answered structurally
```

With premises, LLM can:
1. See what assumption is being made
2. Validate against schema
3. Recognize mismatch
4. Propose alternative or admit limitation
