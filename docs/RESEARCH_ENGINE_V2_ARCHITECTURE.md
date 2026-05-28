# Research Engine V2 - Architecture Document

## Overview

A redesigned Research Engine that decomposes complex user queries into independent sub-questions, discovers actual CPG patterns, and generates realistic approaches for parallel execution by mini CoT agents.

## Problem Statement

### Current Issues
1. **Inefficient**: Generates 5+ approaches for the same query, most fail
2. **Unrealistic queries**: Based on static schema, not actual graph structure
3. **No decomposition**: Treats complex queries as monolithic
4. **Missed data**: Single perspective may miss information
5. **No validation**: No cross-checking between approaches

### Solution
- Decompose queries into independent sub-questions
- Discover actual CPG patterns before query generation
- Generate multi-perspective approaches per sub-question
- Execute in parallel for efficiency
- Cross-validate results for completeness

## Architecture

### High-Level Flow

```
User Query
    |
    v
[Query Decomposition]
    |
    v
Sub-Questions (independent, parallel-ready)
    |
    v
[CPG Discovery] (for each sub-question's target entities)
    |
    v
[Multi-Perspective Approach Generation]
    |
    v
Approaches with realistic queries + CPG context
    |
    v
[Parallel Execution] (mini CoT agents)
    |
    v
[Cross-Validation & Synthesis]
    |
    v
Final Answer
```

### Components

#### 1. Query Decomposition Module
**Purpose**: Break down complex queries into atomic sub-questions

**Input**:
- User query (string)
- Project schema (for context)

**Output**:
```python
{
    "original_query": "How many method calls are in Manager.Run()?",
    "sub_questions": [
        {
            "id": "sq1",
            "question": "Does Manager.Run() function exist?",
            "target_entities": ["Function", "Class"],
            "dependencies": []
        },
        {
            "id": "sq2",
            "question": "What patterns represent method calls?",
            "target_entities": ["Function", "Statement", "Expression"],
            "dependencies": []
        },
        {
            "id": "sq3",
            "question": "Count calls in Manager.Run()",
            "target_entities": ["Function"],
            "dependencies": []  # No dependencies if CPG discovery done upfront
        }
    ]
}
```

**Key Principles**:
- Sub-questions should be atomic (answer one thing)
- Sub-questions should be independent (parallel execution)
- Identify target entities for CPG discovery
- No hardcoded assumptions about graph structure

---

#### 2. CPG Discovery Agent
**Purpose**: Discover actual graph patterns for target entities

**Input**:
- Target entities (node types, relationships)
- Project name (for scoping)
- APOC cache (for metadata queries)

**Output**:
```python
{
    "node_type": "Function",
    "exists": true,
    "sample_count": 42,
    "properties": ["name", "signature", "modifier"],
    "paths_from_project": [
        "Project -[:CONTAINS]-> File -[:CONTAINS]-> Function",
        "Project -[:CONTAINS]-> File -[:CONTAINS]-> Class -[:HAS_METHOD]-> Function"
    ],
    "outgoing_relationships": [
        {"type": "CALLS", "target": "Function", "count": 15},
        {"type": "CONTAINS", "target": "Statement", "count": 156}
    ],
    "example_queries": [
        "MATCH (p:Project {name: $project})-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function) RETURN fn LIMIT 5"
    ]
}
```

**Key Principles**:
- ALWAYS scope by project_name first
- Use LIMIT aggressively (production has millions of edges)
- Sample, don't exhaust (5-10 examples sufficient)
- Use APOC cache conversationally (incremental queries)
- Return actionable patterns, not validation messages

**Query Safety**:
```python
# BAD - scans entire graph
MATCH (n:Function) RETURN count(n)

# GOOD - scoped and limited
MATCH (p:Project {name: $project})
MATCH (p)-[*1..3]->(n:Function)
RETURN count(n) LIMIT 100
```

---

#### 3. Multi-Perspective Approach Generator
**Purpose**: Generate complementary approaches for each sub-question

**Input**:
- Sub-question
- CPG discovery results for target entities
- Project schema

**Output**:
```python
{
    "sub_question_id": "sq2",
    "approaches": [
        {
            "approach_name": "Method Calls via CALLS Relationship",
            "perspective": "relationship-based",
            "target_nodes": ["Function"],
            "relationships": ["CALLS"],
            "strategy": "MATCH (p:Project {name: $project})-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function {name: 'Run'}) MATCH (fn)-[:CALLS]->(callee) RETURN count(callee) AS call_count",
            "cpg_context": {
                "discovered_patterns": [...],
                "confidence": "high",
                "notes": "CALLS relationships exist in this codebase (15 instances found)"
            }
        },
        {
            "approach_name": "Method Calls via Statement Nodes",
            "perspective": "syntax-tree-based",
            "target_nodes": ["Function", "Statement"],
            "relationships": ["CONTAINS"],
            "strategy": "MATCH (p:Project {name: $project})-[:CONTAINS]->(f:File)-[:CONTAINS]->(fn:Function {name: 'Run'}) MATCH (fn)-[:CONTAINS]->(s:Statement) WHERE s.statement_type = 'expression_statement' RETURN count(s) AS call_count",
            "cpg_context": {
                "discovered_patterns": [...],
                "confidence": "medium",
                "notes": "Statement nodes exist (156 instances), filtering needed"
            }
        }
    ]
}
```

