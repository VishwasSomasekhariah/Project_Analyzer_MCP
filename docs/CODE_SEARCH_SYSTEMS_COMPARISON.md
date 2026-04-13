# Code Search Systems Comparison

**Comparing Three Approaches to Semantic Code Search**

This document provides a comprehensive comparison of three code search systems analyzed in detail:

1. **Context-Engine** (m1rl0k) - Open-source, ReFRAG-inspired
2. **Augment Code** - Commercial, enterprise-scale
3. **claude-context** (Zilliz) - Open-source, MCP-native

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Architecture Comparison](#architecture-comparison)
3. [Chunking Strategies](#chunking-strategies)
4. [Embedding Models](#embedding-models)
5. [Vector Databases](#vector-databases)
6. [Hybrid Search Implementation](#hybrid-search-implementation)
7. [Search Optimization Techniques](#search-optimization-techniques)
8. [Incremental Indexing](#incremental-indexing)
9. [Reranking Strategies](#reranking-strategies)
10. [Security Features](#security-features)
11. [Personalization](#personalization)
12. [Evaluation & Benchmarks](#evaluation--benchmarks)
13. [Key Technique Deep Dive](#key-technique-deep-dive)
14. [Feature Matrix](#feature-matrix)
15. [Recommendations](#recommendations)

---

## Executive Summary

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Type** | Open-source | Commercial | Open-source |
| **Scale** | Small-medium | Enterprise (500k+ files) | Medium |
| **Unique Strength** | Mini-vector gating | Quantized ANN + per-developer views | AST chunking + Merkle DAG |
| **Vector DB** | Qdrant (self-hosted) | Unknown (proprietary) | Zilliz Cloud (managed) |
| **Embedding** | BGE-base-en-v1.5 | Custom (claimed) | OpenAI/VoyageAI/Ollama |
| **Benchmarks** | None | 65% precision, 55% recall (self-reported) | None |

---

## Architecture Comparison

### Context-Engine Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTEXT-ENGINE                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Codebase → Chunker → BGE Embedder → Multi-Vector Storage       │
│              │                          │                        │
│              ├── Line-based            ├── Dense (768-dim)       │
│              ├── Semantic (AST)        ├── Lexical (4096-dim)    │
│              └── Token (16-tok)        └── Mini (64-dim)         │
│                                                                  │
│  Query → Gate (Mini) → Dense Search → Lexical Search → RRF      │
│                              │              │            │       │
│                              └──────────────┴────────────┘       │
│                                         │                        │
│                                    Reranker                      │
│                                         │                        │
│                                    Qdrant                        │
└─────────────────────────────────────────────────────────────────┘
```

### Augment Code Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    AUGMENT CODE                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Multiple Repos → Content Tracker → Quantized Index             │
│       │                 │                │                       │
│       │           File Hashes      Binary/PQ Vectors            │
│       │                 │                │                       │
│       └─────────────────┴────────────────┘                       │
│                         │                                        │
│            ┌────────────┴────────────┐                          │
│            │                         │                          │
│      Quantized Index           Fresh Embeddings                 │
│      (Fast ANN)                (Recent Changes)                 │
│            │                         │                          │
│            └─────────┬───────────────┘                          │
│                      │                                          │
│              Hybrid Search + Helpfulness Scoring                │
│                      │                                          │
│              Per-Developer Views                                │
│                      │                                          │
│              Proof of Possession Filter                         │
└─────────────────────────────────────────────────────────────────┘
```

### claude-context Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    CLAUDE-CONTEXT                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Codebase → AST Splitter (tree-sitter) → OpenAI/VoyageAI        │
│                   │                            │                 │
│             9 Languages                  Dense + BM25 Sparse    │
│                   │                            │                 │
│            Chunk Overlap (300 chars)           │                 │
│                                                │                 │
│  Merkle DAG ────────────────────────────► Zilliz Cloud          │
│  (Change Detection)                      (Milvus)               │
│                                                │                 │
│  MCP Server ◄──────────────────────────────────┘                │
│      │                                                          │
│      ├── index_codebase (background)                            │
│      ├── search_code (hybrid RRF)                               │
│      ├── clear_index                                            │
│      └── get_indexing_status                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Chunking Strategies

### Comparison Table

| Strategy | Context-Engine | Augment Code | claude-context |
|----------|---------------|--------------|----------------|
| **Line-based** | 120 lines, 20 overlap | Unknown | Fallback only |
| **Semantic/AST** | tree-sitter (basic) | Unknown | tree-sitter (9 langs) |
| **Token-based** | 16 tokens, 8 stride | Unknown | Not implemented |
| **Chunk Size** | Configurable | Unknown | 2500 chars |
| **Overlap** | 20 lines or none | Unknown | 300 chars |

### Context-Engine: Three Strategies

```python
# 1. Line-based (default)
def chunk_lines(text, max_lines=120, overlap_lines=20):
    # Simple sliding window over lines
    pass

# 2. Semantic (AST-aware)
def chunk_semantic(text, language):
    # Uses tree-sitter to extract functions/classes
    pass

# 3. Token-based (ReFRAG-inspired)
def chunk_by_tokens(text, k_tokens=16, stride_tokens=8):
    # 16-token windows with 50% overlap
    pass
```

**Unique Feature**: Micro-chunking (16 tokens) for precise retrieval of small code snippets.

### Augment Code: Unknown

No public documentation on chunking strategy. Claims to handle "multi-module architectures" and "cross-file invariants" suggesting some form of context-aware chunking.

### claude-context: AST-First with Fallback

```typescript
// Supported AST node types by language
const SPLITTABLE_NODE_TYPES = {
    typescript: ['function_declaration', 'class_declaration', 'method_definition',
                 'interface_declaration', 'type_alias_declaration'],
    python: ['function_definition', 'class_definition', 'decorated_definition'],
    java: ['method_declaration', 'class_declaration', 'interface_declaration'],
    // ... 9 languages total
};

// Flow: AST extraction → Size check → Split large chunks → Add overlap
```

**Unique Feature**: Most comprehensive AST support (9 languages) with automatic fallback to LangChain splitter.

### Key Differences

| Aspect | Context-Engine | Augment | claude-context |
|--------|---------------|---------|----------------|
| **Philosophy** | Micro-chunks for precision | Unknown | Logical units (functions/classes) |
| **Large Files** | Split by tokens/lines | Unknown | Split by lines, add overlap |
| **Languages** | Python-focused | Multi-language | 9 languages via tree-sitter |
| **Overlap Purpose** | None documented | Unknown | Context continuity (not retrieval) |

---

## Embedding Models

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Model** | BGE-base-en-v1.5 | "Custom" (unverified) | OpenAI text-embedding-3-small |
| **Dimensions** | 768 | Unknown | 1536 (or 3072 for large) |
| **Provider** | Local (sentence-transformers) | Proprietary | API (OpenAI/VoyageAI/Ollama) |
| **Code-specific** | No (general) | Claimed | VoyageAI option |
| **Batch Support** | Yes | Yes | Yes (100 per batch) |

### Context-Engine: Local BGE Model

```python
from sentence_transformers import SentenceTransformer

class EmbeddingModel:
    def __init__(self):
        self.model = SentenceTransformer("BAAI/bge-base-en-v1.5")
        self.dim = 768

    def embed(self, texts):
        return self.model.encode(texts, normalize_embeddings=True)
```

**Pros**: Free, local, no API dependency
**Cons**: General-purpose, not code-optimized

### Augment Code: Custom (Claimed)

From marketing materials:
> "Research-driven embeddings trained in pairs with retrieval"

**What's Confirmed**:
- They have a custom code completion model (RLDB)
- Third-party LLMs for chat (documented)

**What's Unconfirmed**:
- Custom embedding model architecture
- Training methodology
- Whether it's truly custom or fine-tuned

### claude-context: Multi-Provider

```typescript
// Supported providers
const providers = {
    'openai': OpenAIEmbedding,      // text-embedding-3-small (1536-dim)
    'voyageai': VoyageAIEmbedding,  // voyage-code-3 (code-optimized)
    'gemini': GeminiEmbedding,
    'ollama': OllamaEmbedding       // Local models
};

// Auto-dimension detection for custom models
async detectDimension(testText = "test"): Promise<number> {
    const response = await this.client.embeddings.create({...});
    return response.data[0].embedding.length;
}
```

**Unique Feature**: Most flexible - supports 4 providers with auto-dimension detection.

---

## Vector Databases

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Database** | Qdrant | Unknown | Milvus/Zilliz Cloud |
| **Deployment** | Self-hosted | Cloud (proprietary) | Managed cloud |
| **Index Type** | HNSW | Quantized ANN | AUTOINDEX |
| **Named Vectors** | Yes (dense, lex, mini) | Unknown | Yes (vector, sparse_vector) |
| **Filtering** | Payload filters | Hash-based | Expression filters |

### Context-Engine: Qdrant with Named Vectors

```python
vectors_config = {
    "dense": VectorParams(size=768, distance=Distance.COSINE),
    "lex": VectorParams(size=4096, distance=Distance.COSINE),
    "mini": VectorParams(size=64, distance=Distance.COSINE),  # Optional
}

client.create_collection(
    collection_name=name,
    vectors_config=vectors_config,
    hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
)
```

**Unique Feature**: Three vector types per document for different search strategies.

### Augment Code: Quantized ANN

```python
# Binary quantization (conceptual)
class BinaryQuantizer:
    def quantize(self, vector):
        return np.packbits((vector > 0).astype(np.uint8))  # 768 bits = 96 bytes

    def hamming_distance(self, a, b):
        return np.unpackbits(np.bitwise_xor(a, b)).sum()

# Product quantization for better accuracy
class ProductQuantizer:
    def __init__(self, n_subvectors=8, n_centroids=256):
        # 768-dim → 8 bytes (8 subvectors × 1 byte each)
        pass
```

**Unique Feature**: Two-phase search (coarse quantized → precise rerank) for 10-100x speedup.

### claude-context: Zilliz Cloud with Hybrid Schema

```typescript
const hybridSchema = [
    { name: 'vector', data_type: DataType.FloatVector, dim: 1536 },
    { name: 'sparse_vector', data_type: DataType.SparseFloatVector },  // BM25
];

const indexes = [
    { field_name: 'vector', index_type: 'AUTOINDEX', metric_type: 'COSINE' },
    { field_name: 'sparse_vector', index_type: 'SPARSE_INVERTED_INDEX', metric_type: 'BM25' }
];
```

**Unique Feature**: Native BM25 sparse vectors (auto-generated from content).

---

## Hybrid Search Implementation

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Dense Search** | BGE embeddings | Custom embeddings | OpenAI embeddings |
| **Sparse Search** | Hash-based BM25 | Unknown | Native BM25 function |
| **Fusion Method** | RRF (k=60) | Unknown | RRF (k=60) |
| **Weights** | 0.7 dense / 0.3 lexical | Unknown | Equal (configurable) |

### What is Hybrid Search?

```
┌─────────────────────────────────────────────────────────────────┐
│                      HYBRID SEARCH                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  DENSE (Semantic)              SPARSE (Lexical/BM25)            │
│  ───────────────               ──────────────────               │
│  Query → Embedding → ANN       Query → Tokenize → Inverted Idx  │
│                                                                  │
│  Finds: Similar MEANING        Finds: Exact KEYWORDS            │
│  "authenticate users"          "AuthService.login()"            │
│       matches                       matches                      │
│  "verify credentials"          "AuthService", "login" literally │
│                                                                  │
│  Strength: Synonyms            Strength: Identifiers, names     │
│  Weakness: Exact names         Weakness: No semantics           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    RRF FUSION: score = Σ 1/(k + rank)
```

### Context-Engine: Hash-Based Lexical Vectors

```python
def create_lexical_vector(text, dim=4096):
    """Create BM25-style hash vector."""
    tokens = tokenize_code(text)  # Split camelCase, snake_case

    vec = [0.0] * dim
    for token in tokens:
        idx = int(hashlib.md5(token.encode()).hexdigest()[:8], 16) % dim
        vec[idx] += 1.0

    # L2 normalize
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm > 0 else vec
```

### claude-context: Native Milvus BM25

```typescript
// Milvus handles BM25 natively
const searchRequests = [
    { data: queryEmbedding.vector, anns_field: "vector", limit: topK },
    { data: query,  // Raw text - BM25 handles tokenization
      anns_field: "sparse_vector",
      param: { "drop_ratio_search": 0.2 },  // Drop low-weight terms
      limit: topK }
];

const results = await vectorDatabase.hybridSearch(collection, searchRequests, {
    rerank: { strategy: 'rrf', params: { k: 60 } }
});
```

### RRF Fusion Example

```
Query: "AuthService error handling"

Dense Results:              Sparse Results:
1. chunk_A (rank 1)        1. chunk_B (rank 1) ← "AuthService" exact match
2. chunk_C (rank 2)        2. chunk_A (rank 2)
3. chunk_B (rank 3)        3. chunk_D (rank 3)

RRF Scores (k=60):
chunk_A: 1/(60+1) + 1/(60+2) = 0.0164 + 0.0161 = 0.0325 ← Winner
chunk_B: 1/(60+3) + 1/(60+1) = 0.0159 + 0.0164 = 0.0323
chunk_C: 1/(60+2) + 0        = 0.0161

Final: [chunk_A, chunk_B, chunk_C, chunk_D]
```

---

## Search Optimization Techniques

### Comparison Table

| Technique | Context-Engine | Augment Code | claude-context |
|-----------|---------------|--------------|----------------|
| **Two-Stage Search** | Mini-vector gating | Quantized → Full | Not implemented |
| **Compression** | Random projection (64-dim) | Binary/PQ quantization | None |
| **Speedup** | ~10x | 10-100x | N/A (cloud handles) |
| **Adaptive** | Bypass for short queries | Fresh/stale hybrid | N/A |

### Context-Engine: Mini-Vector Gating

```python
# Random projection: 768-dim → 64-dim
def project_mini(vec, out_dim=64, seed=1337):
    """Johnson-Lindenstrauss projection preserves distances."""
    M = get_rademacher_matrix(len(vec), out_dim, seed)
    out = [sum(v * M[i][j] for i, v in enumerate(vec)) for j in range(out_dim)]
    norm = math.sqrt(sum(x*x for x in out)) or 1.0
    return [x / norm for x in out]

# Two-stage search
def search_with_gating(query_embedding, limit=10, gate_candidates=200):
    # Stage 1: Fast search with 64-dim mini vectors
    query_mini = project_mini(query_embedding)
    candidates = qdrant.search(query_vector=("mini", query_mini), limit=gate_candidates)

    # Stage 2: Precise search restricted to candidates
    return qdrant.search(
        query_vector=("dense", query_embedding),
        filter=HasIdCondition(has_id=[c.id for c in candidates]),
        limit=limit
    )
```

**Key Insight**: 768-dim → 64-dim = 12x fewer operations, ~99% same results.

### Augment Code: Quantized ANN

```python
# Two-phase search
def quantized_search(query_embedding, limit=10):
    # Phase 1: Coarse search with quantized vectors (fast)
    query_quantized = quantizer.quantize(query_embedding)
    candidates = quantized_index.search(query_quantized, limit=500)

    # Phase 2: Precise reranking with full vectors
    full_results = []
    for candidate_id in candidates:
        full_vec = get_full_embedding(candidate_id)
        score = cosine_similarity(query_embedding, full_vec)
        full_results.append((candidate_id, score))

    return sorted(full_results, key=lambda x: x[1], reverse=True)[:limit]
```

**Key Insight**: 3KB → 96 bytes (binary) or 8 bytes (PQ) = 32-400x compression.

### claude-context: Cloud-Managed

No explicit optimization - relies on Zilliz Cloud's AUTOINDEX:
- Automatic index type selection
- Managed scaling
- No user-side compression needed

---

## Incremental Indexing

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Change Detection** | Not implemented | Content hash tracking | Merkle DAG |
| **Update Latency** | Full re-index | Seconds (fresh layer) | File-level re-index |
| **Strategy** | N/A | Hybrid fresh/stale | Delete old + insert new |

### Augment Code: Hybrid Fresh/Stale

```python
class HybridIndex:
    def __init__(self):
        self.quantized_index = QuantizedIndex()  # Stable, rebuilt nightly
        self.fresh_embeddings = {}               # Recent changes
        self.content_tracker = {}                # path → hash

    def update_file(self, path, content, embedding):
        # Immediately available in fresh layer
        self.fresh_embeddings[path] = embedding
        self.content_tracker[path] = hash(content)

    def search(self, query_embedding, limit=10):
        # Search both layers, prioritize fresh
        quantized_results = self.quantized_index.search(query_embedding)
        fresh_results = brute_force_search(self.fresh_embeddings, query_embedding)
        return merge_prioritize_fresh(quantized_results, fresh_results)[:limit]
```

**Key Insight**: Zero-latency updates via fresh layer; background rebuild of quantized index.

### claude-context: Merkle DAG

```typescript
class MerkleDAG {
    static compare(dag1, dag2): { added, removed, modified } {
        const nodes1 = new Map(dag1.getAllNodes().map(n => [n.id, n]));
        const nodes2 = new Map(dag2.getAllNodes().map(n => [n.id, n]));

        return {
            added: [...nodes2.keys()].filter(k => !nodes1.has(k)),
            removed: [...nodes1.keys()].filter(k => !nodes2.has(k)),
            modified: [...nodes1.entries()]
                .filter(([id, n]) => nodes2.has(id) && nodes2.get(id).data !== n.data)
                .map(([id]) => id)
        };
    }
}

// Incremental re-index
async reindexByChange(codebasePath) {
    const { added, removed, modified } = await synchronizer.checkForChanges();

    for (const file of [...removed, ...modified]) {
        await this.deleteFileChunks(collectionName, file);
    }

    await this.processFileList([...added, ...modified].map(f => join(codebasePath, f)));
}
```

**Key Insight**: Only re-index files with changed content hashes.

---

## Reranking Strategies

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Cross-Encoder** | ms-marco-MiniLM | Unknown | Not implemented |
| **Learned Reranker** | TinyScorer (MLP) | Unknown | Not implemented |
| **Helpfulness Scoring** | Not implemented | Yes | Not implemented |

### Context-Engine: Cross-Encoder + Adaptive Learning

```python
# Cross-encoder reranking
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self):
        self.model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    def rerank(self, query, results, top_k=10):
        pairs = [(query, r["payload"]["text"]) for r in results]
        scores = self.model.predict(pairs)

        for result, score in zip(results, scores):
            result["rerank_score"] = float(score)

        return sorted(results, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

# Adaptive learning (knowledge distillation)
class TinyScorer:
    """2-layer MLP that learns from cross-encoder teacher."""
    def learn_from_teacher(self, query_vec, doc_vecs, teacher_scores, lr=0.001):
        # Distill cross-encoder knowledge into fast scorer
        pass
```

### Augment Code: Helpfulness Scoring

```python
class HelpfulnessScorer:
    def __init__(self):
        self.file_patterns = {
            "implementation": 1.5,    # *_service.py, *_handler.py
            "test_file": 0.6,         # test_*.py
            "type_definitions": 0.7,  # *.d.ts
            "vendor": 0.4,            # node_modules/*
        }

    def score(self, result):
        path = result["path"]
        base_score = result["score"]

        multiplier = 1.0
        if self._is_implementation(path):
            multiplier *= self.file_patterns["implementation"]
        if self._is_test_file(path):
            multiplier *= self.file_patterns["test_file"]

        return base_score * multiplier
```

**Key Insight**: Boost implementation files, penalize tests/types/vendor.

---

## Security Features

### Comparison Table

| Feature | Context-Engine | Augment Code | claude-context |
|---------|---------------|--------------|----------------|
| **Access Control** | Not implemented | Proof of Possession | Collection-based |
| **Multi-tenant** | No | Yes (per-developer) | No |
| **Data Privacy** | Local only | Hash verification | Cloud (Zilliz trust) |

### Augment Code: Proof of Possession

```python
# Client sends file hashes (not content)
request = {
    "query": "authentication flow",
    "known_hashes": ["a3f8b2c1...", "b7e2d4f9...", ...]
}

# Server filters results
def secure_search(query_embedding, client_hashes, limit=10):
    raw_results = index.search(query_embedding, limit=limit * 5)

    # Only return files the client can prove they have
    return [r for r in raw_results if r["content_hash"] in client_hashes][:limit]
```

**Key Insight**: Hash proves possession without transmitting content; can't guess hashes.

---

## Personalization

### Comparison Table

| Feature | Context-Engine | Augment Code | claude-context |
|---------|---------------|--------------|----------------|
| **Per-Developer Views** | No | Yes | No |
| **Branch Awareness** | No | Yes | No |
| **Local Changes** | No | Overlay system | No |

### Augment Code: Per-Developer Index Views

```python
class DeveloperView:
    developer_id: str
    base_branch: str = "main"
    current_branch: str

    modified_files: Dict[str, List[float]] = {}  # Overlay
    deleted_files: Set[str] = set()

def search_for_developer(developer_id, branch, query_embedding, limit=10):
    view = get_or_create_view(developer_id, branch)

    # Search shared index, excluding deleted/modified
    excluded = view.deleted_files | set(view.modified_files.keys())
    shared_results = shared_index.search(query_embedding, exclude_paths=excluded)

    # Search overlay (local changes)
    overlay_results = brute_force_search(view.modified_files, query_embedding)

    # Merge, prioritizing local changes
    return merge_results(shared_results, overlay_results)[:limit]
```

**Key Insight**: Shared base index + per-developer overlay for uncommitted changes.

---

## Evaluation & Benchmarks

### Comparison Table

| Aspect | Context-Engine | Augment Code | claude-context |
|--------|---------------|--------------|----------------|
| **Precision** | Not measured | 65% (self-reported) | Not measured |
| **Recall** | Not measured | 55% (self-reported) | Not measured |
| **Dataset** | None | 50 PRs, 5 repos | None |
| **Independent** | N/A | No (self-evaluated) | N/A |
| **Retrieval-specific** | N/A | No (end-to-end only) | N/A |

### Augment's Benchmark Methodology

```
┌─────────────────────────────────────────────────────────────────┐
│                 AUGMENT BENCHMARK METHODOLOGY                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Select 50 PRs from 5 repos (Sentry, Grafana, Cal.com, etc.) │
│                                                                  │
│  2. Create "Golden Comments" = known bugs that should be caught │
│                                                                  │
│  3. Run AI tools on PRs, compare output to golden comments      │
│                                                                  │
│  4. Score:                                                      │
│     - Match golden = True Positive                              │
│     - Tool comment not in golden = False Positive               │
│     - Golden missed = False Negative                            │
│                                                                  │
│  CRITICAL ISSUE: Augment created their own golden comments      │
│                  AND won their own benchmark                    │
└─────────────────────────────────────────────────────────────────┘
```

### What's NOT Measured

None of the three systems provide:
- **Retrieval precision**: "Of chunks retrieved, how many were relevant?"
- **Retrieval recall**: "Of all relevant chunks, how many were retrieved?"
- **Independent validation**: Third-party evaluation

---

## Key Technique Deep Dive

### Technique 1: Mini-Vector Gating (Context-Engine)

**Problem**: Full vector search is expensive at scale.

**Solution**: Two-stage search with compressed vectors.

```
┌─────────────────────────────────────────────────────────────────┐
│  Stage 1: Gate with 64-dim mini vectors                         │
│  ─────────────────────────────────────                          │
│  Query (768) → Random Projection → Query Mini (64)              │
│                                         ↓                       │
│                               Search 100k mini vectors          │
│                               (64-dim = 12x faster)             │
│                                         ↓                       │
│                               Top 200 candidate IDs             │
│                                                                  │
│  Stage 2: Precise search on candidates only                     │
│  ─────────────────────────────────────────                      │
│  Query (768) → Search ONLY 200 full vectors                     │
│                (not 100k!)                                       │
│                         ↓                                       │
│                Final top-K results                              │
│                                                                  │
│  Result: ~10x speedup, ~99% same accuracy                       │
└─────────────────────────────────────────────────────────────────┘
```

### Technique 2: Quantized ANN (Augment)

**Problem**: Enterprise scale (500k+ files) requires extreme optimization.

**Solution**: Compress vectors for fast approximate search.

```
┌─────────────────────────────────────────────────────────────────┐
│  Binary Quantization                                             │
│  ───────────────────                                            │
│  [0.234, -0.891, 0.445, ...] (768 floats = 3KB)                 │
│                     ↓                                            │
│  [1, 0, 1, 1, 0, 1, ...] (768 bits = 96 bytes)                  │
│                                                                  │
│  Distance: Hamming (XOR + popcount) instead of cosine           │
│  Speedup: 32x smaller, CPU-optimized bit operations             │
│                                                                  │
│  Product Quantization (better accuracy)                         │
│  ─────────────────────────────────────                          │
│  768-dim → 8 subvectors → 8 centroid indices                    │
│  768 floats → 8 bytes (96x compression!)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Technique 3: Merkle DAG Sync (claude-context)

**Problem**: Re-indexing entire codebase on every change is expensive.

**Solution**: Content-addressable change detection.

```
┌─────────────────────────────────────────────────────────────────┐
│  Merkle DAG Structure                                            │
│  ───────────────────                                            │
│                 ┌────────────┐                                   │
│                 │ Root       │                                   │
│                 │ hash: abc  │                                   │
│                 └─────┬──────┘                                   │
│         ┌─────────────┼─────────────┐                            │
│         ↓             ↓             ↓                            │
│    ┌────────┐   ┌────────┐   ┌────────┐                         │
│    │file1.ts│   │file2.py│   │file3.go│                         │
│    │h: def  │   │h: ghi  │   │h: jkl  │                         │
│    └────────┘   └────────┘   └────────┘                         │
│                                                                  │
│  On change: file2.py modified → new hash → root changes         │
│  Compare DAGs → precisely identify changed files                 │
│  Re-index ONLY changed files                                     │
└─────────────────────────────────────────────────────────────────┘
```

### Technique 4: Hybrid Fresh/Stale Index (Augment)

**Problem**: Index rebuilding creates staleness window.

**Solution**: Dual-layer index with immediate availability.

```
┌─────────────────────────────────────────────────────────────────┐
│  Quantized Index (stable)     Fresh Embeddings (real-time)      │
│  ─────────────────────────    ────────────────────────────      │
│  • Rebuilt nightly            • Immediately updated              │
│  • Fast (quantized)           • Slower (full vectors)            │
│  • Covers 99% of files        • Covers recent changes            │
│                                                                  │
│  Search: Query both layers → Merge → Prioritize fresh           │
│                                                                  │
│  Result: Zero-latency updates + fast search                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Feature Matrix

### Complete Feature Comparison

| Feature | Context-Engine | Augment Code | claude-context |
|---------|---------------|--------------|----------------|
| **CHUNKING** | | | |
| Line-based | Yes (120 lines) | Unknown | Fallback |
| AST-aware | Basic | Unknown | 9 languages |
| Token-based | Yes (16 tokens) | Unknown | No |
| Overlap | 20 lines | Unknown | 300 chars |
| | | | |
| **EMBEDDING** | | | |
| Model | BGE-base-en-v1.5 | Custom (claimed) | OpenAI/VoyageAI |
| Dimensions | 768 | Unknown | 1536/3072 |
| Local option | Yes | No | Yes (Ollama) |
| Code-specific | No | Claimed | VoyageAI option |
| | | | |
| **VECTOR DB** | | | |
| Database | Qdrant | Proprietary | Zilliz Cloud |
| Deployment | Self-hosted | Cloud | Managed cloud |
| Multi-vector | Yes (3 types) | Unknown | Yes (2 types) |
| | | | |
| **SEARCH** | | | |
| Hybrid (dense+sparse) | Yes (RRF) | Yes | Yes (RRF) |
| Two-stage gating | Yes (mini vectors) | Yes (quantized) | No |
| Cross-encoder rerank | Yes | Unknown | No |
| Helpfulness scoring | No | Yes | No |
| | | | |
| **OPTIMIZATION** | | | |
| Compression | Random projection | Binary/PQ | None (cloud) |
| Speedup | ~10x | 10-100x | N/A |
| Incremental index | No | Yes (fresh/stale) | Yes (Merkle DAG) |
| | | | |
| **ENTERPRISE** | | | |
| Scale | Small-medium | 500k+ files | Medium |
| Multi-repo | No | Yes | No |
| Per-developer views | No | Yes | No |
| Access control | No | Proof of possession | Collection-based |
| | | | |
| **INTEGRATION** | | | |
| MCP support | No | Yes | Yes (native) |
| VS Code extension | No | Yes | Yes |
| CLI | No | Yes (Auggie) | No |
| | | | |
| **EVALUATION** | | | |
| Benchmarks published | No | Yes (self-reported) | No |
| Precision/Recall | Unknown | 65%/55% | Unknown |
| Independent validation | No | No | No |

---

## Recommendations

### Choose Context-Engine If:

- You need **self-hosted, local deployment**
- Your codebase is **small-medium** (< 100k files)
- You want **maximum customization** (mini vectors, token chunking)
- You need **cross-encoder reranking** for precision
- Budget: **Free** (open-source)

### Choose Augment Code If:

- You have **enterprise scale** (500k+ files, multiple repos)
- You need **per-developer personalization** (branch awareness)
- **Security is critical** (proof of possession)
- You want **real-time index updates** (fresh/stale hybrid)
- Budget: **Commercial** (pricing not public)

### Choose claude-context If:

- You want **MCP-native integration** with Claude
- You need **managed infrastructure** (Zilliz Cloud)
- Your codebase uses **multiple languages** (9 AST parsers)
- You want **simple deployment** (npm install + cloud)
- You need **incremental indexing** (Merkle DAG)
- Budget: **Zilliz Cloud pricing** + embedding API costs

### Build Your Own If:

You need specific features not available in any system:

| Missing Feature | Solution |
|-----------------|----------|
| Higher retrieval recall | Implement parent-child chunking or contextual retrieval |
| Code-specific embeddings | Fine-tune on your codebase or use Voyage Code |
| Independent evaluation | Build benchmark with RAGAS/DeepEval |
| Cross-chunk awareness | Implement ColBERT-style multi-vector per token |

---

## References

### Documentation
- [Context-Engine GitHub](https://github.com/m1rl0k/Context-Engine)
- [claude-context GitHub](https://github.com/zilliztech/claude-context)
- [Augment Code Documentation](https://docs.augmentcode.com)

### Technical Papers
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Johnson-Lindenstrauss Lemma](https://en.wikipedia.org/wiki/Johnson%E2%80%93Lindenstrauss_lemma)
- [Product Quantization](https://ieeexplore.ieee.org/document/5432202)
- [Tree-sitter](https://tree-sitter.github.io/tree-sitter/)

### Related Guides
- [VECTOR_RAG_IMPLEMENTATION_GUIDE.md](./VECTOR_RAG_IMPLEMENTATION_GUIDE.md) - Context-Engine patterns
- [ENTERPRISE_CODEBASE_INDEXING_GUIDE.md](./ENTERPRISE_CODEBASE_INDEXING_GUIDE.md) - Augment patterns
- [CLAUDE_CONTEXT_IMPLEMENTATION_GUIDE.md](./CLAUDE_CONTEXT_IMPLEMENTATION_GUIDE.md) - Zilliz patterns
