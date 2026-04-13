# Complete CoT Agent Flow - From Initialization to Completion

## Starting Point: User Query

```
User: "What classes does the CreateWorkers method instantiate or return?"
```

---

## Phase 0: Decomposition (research_engine.py)

### Step 1: GPT-4o breaks query into subqueries

```json
{
  "logical_form": "∃F ∃T (Function(F) ∧ Name(F, 'CreateWorkers') ∧ ...",
  "subqueries": [
    {
      "id": "SQ1",
      "text": "Locate the Function node F where F.name='CreateWorkers'"
    },
    {
      "id": "SQ2",
      "text": "Retrieve all Statement nodes within the Block nodes contained in the CreateWorkers Function node that instantiate Type nodes."
    },
    {
      "id": "SQ3",
      "text": "Retrieve all Statement nodes within the Block nodes that return Type nodes."
    }
  ],
  "premises": [
    {"id": "P1", "text": "Function F has name 'CreateWorkers'"},
    {"id": "P2", "text": "Function F contains Block nodes"},
    {"id": "P3", "text": "Block nodes contain Statement nodes"},
    ...
  ]
}
```

### Step 2: Build Approach Packets (research_engine.py:599)

```python
def _build_approach_packets(decomposition, dependency_analysis):
    packets = {}

    for sq in subqueries:
        packet = ApproachPacket(
            id="SQ2",
            text="Retrieve all Statement nodes...",  # The subquery text
            logical_form="∃F ∃T ...",
            original_premises=[P1, P2, P3],
            active_premises=[P1, P2, P3],
            depends_on_subqueries=[],
            status='pending'
        )
        packets["SQ2"] = packet

    return collection
```

**At this point:**
- ✅ We have ApproachPacket with subquery text and premises
- ❌ NO schema yet (will be extracted per subquery later)
- ❌ NO target nodes/relationships yet (will come from schema extraction)

---

## Phase 1: Parallel Execution (nodes.py:execute_batch_approaches)

### Step 1: Worker Pool Receives Packet (nodes.py:502-512)

```python
# For each packet, create minimal approach_details
approach_details = {
    'approach_name': "Subquery SQ2",
    'description': packet['text'],  # "Retrieve all Statement nodes..."
    'target_nodes': [],  # ← EMPTY! No schema extraction yet
    'strategy': 'lookup'
    # NO 'relationships' field at all
}

# Create AdaptiveQueryAgent
agent = AdaptiveQueryAgent(
    approach_index=2,
    approach_details=approach_details,  # ← Minimal, no schema
    user_query=user_query,  # Original user query
    schema=state['schema'],  # ← OLD YAML schema (not reconciled)
    project_name='HelloWorldApp',
    llm_service=llm_service,
    cypher_server=server,
    approach_packet=packet,  # ← NEW: Full packet with premises
    schema_manager=schema_manager  # ← NEW: DynamicSchemaManager
)

result = await agent.run()
```

**Key observation:**
- `approach_details` is MINIMAL (no target_nodes, no relationships)
- `schema` passed to agent is OLD YAML schema (no cardinality)
- But agent has `schema_manager` to extract fresh schema

---

## Phase 2: AdaptiveQueryAgent Initialization (adaptive_query_agent.py:150)

```python
def __init__(
    self,
    approach_index: int,
    approach_details: Dict[str, Any],  # Minimal (no schema)
    user_query: str,
    schema: Dict[str, Any],  # OLD YAML schema
    project_name: str,
    llm_service: Any,
    cypher_server: Any,
    approach_packet: Optional[Dict[str, Any]] = None,  # NEW
    schema_manager: Optional[Any] = None  # NEW
):
    # Store minimal approach_details
    self.state = AdaptiveQueryAgentState(
        approach_index=2,
        approach_details=approach_details,  # Still minimal
        user_query=packet['text'],  # "Retrieve Statement nodes..."
        schema=copy.copy(schema),  # OLD YAML schema (copy)
        project_name='HelloWorldApp'
    )

    self.approach_packet = packet  # Store packet
    self.schema_manager = schema_manager  # Store schema manager
```

**After __init__:**
- `self.state.approach_details` = Minimal (no target_nodes, no relationships)
- `self.state.schema` = OLD YAML schema (copy, will be replaced)
- Has `schema_manager` to extract fresh schema

---

## Phase 3: Agent Run - Schema Extraction (adaptive_query_agent.py:201)

```python
async def run(self) -> Dict[str, Any]:
    logger.info("🤖 AdaptiveQueryAgent starting for SQ2")

    # STEP 1: Extract schema for THIS subquery
    if self.schema_manager:
        logger.info("🔍 Getting filtered schema for subquery...")

        schema_result = await self.schema_manager.get_schema_for_subquery(
            subquery_text=self.state.user_query,  # "Retrieve Statement nodes..."
            cypher_server=self.cypher_server
        )

        # REPLACE the old schema with extracted schema
        self.state.schema = {
            'nodes': schema_result.get('node_schemas', {}),
            'node_labels': ['Function', 'Type', 'Statement'],
            'relationships': {  # ← THIS IS THE "ACTUAL SCHEMA"
                'CONTAINS': {
                    'description': 'Contains relationship',
                    'cardinality': [
                        {'from': 'Function', 'to': 'Block'},
                        {'from': 'Block', 'to': 'Statement'},
                        ...
                    ],
                    'properties': [...],
                    'count': 142
                },
                'CALLS': {
                    'cardinality': [{'from': 'Function', 'to': 'Function'}],
                    ...
                }
            },
            'paths': [...]
        }

        logger.info("✅ Tier 1: Using filtered reconciled schema: 3 node types, 2 relationships")
```

