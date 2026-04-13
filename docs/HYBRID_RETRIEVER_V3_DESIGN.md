# Hybrid Retriever V3 — Intent-Driven Routing Design

## Overview

The current V2 hybrid workflow runs PageIndex on every query regardless of intent, then falls
back to both Vector and CPG together when PageIndex is insufficient. Benchmark analysis across
61 ground-truth queries shows this is wasteful and actively hurts answer quality in some cases.

V3 replaces the PageIndex-first-always strategy with **intent-driven routing**: the query intent
is classified first and used to send each query directly to the retriever most likely to succeed.

---

## Evidence From Benchmark Analysis

### Where Each Retriever Explicitly Fails

**Vector RAG fails on exact structural queries:**

| Query | Vector Score | CPG Score | Vector's Mistake |
|-------|-------------|-----------|-----------------|
| What is the first `using` statement in Manager.cs? | 1.0 | 9.9 | Inferred from usage patterns instead of reading file order |
| Is `ImplicitUsings` enabled in the project config? | 1.0 | 10.0 | Could not read `.csproj`; guessed from C# code style |
| How many classes are declared `public static`? | 1.9 | 10.0 | Found 1, missed WorkerFactory — incomplete enumeration |
| What `using` statements are in Program.cs? | 3.2 | 9.9 | Hallucinated 4 statements; only 1 exists |
| What interface does Manager implement? | 3.7 | 10.0 | Hallucinated `IWorker`; only `INotifier` is correct |

**Root cause:** Embeddings capture semantic similarity, not structural ground truth. Vector RAG
cannot reliably count, enumerate, or pin exact values — it fills gaps with semantically plausible
but factually wrong answers.

---

**CPG RAG fails on conceptual reasoning queries:**

| Query | Vector Score | CPG Score | CPG's Mistake |
|-------|-------------|-----------|--------------|
| Find all design patterns implemented | 9.1 | 3.3 | Found classes/edges but cannot identify *which pattern* they represent |
| What are the class dependencies and relationships? | 8.6 | 3.4 | Gives structural labels, not the actual "A depends on B" narrative |
| What is the core business logic and worker coordination? | 8.3 | 4.7 | Knows structure but cannot synthesise *what the code does* |

**Root cause:** The CPG encodes nodes, edges, and properties — structure only. It has no semantic
understanding of what a pattern means or how to narrate a workflow. It can traverse the graph but
cannot interpret it conceptually.

---

### RAGChecker Results (61 queries, ground-truth compared)

| Metric | Vector | CPG | Hybrid (V2) |
|--------|--------|-----|-------------|
| Retriever Claim Recall | 56.0% | **77.6%** | 73.6% |
| Retriever Context Precision | 57.8% | **71.4%** | 60.9% |
| Generator Context Utilisation | 64.8% | **87.9%** | 55.5% |
| Noise Sensitivity (relevant) | **21.9%** | 44.9% | 13.8% |

> The V2 hybrid has the **lowest generator context utilisation (55.5%)** despite having the most
> context. Combining both retrievers always adds noise — the generator uses only half of what it
> receives. CPG alone achieves 87.9% utilisation.

---

## The Fundamental Split

| Intent | Best Retriever | Reason |
|--------|---------------|--------|
| Structural, Direct Lookup, Quantitative | CPG | Ground-truth exact facts: counts, enumerations, signatures, property values |
| Architectural, Semantic | PageIndex → Vector | Navigates real file content; Vector adds conceptual synthesis |
| Relational | CPG + Vector (parallel) | CPG has the edges; Vector synthesises what they mean |
| Mixed, Unknown | PageIndex → Vector | Start broad, escalate to semantic if insufficient |

---

## New Graph: Intent-Driven Routing With Confidence Escalation

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              START                                      │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
                                  ▼
                        ┌─────────────────┐
                        │ classify_intent │
                        └────────┬────────┘
                                 │
             ┌───────────────────┼───────────────────────┐
             │                   │                       │
             │ STRUCTURAL        │ ARCHITECTURAL         │ RELATIONAL
             │ DIRECT_LOOKUP     │ SEMANTIC              │
             │ QUANTITATIVE      │ MIXED                 │
             │                   │ UNKNOWN               │
             ▼                   ▼                       ▼
    ┌─────────────────┐ ┌──────────────────────┐      fan-out
    │  cpg_retrieval  │ │ pageindex_retrieval  │         │
    └────────┬────────┘ └──────────┬───────────┘      ┌──┴─────────────────┐
             │                     │                  │                    │
             │                     │          ┌────────────────┐  ┌─────────────────┐
             │                     │          │ cpg_retrieval  │  │ vector_retrieval│
             │                     │          └───────┬────────┘  └────────┬────────┘
             │                     │                  └──────────┬─────────┘
             │                     │                             │
             │    ┌────────────────┴─────────────────┐           │ combine_results
             │    │  route_after_single              │           │
             │    │  (confidence gate)               │           │
             │    └──────────┬──────────────┬────────┘           │
             │               │              │                    │
             │          HIGH conf      LOW conf                  │
             │               │              │                    │
             │               │    ┌─────────────────┐            │
             │               │    │    escalate_    │            │
             │               │    │    retrieval    │            │
             │               │    │  (backup runs)  │            │
             │               │    └─────────┬───────┘            │
             │               │              │                    │
             └───────────────┴──────────────┘                    │
                             │                                   │
                    ┌────────┴───────────────────────────────────┘
                    │
                    │  if two results present:
                    ▼
          ┌──────────────────┐
          │  cross_validate  │  ◄── resolves conflicts between
          └────────┬─────────┘      primary and secondary results
                   │
                   ▼
          ┌───────────────────┐
          │synthesize_response│
          └────────┬──────────┘
                   │
                   ▼
          ┌──────────────────┐
          │ critic_validation│
          └────────┬─────────┘
                   │
                   ▼
                  END