**Key Principles**:
- Generate 1-3 approaches per sub-question (not 5+)
- Each approach represents a different perspective
- Approaches should be complementary, not redundant
- Only generate approaches for patterns that EXIST in graph
- Include confidence based on discovery results

---

#### 4. Cross-Validation & Synthesis Module
**Purpose**: Combine results from multiple perspectives, detect inconsistencies

**Input**:
- Results from all mini CoT agents
- Original sub-questions
- Approach metadata

**Output**:
```python
{
    "sub_question": "Count calls in Manager.Run()",
    "perspectives": [
        {"approach": "via CALLS", "result": 5, "confidence": "high"},
        {"approach": "via Statements", "result": 7, "confidence": "medium"}
    ],
    "validation": {
        "agreement": false,
        "discrepancy": "Statement-based found 2 more calls",
        "investigation": "CALLS relationships may not capture all call sites",
        "recommended_result": 7,
        "confidence": "medium-high"
    }
}
```

**Key Principles**:
- Agreement across perspectives = high confidence
- Disagreement triggers investigation
- Prefer more complete results when validated
- Report confidence levels clearly

---

## Data Models

### SubQuestion
```python
from pydantic import BaseModel, Field
from typing import List, Optional

class SubQuestion(BaseModel):
    id: str
    question: str
    target_entities: List[str]
    dependencies: List[str] = []  # IDs of other sub-questions (should be empty for parallel)
    reasoning: Optional[str] = None
```

### CPGDiscoveryResult
```python
class PathPattern(BaseModel):
    pattern: str  # e.g. "Project -> File -> Function"
    relationship_types: List[str]  # ["CONTAINS", "CONTAINS"]
    example_query: str

class RelationshipPattern(BaseModel):
    relationship_type: str
    source_node: str
    target_node: str
    count: int
    example_query: str

class CPGDiscoveryResult(BaseModel):
    node_type: str
    exists: bool
    sample_count: int
    properties: List[str]
    paths_from_project: List[PathPattern]
    outgoing_relationships: List[RelationshipPattern]
    discovery_timestamp: str
```

### EnhancedApproach
```python
class EnhancedApproach(BaseModel):
    approach_name: str
    perspective: str  # "relationship-based", "syntax-tree-based", etc.
    description: str
    target_nodes: List[str]
    relationships: List[str]
    key_attributes: List[str]
    strategy: str  # Full Cypher query
    cpg_context: CPGDiscoveryResult
    confidence: str  # "high", "medium", "low"
    sub_question_id: str
```

---

## Implementation Plan

### Phase 1: CPG Discovery Agent
1. Create `cpg_discovery_agent.py`
2. Implement conversational pattern with APOC cache
3. Implement scoped, limited discovery queries
4. Return structured CPGDiscoveryResult
5. Test with production-scale graph

### Phase 2: Query Decomposition
1. Create `query_decomposition.py`
2. Implement LLM-based query breakdown
3. Identify target entities per sub-question
4. Validate independence (no circular dependencies)
5. Test with various query types

### Phase 3: Multi-Perspective Generator
1. Create `multi_perspective_generator.py`
2. Use CPG discovery results to inform approach generation
3. Generate complementary (not redundant) approaches
4. Assign confidence based on discovery
5. Test approach quality

### Phase 4: Research Engine V2
1. Update `research_engine.py` (or create `research_engine_v2.py`)
2. Orchestrate: decompose -> discover -> generate
3. Maintain backward compatibility
4. Feature flag for V1 vs V2
5. Comprehensive testing

### Phase 5: Cross-Validation
1. Create `result_validator.py`
2. Compare results across perspectives
3. Detect and investigate discrepancies
4. Synthesize final answer with confidence
5. Test validation logic

---

## Testing Strategy

### Unit Tests
- CPG Discovery Agent: Mock APOC cache, verify query scoping
- Query Decomposition: Verify sub-question independence
- Approach Generator: Verify complementary perspectives

### Integration Tests
- Full flow: Query -> Sub-questions -> Discovery -> Approaches
- Parallel execution with mock mini CoT agents
- Cross-validation with synthetic results

### Production Tests
- Test with real STATE.pkl queries
- Measure: query realism, execution time, result accuracy
- Compare V1 vs V2 performance

---

## Success Metrics

1. **Efficiency**: Fewer total approaches (15 -> 6)
2. **Realism**: Higher query success rate (40% -> 80%)
3. **Completeness**: Multiple perspectives catch more data
4. **Confidence**: Cross-validation provides reliability scores
5. **Scalability**: Works with production-scale graphs

---

## Migration Strategy

### Backward Compatibility
- Keep ResearchEngine V1 intact
- Feature flag: `USE_RESEARCH_ENGINE_V2=false`
- Gradual rollout with side-by-side testing

### Rollout Plan
1. Implement V2 alongside V1
2. Test V2 with subset of queries
3. Compare results quality
4. Gradual migration: 10% -> 50% -> 100%
5. Deprecate V1 after validation period

---

## Open Questions

1. How to handle truly sequential sub-questions (rare case)?
2. What confidence threshold for approach rejection?
3. How many perspectives per sub-question (1-3)?
4. Should CPG discovery be cached across queries?

---

## References

- Current ResearchEngine: `src/core/workflow/research_engine.py`
- APOC Cache: `src/core/apoc_procedure_cache.py`
- Mini CoT Agent: `src/core/workflow/cot_agent.py`
- Workflow State: `src/core/workflow/models.py`