**After schema extraction:**
- `self.state.schema` = **REPLACED** with filtered reconciled schema
- Contains ONLY: CONTAINS, CALLS (no REFERENCES)
- Has cardinality data from reconciled schema
- `self.state.approach_details` = Still minimal (not updated with schema)

---

## Phase 4: Query Generation (adaptive_query_agent.py:388)

```python
async def _cot_generate_query_step(self):
    # Build schema examples (STATIC - shows all relationships)
    schema_examples = self._build_schema_path_examples()
    # Returns: Shows INHERITS_FROM, IMPLEMENTS, etc. ← PROBLEM!

    # Get prompt (prompts.py:get_cot_generate_query_prompt)
    base_prompt = get_cot_generate_query_prompt(
        user_query=self.state.user_query,  # "Retrieve Statement nodes..."
        approach_details=self.state.approach_details,  # Still minimal
        project_name=self.state.project_name,
        schema=self.state.schema,  # ← NEW EXTRACTED SCHEMA (CONTAINS, CALLS)
        schema_examples=schema_examples,  # ← STATIC (shows INHERITS_FROM, etc.)
        previous_queries=previous_context,
        last_analysis_hint=self.state.last_analysis_hint
    )
```

---

## Phase 5: Prompt Building (prompts.py:143)

### What Gets Passed to Prompt:

```python
# From approach_details (MINIMAL - not updated after schema extraction)
approach_details = {
    'approach_name': 'Subquery SQ2',
    'description': 'Retrieve all Statement nodes...',
    'target_nodes': [],  # ← EMPTY
    'relationships': []  # ← DOESN'T EXIST (returns [])
}

# From self.state.schema (EXTRACTED - fresh from DynamicSchemaManager)
schema = {
    'node_labels': ['Function', 'Type', 'Statement'],
    'relationships': {  # ← THIS HAS CARDINALITY
        'CONTAINS': {...},
        'CALLS': {...}
    }
}

# Static examples (HARDCODED)
schema_examples = """
5. **Type node relationships**:
   MATCH (child:Type)-[:INHERITS_FROM]->(parent:Type)  ← Shows INHERITS_FROM!
"""
```

### Current Prompt (lines 143-163):

```
**APPROACH**: Subquery SQ2
- Goal: Retrieve all Statement nodes...
- Target Nodes: []                        ← EMPTY (not updated)
- Relationships: []                       ← EMPTY (field doesn't exist)
- Key Attributes: []

**ACTUAL SCHEMA** (use this as source of truth):
- Node Types: Function, Type, Statement
- Relationships: {                        ← HAS CARDINALITY
    "CONTAINS": {
      "cardinality": [
        {"from": "Function", "to": "Block"},
        ...
      ]
    },
    "CALLS": {...}
  }

**SCHEMA EXAMPLES** (guidance for common patterns):
5. **Type node relationships**:
   MATCH (child:Type)-[:INHERITS_FROM]->(parent:Type)  ← SHOWS UNAVAILABLE REL!
```

---

## The Problem Identified

### Issue #1: approach_details Never Updated
```python
# nodes.py creates minimal approach_details
approach_details = {
    'target_nodes': [],  # Empty
    'relationships': []  # Doesn't exist
}

# After schema extraction, approach_details is NOT updated
# So prompt shows empty target_nodes and relationships
```

**Result:** Confusing empty fields in prompt

### Issue #2: Static Examples Show Wrong Relationships
```python
# Static examples show ALL relationships from full CPG
schema_examples = _build_schema_path_examples()
# Shows: INHERITS_FROM, IMPLEMENTS, etc.

# But extracted schema only has CONTAINS, CALLS
```

**Result:** LLM sees INHERITS_FROM in examples, thinks it's available

### Issue #3: Two Sources of Schema Info
```python
# Source 1: approach_details['relationships'] (empty)
**APPROACH**:
- Relationships: []

# Source 2: schema['relationships'] (actual extracted schema)
**ACTUAL SCHEMA**:
- Relationships: {CONTAINS, CALLS}
```

**Result:** Conflicting signals

---

## Summary

### What approach_details Contains:
```python
{
    'approach_name': 'Subquery SQ2',  # Redundant ID
    'description': 'Retrieve Statement nodes...',  # Actual subquery
    'target_nodes': [],  # EMPTY - never populated
    'relationships': []  # DOESN'T EXIST - returns []
    'strategy': 'lookup',
    'key_attributes': []
}
```

### What "Actual Schema" Is:
```python
{
    'node_labels': ['Function', 'Type', 'Statement'],  # From extraction
    'relationships': {  # From DynamicSchemaManager.get_schema_for_subquery
        'CONTAINS': {
            'cardinality': [...],  # Real cardinality from Neo4j
            'properties': [...],
            'count': 142
        },
        'CALLS': {...}
    }
}
```

### Why Two Sources:
1. **approach_details** = Created early (nodes.py), before schema extraction
2. **schema** = Extracted fresh per subquery (adaptive_query_agent.py:line 216)
3. **approach_details is never updated** after schema extraction

---

## The Fix Strategy

### 1. Remove Redundant Fields from Prompt
- Remove `approach_name` (just "Subquery SQ2")
- Remove `target_nodes` (empty, not used)
- Remove `relationships` (empty, confusing)
- Keep only `description` (the actual subquery goal)

### 2. Remove Static Examples
- Don't show hardcoded INHERITS_FROM, IMPLEMENTS
- Use simple generic example instead

### 3. Use Only Extracted Schema
- Trust `self.state.schema` (from DynamicSchemaManager)
- It has correct cardinality
- Has ONLY relationships available for this subquery

### 4. Strengthen Framing
- "USE ONLY THESE relationships"
- List available: CONTAINS, CALLS
- Don't mention unavailable ones

Does this clarify the flow and the issues?