```

---

## Node Descriptions

### `classify_intent`
Analyses the user query using a lightweight LLM call with chain-of-thought reasoning.
Maps the query to one of the existing `QueryIntent` values and sets `routing_strategy`
in state so all downstream nodes know how the workflow was routed.

**Output state fields:** `intent_analysis`, `routing_strategy`, `primary_retriever`

---

### `route_by_intent` *(conditional edge function)*
Reads `intent_analysis.intent` and returns the next node(s).

```
STRUCTURAL | DIRECT_LOOKUP | QUANTITATIVE  →  "cpg_retrieval"
ARCHITECTURAL | SEMANTIC | MIXED | UNKNOWN →  "pageindex_retrieval"
RELATIONAL                                 →  ["cpg_retrieval", "vector_retrieval"]
```

For `RELATIONAL`, LangGraph fans out to both nodes in parallel.

---

### `cpg_retrieval`
Executes the 4-agent CPG team (Thinker → Validator → Executor).
Sets `primary_retriever = "cpg"` in state when running as primary.

---

### `pageindex_retrieval`
Executes MCTS search over the `.pageindex/__index__.json` hierarchy.
Sets `primary_retriever = "pageindex"` in state.

---

### `vector_retrieval`
Executes the `codebase-vector-rag` CLI.
Sets `primary_retriever = "vector"` in state when running as primary,
or populates `secondary_result` when running as escalation backup.

---

### `route_after_single` *(conditional edge function)*
Applied after any **single-retriever** path (CPG-only or PageIndex-only).
Reads the result's confidence score and answer length.

```
confidence ≥ 0.6  AND  answer length ≥ 50 chars  →  "synthesize_response"
otherwise                                          →  "escalate_retrieval"
```

---

### `escalate_retrieval`
Runs the backup retriever when the primary had low confidence.
Escalation rules derived from the benchmark failure analysis:

| Primary Retriever | Escalates To | Reason |
|-------------------|-------------|--------|
| `pageindex` | Vector | Semantic synthesis covers what PageIndex missed |
| `cpg` | Vector | Vector sometimes captures structural info CPG missed |
| `vector` | CPG | Structural ground truth as backup for semantic failures |

Populates `secondary_result` in state. Does **not** overwrite the primary result.

---

### `combine_results`
Used only on the **RELATIONAL parallel path**. Merges CPG and Vector raw results,
manages context limits, and creates batches for synthesis.

---

### `cross_validate`
Runs when two retriever results are present (either from parallel RELATIONAL path
or from primary + escalation). Identifies:
- **Agreements** — facts confirmed by both retrievers (high confidence)
- **Conflicts** — contradictions between retrievers (require resolution)
- **Unique contributions** — facts only one retriever found

Produces a `CrossValidationResult` that `synthesize_response` uses to weight evidence.

---

### `synthesize_response`
Synthesises the final answer. The `SynthesisStrategy` is set automatically based on
how the workflow was routed:

| Routing Path | Strategy |
|---|---|
| CPG only, high confidence | `CPG_PRIMARY` |
| PageIndex sufficient | `PAGEINDEX_PRIMARY` |
| Vector only, high confidence | `VECTOR_PRIMARY` |
| Primary + escalation backup | `CROSS_VALIDATION` |
| CPG + Vector parallel (RELATIONAL) | `HYBRID_CONSENSUS` |
| Only secondary succeeded | `FALLBACK_VECTOR` or `FALLBACK_CPG` |
| All failed | `NO_RESULTS` |

---

### `critic_validation`
Unchanged from V2. Scores the synthesis output for hallucination, faithfulness,
and accuracy against the retrieved context.

---

## State Changes Required

Three fields added to `HybridState`:

```python
# Set by classify_intent; consumed by route_by_intent
routing_strategy: str = "unknown"
# "cpg_only" | "pageindex_primary" | "relational_parallel" | "vector_only"

# Set by the primary retriever node; used by escalate_retrieval
primary_retriever: str = ""
# "cpg" | "pageindex" | "vector"

# Set by escalate_retrieval; consumed by cross_validate + synthesize_response
secondary_result: Optional[RetrieverResult] = None

# Set by escalate_retrieval to signal cross_validate is needed
escalated: bool = False
```

The existing fields `use_fallback` and `pageindex_learnings` are kept for
backwards compatibility but are no longer the primary routing mechanism.

---

## What This Fixes

| Issue in V2 | Fix in V3 |
|-------------|-----------|
| PageIndex runs on every query regardless of intent | CPG handles structural queries directly — no PageIndex overhead |
| Fallback always fires both Vector + CPG | Escalation only fires the backup when confidence is low |
| Intent analysis result unused in routing | Intent drives every routing decision |
| Hybrid hurts generator utilisation (55.5% vs CPG's 87.9%) | Single-retriever paths give clean, high-utilisation context |
| CPG wastes time on conceptual queries it will fail | CPG only runs on STRUCTURAL / DIRECT_LOOKUP / QUANTITATIVE |
| Vector adds noise to structural queries | Vector only runs on ARCHITECTURAL / SEMANTIC or as escalation |

---

## Implementation Scope

| File | Change |
|------|--------|
| `hybrid_workflow_V2/models.py` | Add `routing_strategy`, `primary_retriever`, `secondary_result`, `escalated` to `HybridState` |
| `hybrid_workflow_V2/nodes.py` | Replace `route_after_pageindex` with `route_by_intent` + `route_after_single`; add `escalate_retrieval` node; add `cross_validate` node |
| `hybrid_workflow_V2/orchestrator.py` | Rewire conditional edges to use new routing functions; add `escalate_retrieval` and `cross_validate` nodes to graph |
