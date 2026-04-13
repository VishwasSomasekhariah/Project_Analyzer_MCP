# Vector RAG Implementation Guide

**Based on Context-Engine Architecture Analysis**

This guide explains how to build a production-grade Vector RAG (Retrieval-Augmented Generation) system for code search, following the patterns discovered in the [Context-Engine](https://github.com/m1rl0k/Context-Engine) project.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [1. Chunking Strategies](#1-chunking-strategies)
- [2. Embedding Pipeline](#2-embedding-pipeline)
- [3. Multi-Vector Storage](#3-multi-vector-storage)
- [4. Mini Vectors for Fast Gating](#4-mini-vectors-for-fast-gating)
- [5. Hybrid Search Pipeline](#5-hybrid-search-pipeline)
- [6. Reranking](#6-reranking)
- [7. Span Budgeting](#7-span-budgeting)
- [8. Decoder Integration](#8-decoder-integration)
- [9. Configuration Reference](#9-configuration-reference)
- [Appendix: ReFRAG Comparison](#appendix-refrag-comparison)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           VECTOR RAG ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐                     │
│  │   Codebase   │────►│   Chunker    │────►│  Embedder    │                     │
│  │              │     │              │     │  (bge-base)  │                     │
│  └──────────────┘     └──────────────┘     └──────┬───────┘                     │
│                                                   │                              │
│                              ┌────────────────────┼────────────────────┐        │
│                              ▼                    ▼                    ▼        │
│                       ┌───────────┐        ┌───────────┐        ┌───────────┐  │
│                       │  Dense    │        │  Lexical  │        │   Mini    │  │
│                       │  Vector   │        │  Vector   │        │  Vector   │  │
│                       │ (768-dim) │        │(4096-dim) │        │ (64-dim)  │  │
│                       └─────┬─────┘        └─────┬─────┘        └─────┬─────┘  │
│                             │                    │                    │        │
│                             └────────────────────┼────────────────────┘        │
│                                                  ▼                              │
│                                          ┌─────────────┐                        │
│                                          │   Qdrant    │                        │
│                                          │   (HNSW)    │                        │
│                                          └──────┬──────┘                        │
│                                                 │                               │
│  ┌──────────────┐                               │                               │
│  │    Query     │───────────────────────────────┘                               │
│  └──────┬───────┘                                                               │
│         │                                                                        │
│         ▼                                                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         RETRIEVAL PIPELINE                               │   │
│  │  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   │   │
│  │  │ Gate    │──►│ Dense   │──►│ Lexical │──►│   RRF   │──►│ Rerank  │   │   │
│  │  │ (Mini)  │   │ Search  │   │ Search  │   │ Fusion  │   │         │   │   │
│  │  └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                 │                               │
│                                                 ▼                               │
│                                          ┌─────────────┐                        │
│                                          │   Results   │                        │
│                                          └─────────────┘                        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. Chunking Strategies

Context-Engine implements three chunking strategies. Choose based on your use case.

### 1.1 Line-Based Chunking (Simple)

Best for: General-purpose indexing, large files.

```python
def chunk_lines(
    text: str,
    max_lines: int = 120,
    overlap_lines: int = 20
) -> List[Dict]:
    """Split text into overlapping line-based chunks."""
    lines = text.splitlines(keepends=True)
    chunks = []

    i = 0
    while i < len(lines):
        end = min(i + max_lines, len(lines))
        chunk_lines = lines[i:end]
        chunk_text = "".join(chunk_lines)

        chunks.append({
            "text": chunk_text,
            "start_line": i + 1,
            "end_line": end,
        })

        # Advance with overlap
        i += max_lines - overlap_lines
        if i + overlap_lines >= len(lines):
            break

    return chunks
```

**Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_lines` | 120 | Maximum lines per chunk |
| `overlap_lines` | 20 | Overlap between consecutive chunks |

### 1.2 Semantic Chunking (AST-Aware)

Best for: Code files where you want to keep functions/classes together.

```python
def chunk_semantic(text: str, language: str) -> List[Dict]:
    """AST-aware chunking that keeps code structures intact."""
    try:
        import tree_sitter
        parser = get_parser(language)
        tree = parser.parse(text.encode())

        chunks = []
        for node in tree.root_node.children:
            # Extract complete functions, classes, etc.
            if node.type in ('function_definition', 'class_definition',
                            'method_definition'):
                chunks.append({
                    "text": text[node.start_byte:node.end_byte],
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "symbol_type": node.type,
                })

        return chunks if chunks else chunk_lines(text)  # Fallback
    except Exception:
        return chunk_lines(text)  # Fallback to line-based
```

### 1.3 Token-Based Micro-Chunking (ReFRAG-Inspired)

Best for: Precise retrieval where you need small, focused snippets.

```python
def chunk_by_tokens(
    text: str,
    k_tokens: int = 16,      # Window size
    stride_tokens: int = 8    # Step size (overlap = k - stride)
) -> List[Dict]:
    """Token-based micro-chunking with sliding window."""
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-base-en-v1.5")
    tokens = tokenizer.encode(text, add_special_tokens=False)

    chunks = []
    i = 0
    while i < len(tokens):
        end = min(i + k_tokens, len(tokens))
        chunk_tokens = tokens[i:end]
        chunk_text = tokenizer.decode(chunk_tokens)

        # Map back to line numbers (simplified)
        chunks.append({
            "text": chunk_text,
            "start_token": i,
            "end_token": end,
        })

        i += stride_tokens
        if end >= len(tokens):
            break

    return chunks
```

**Why Overlapping Windows?**

```
Without overlap (stride = window):
  "validate_token checks if | JWT token is valid"
                          ↑
                    Chunk boundary cuts the phrase!

With overlap (stride = window/2):
  Chunk 1: "validate_token checks if JWT token"
  Chunk 2: "checks if JWT token is valid and"
                    ↑
            Both chunks capture the full phrase
```

**Configuration:**
| Parameter | Default | Environment Variable |
|-----------|---------|---------------------|
| `k_tokens` | 16 | `MICRO_CHUNK_TOKENS` |
| `stride_tokens` | 8 | `MICRO_CHUNK_STRIDE` |
| `max_per_file` | 200 | `MAX_MICRO_CHUNKS_PER_FILE` |

---

## 2. Embedding Pipeline

### 2.1 Model Selection

Context-Engine uses `BAAI/bge-base-en-v1.5` (768-dimensional embeddings).

```python
from sentence_transformers import SentenceTransformer

class EmbeddingModel:
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5"):
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        """Batch embed texts."""
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,  # L2 normalize
            show_progress_bar=False
        )
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Embed a single query."""
        return self.embed([query])[0]
```

**Recommended Models:**
| Model | Dimensions | Use Case |
|-------|------------|----------|
| `BAAI/bge-base-en-v1.5` | 768 | General purpose (recommended) |
| `BAAI/bge-large-en-v1.5` | 1024 | Higher accuracy, slower |
| `BAAI/bge-small-en-v1.5` | 384 | Faster, lower accuracy |

### 2.2 Embedding at Index Time

```python
def index_file(file_path: str, embedder: EmbeddingModel):
    """Index a single file."""
    content = read_file(file_path)
    language = detect_language(file_path)

    # Choose chunking strategy
    if os.environ.get("INDEX_MICRO_CHUNKS") == "1":
        chunks = chunk_by_tokens(content)
    else:
        chunks = chunk_semantic(content, language)

    # Batch embed all chunks
    texts = [c["text"] for c in chunks]
    embeddings = embedder.embed(texts)

    # Prepare points for Qdrant
    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        points.append({
            "id": generate_uuid(file_path, i),
            "vector": {
                "dense": embedding,
                "lex": create_lexical_vector(chunk["text"]),
                "mini": project_mini(embedding),  # Optional
            },
            "payload": {
                "path": file_path,
                "text": chunk["text"],
                "start_line": chunk.get("start_line"),
                "end_line": chunk.get("end_line"),
                "language": language,
            }
        })

    return points
```

---

## 3. Multi-Vector Storage

Context-Engine stores **three vectors per chunk** in Qdrant using named vectors.

### 3.1 Vector Types

| Vector | Dimensions | Purpose |
|--------|------------|---------|
| `dense` | 768 | Semantic similarity (main search) |
| `lex` | 4096 | Lexical/keyword matching (BM25-style) |
| `mini` | 64 | Fast pre-filtering (gating) |

### 3.2 Collection Setup

```python
from qdrant_client import QdrantClient, models

def create_collection(client: QdrantClient, name: str):
    """Create collection with named vectors."""
    vectors_config = {
        "dense": models.VectorParams(
            size=768,
            distance=models.Distance.COSINE,
        ),
        "lex": models.VectorParams(
            size=4096,
            distance=models.Distance.COSINE,
        ),
    }

    # Add mini vector if REFRAG_MODE enabled
    if os.environ.get("REFRAG_MODE") == "1":
        vectors_config["mini"] = models.VectorParams(
            size=64,
            distance=models.Distance.COSINE,
        )

    client.create_collection(
        collection_name=name,
        vectors_config=vectors_config,
        # HNSW index parameters
        hnsw_config=models.HnswConfigDiff(
            m=16,
            ef_construct=100,
        ),
    )
```

### 3.3 Lexical Vector Creation (BM25-Style Hashing)

```python
import hashlib
import re
from typing import List

STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been", ...}

def tokenize_code(text: str) -> List[str]:
    """Tokenize code with identifier splitting."""
    # Split on non-alphanumeric
    parts = re.split(r"[^A-Za-z0-9]+", text)

    tokens = []
    for p in parts:
        if not p:
            continue
        # Split camelCase and snake_case
        segments = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", p)
        tokens.extend([s.lower() for s in segments])

    # Remove stop words
    return [t for t in tokens if t and t not in STOP_WORDS]

def create_lexical_vector(text: str, dim: int = 4096) -> List[float]:
    """Create BM25-style hash vector."""
    tokens = tokenize_code(text)

    vec = [0.0] * dim
    for token in tokens:
        # Hash token to index
        h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
        idx = h % dim
        vec[idx] += 1.0

    # L2 normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]

    return vec
```

---

## 4. Mini Vectors for Fast Gating

This is the key "ReFRAG-inspired" optimization: use compressed vectors for fast pre-filtering before expensive full-vector search.

### 4.1 How It Works

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     GATE-FIRST TWO-STAGE SEARCH                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  STAGE 1: FAST ROUGH FILTERING                                              │
│  ─────────────────────────────                                              │
│                                                                              │
│  Query (768-dim) ──► Random Projection ──► Query Mini (64-dim)              │
│                                                   │                          │
│                                                   ▼                          │
│                                         Search "mini" vectors                │
│                                         (64-dim = 12x fewer ops)             │
│                                                   │                          │
│                                                   ▼                          │
│                                         Top 200 candidate IDs                │
│                                                                              │
│  STAGE 2: PRECISE SEARCH (Restricted)                                       │
│  ────────────────────────────────────                                       │
│                                                                              │
│  Query (768-dim) ──► Search ONLY 200 candidates ──► Final Results           │
│                      (not all 100k documents!)                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘

Performance: ~10x faster with ~99% same results
```

### 4.2 Random Projection Implementation

Based on the **Johnson-Lindenstrauss lemma**: random projection approximately preserves distances.

```python
import random
import math
from typing import List, Dict, Tuple

# Cache projection matrices
_PROJECTION_CACHE: Dict[Tuple[int, int, int], List[List[float]]] = {}

def get_projection_matrix(
    in_dim: int,
    out_dim: int,
    seed: int = 1337
) -> List[List[float]]:
    """Get or create random Rademacher projection matrix."""
    key = (in_dim, out_dim, seed)

    if key not in _PROJECTION_CACHE:
        rng = random.Random(seed)
        scale = 1.0 / math.sqrt(out_dim)

        # Rademacher matrix: random +1/-1 values, scaled
        matrix = [
            [scale * (1.0 if rng.random() < 0.5 else -1.0)
             for _ in range(out_dim)]
            for _ in range(in_dim)
        ]
        _PROJECTION_CACHE[key] = matrix

    return _PROJECTION_CACHE[key]

def project_mini(
    vec: List[float],
    out_dim: int = 64
) -> List[float]:
    """Project dense vector to mini vector via random projection."""
    if not vec:
        return [0.0] * out_dim

    M = get_projection_matrix(len(vec), out_dim)

    # y = x @ M
    out = [0.0] * out_dim
    for i, val in enumerate(vec):
        if val == 0.0:
            continue
        for j in range(out_dim):
            out[j] += val * M[i][j]

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]
```

### 4.3 Gate-First Search Implementation

```python
from qdrant_client import QdrantClient, models

def search_with_gating(
    client: QdrantClient,
    collection: str,
    query_embedding: List[float],
    limit: int = 10,
    gate_candidates: int = 200,
) -> List[dict]:
    """Two-stage search with mini-vector gating."""

    # STAGE 1: Fast pre-filter with mini vectors
    query_mini = project_mini(query_embedding)

    gate_results = client.search(
        collection_name=collection,
        query_vector=("mini", query_mini),
        limit=gate_candidates,
    )

    candidate_ids = [r.id for r in gate_results]

    if not candidate_ids:
        # Fallback to full search
        return search_full(client, collection, query_embedding, limit)

    # STAGE 2: Precise search restricted to candidates
    filter_condition = models.Filter(
        must=[models.HasIdCondition(has_id=candidate_ids)]
    )

    results = client.search(
        collection_name=collection,
        query_vector=("dense", query_embedding),
        query_filter=filter_condition,
        limit=limit,
    )

    return [
        {
            "id": r.id,
            "score": r.score,
            "payload": r.payload,
        }
        for r in results
    ]
```

### 4.4 Adaptive Gating

Context-Engine disables gating for very short queries or queries without strong identifiers:

```python
def should_bypass_gate(queries: List[str]) -> bool:
    """Determine if gating should be skipped."""
    total_tokens = sum(len(tokenize_code(q)) for q in queries)

    # Check for strong identifiers (camelCase, UPPER_CASE, snake_case)
    has_strong_id = any(
        any(
            t.isupper() or
            "_" in t or
            (any(c.isupper() for c in t[1:]) and any(c.islower() for c in t))
            for t in tokenize_code(q)
        )
        for q in queries
    )

    # Bypass if query is too short and has no strong identifiers
    if total_tokens < 3 and not has_strong_id:
        return True

    return False
```

---

## 5. Hybrid Search Pipeline

Combine dense (semantic) and lexical (keyword) search for best results.

### 5.1 Reciprocal Rank Fusion (RRF)

```python
def reciprocal_rank_fusion(
    result_lists: List[List[dict]],
    k: int = 60,
    weights: List[float] = None,
) -> List[dict]:
    """Combine multiple ranked lists using RRF."""
    if weights is None:
        weights = [1.0] * len(result_lists)

    # Accumulate RRF scores
    scores = {}  # id -> score
    payloads = {}  # id -> payload

    for results, weight in zip(result_lists, weights):
        for rank, result in enumerate(results):
            doc_id = result["id"]
            rrf_score = weight / (k + rank + 1)

            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
            payloads[doc_id] = result.get("payload", {})

    # Sort by combined score
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    return [
        {"id": doc_id, "score": scores[doc_id], "payload": payloads[doc_id]}
        for doc_id in sorted_ids
    ]
```

### 5.2 Full Hybrid Search

```python
def hybrid_search(
    client: QdrantClient,
    collection: str,
    query: str,
    embedder: EmbeddingModel,
    limit: int = 10,
    dense_weight: float = 0.7,
    lexical_weight: float = 0.3,
    use_gating: bool = True,
) -> List[dict]:
    """Full hybrid search with optional gating."""

    # Embed query
    query_dense = embedder.embed_query(query)
    query_lex = create_lexical_vector(query)

    # Optional gating
    filter_condition = None
    if use_gating and not should_bypass_gate([query]):
        query_mini = project_mini(query_dense)
        gate_results = client.search(
            collection_name=collection,
            query_vector=("mini", query_mini),
            limit=200,
        )
        candidate_ids = [r.id for r in gate_results]
        if candidate_ids:
            filter_condition = models.Filter(
                must=[models.HasIdCondition(has_id=candidate_ids)]
            )

    # Parallel dense and lexical search
    dense_results = client.search(
        collection_name=collection,
        query_vector=("dense", query_dense),
        query_filter=filter_condition,
        limit=limit * 3,
    )

    lexical_results = client.search(
        collection_name=collection,
        query_vector=("lex", query_lex),
        query_filter=filter_condition,
        limit=limit * 3,
    )

    # Convert to dicts
    dense_list = [{"id": r.id, "score": r.score, "payload": r.payload}
                  for r in dense_results]
    lex_list = [{"id": r.id, "score": r.score, "payload": r.payload}
                for r in lexical_results]

    # RRF fusion
    fused = reciprocal_rank_fusion(
        [dense_list, lex_list],
        weights=[dense_weight, lexical_weight],
    )

    return fused[:limit]
```

---

## 6. Reranking

Use a cross-encoder to re-score top results for better precision.

### 6.1 Cross-Encoder Reranking

```python
from sentence_transformers import CrossEncoder

class Reranker:
    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(
        self,
        query: str,
        results: List[dict],
        top_k: int = 10
    ) -> List[dict]:
        """Rerank results using cross-encoder."""
        if not results:
            return []

        # Prepare pairs
        pairs = [(query, r["payload"]["text"]) for r in results]

        # Score all pairs
        scores = self.model.predict(pairs)

        # Combine with original results
        for result, score in zip(results, scores):
            result["rerank_score"] = float(score)

        # Sort by rerank score
        reranked = sorted(results, key=lambda x: x["rerank_score"], reverse=True)

        return reranked[:top_k]
```

### 6.2 Learning Reranker (Adaptive)

Context-Engine includes an adaptive reranker that learns from usage:

```python
class TinyScorer:
    """Lightweight 2-layer MLP that learns per-collection patterns."""

    def __init__(self, input_dim: int = 768, hidden_dim: int = 128):
        self.W1 = self._init_weights(input_dim, hidden_dim)
        self.b1 = [0.0] * hidden_dim
        self.W2 = self._init_weights(hidden_dim, 1)
        self.b2 = [0.0]

    def score(self, query_vec: List[float], doc_vec: List[float]) -> float:
        """Score a query-document pair."""
        # Concatenate or use element-wise product
        features = [q * d for q, d in zip(query_vec, doc_vec)]

        # Forward pass
        hidden = self._relu(self._matmul(features, self.W1, self.b1))
        output = self._matmul(hidden, self.W2, self.b2)

        return output[0]

    def learn_from_teacher(
        self,
        query_vec: List[float],
        doc_vecs: List[List[float]],
        teacher_scores: List[float],  # From cross-encoder
        lr: float = 0.001,
    ):
        """Knowledge distillation from cross-encoder teacher."""
        # ... training loop implementation
        pass
```

---

## 7. Span Budgeting

Control how much text is returned to the LLM to avoid context overflow.

### 7.1 Token Budget Management

```python
from transformers import AutoTokenizer

class SpanBudgeter:
    def __init__(self, budget_tokens: int = 4096):
        self.budget = budget_tokens
        self.tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-base-en-v1.5")

    def select_spans(
        self,
        results: List[dict],
        max_spans: int = 24,
    ) -> List[dict]:
        """Select spans within token budget."""
        selected = []
        total_tokens = 0

        for result in results[:max_spans]:
            text = result["payload"]["text"]
            tokens = len(self.tokenizer.encode(text))

            if total_tokens + tokens > self.budget:
                # Try to include truncated
                remaining = self.budget - total_tokens
                if remaining > 50:  # Minimum useful length
                    truncated = self._truncate_to_tokens(text, remaining)
                    result["payload"]["text"] = truncated
                    selected.append(result)
                break

            selected.append(result)
            total_tokens += tokens

        return selected

    def _truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        tokens = self.tokenizer.encode(text)[:max_tokens]
        return self.tokenizer.decode(tokens)
```

### 7.2 Span Merging

Merge adjacent spans from the same file:

```python
def merge_adjacent_spans(results: List[dict], merge_distance: int = 5) -> List[dict]:
    """Merge spans that are close together in the same file."""
    # Group by file
    by_file = {}
    for r in results:
        path = r["payload"]["path"]
        if path not in by_file:
            by_file[path] = []
        by_file[path].append(r)

    merged = []
    for path, file_results in by_file.items():
        # Sort by start line
        file_results.sort(key=lambda x: x["payload"].get("start_line", 0))

        current = None
        for r in file_results:
            if current is None:
                current = r
            else:
                # Check if adjacent
                curr_end = current["payload"].get("end_line", 0)
                next_start = r["payload"].get("start_line", 0)

                if next_start - curr_end <= merge_distance:
                    # Merge
                    current["payload"]["end_line"] = r["payload"].get("end_line")
                    current["payload"]["text"] += "\n" + r["payload"]["text"]
                else:
                    merged.append(current)
                    current = r

        if current:
            merged.append(current)

    return merged
```

---

## 8. Decoder Integration

Use an LLM to generate answers based on retrieved context.

### 8.1 Basic Decoder Client

```python
import os
from typing import Optional, List

class DecoderClient:
    """Unified interface for LLM decoders."""

    def __init__(self):
        self.runtime = os.environ.get("REFRAG_RUNTIME", "llamacpp")

    def generate(
        self,
        prompt: str,
        context: List[dict],
        max_tokens: int = 256,
    ) -> str:
        """Generate answer from context."""
        # Format context
        context_text = self._format_context(context)

        full_prompt = f"""Based on the following code context, answer the question.

Context:
{context_text}

Question: {prompt}

Answer:"""

        if self.runtime == "llamacpp":
            return self._call_llamacpp(full_prompt, max_tokens)
        elif self.runtime == "openai":
            return self._call_openai(full_prompt, max_tokens)
        else:
            raise ValueError(f"Unknown runtime: {self.runtime}")

    def _format_context(self, context: List[dict]) -> str:
        parts = []
        for i, c in enumerate(context, 1):
            path = c["payload"]["path"]
            text = c["payload"]["text"]
            parts.append(f"[{i}] {path}:\n```\n{text}\n```")
        return "\n\n".join(parts)

    def _call_llamacpp(self, prompt: str, max_tokens: int) -> str:
        import urllib.request
        import json

        url = os.environ.get("LLAMACPP_URL", "http://localhost:8080")
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": 0.2,
        }

        req = urllib.request.Request(
            f"{url}/completion",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())

        return result.get("content", "").strip()
```

### 8.2 Phi Projection (Advanced - Infrastructure Only)

Context-Engine includes infrastructure for projecting embeddings into decoder space (like ReFRAG), but this requires a modified LLM:

```python
# Note: This is infrastructure for future use.
# Requires patched llama.cpp with /soft_completion endpoint.

def load_phi_matrix(path: str) -> List[List[float]]:
    """Load learned projection matrix."""
    import json
    with open(path) as f:
        return json.load(f)

def project_to_decoder_space(
    embeddings: List[List[float]],
    phi: List[List[float]],
) -> List[List[float]]:
    """Project chunk embeddings to LLM decoder space."""
    results = []
    for emb in embeddings:
        d_model = len(phi[0])
        out = [0.0] * d_model
        for i, val in enumerate(emb):
            for j in range(d_model):
                out[j] += val * phi[i][j]
        results.append(out)
    return results

# Usage (when supported):
# soft_embeddings = project_to_decoder_space(chunk_embeddings, phi)
# response = decoder.generate_with_soft_embeddings(prompt, soft_embeddings)
```

---

## 9. Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **Chunking** | | |
| `INDEX_MICRO_CHUNKS` | `0` | Enable token-based micro-chunking |
| `MICRO_CHUNK_TOKENS` | `16` | Tokens per micro-chunk |
| `MICRO_CHUNK_STRIDE` | `8` | Stride between chunks |
| `MAX_MICRO_CHUNKS_PER_FILE` | `200` | Cap chunks per file |
| **Vectors** | | |
| `REFRAG_MODE` | `0` | Enable mini vectors for gating |
| `MINI_VEC_DIM` | `64` | Mini vector dimensions |
| `LEX_VECTOR_DIM` | `4096` | Lexical vector dimensions |
| **Search** | | |
| `REFRAG_GATE_FIRST` | `0` | Enable two-stage gating |
| `REFRAG_CANDIDATES` | `200` | Candidates from gate stage |
| `RRF_K` | `60` | RRF constant |
| `DENSE_WEIGHT` | `0.7` | Dense search weight in RRF |
| `LEXICAL_WEIGHT` | `0.3` | Lexical search weight in RRF |
| **Decoder** | | |
| `REFRAG_DECODER` | `0` | Enable decoder features |
| `REFRAG_RUNTIME` | `llamacpp` | Decoder backend |
| `LLAMACPP_URL` | `http://localhost:8080` | llama.cpp server URL |

---

## Appendix: ReFRAG Comparison

### What Meta's ReFRAG Actually Does

ReFRAG (Meta AI, 2025) is a technique for **compressing retrieved context** before feeding to an LLM decoder:

1. **Chunk** retrieved documents into 16-token windows
2. **Compress** each chunk into a single embedding
3. **RL policy** decides which chunks to expand back to tokens
4. **Feed hybrid input** (embeddings + selective tokens) to decoder
5. **Modified decoder** processes both embeddings and tokens

### What Context-Engine Implements

| Feature | ReFRAG | Context-Engine |
|---------|--------|----------------|
| 16-token chunking | ✅ | ✅ |
| Compressed representations | ✅ Learned | ✅ Random projection |
| Fast gating | ✅ | ✅ (mini vectors) |
| RL selective expansion | ✅ | ❌ |
| Hybrid decoder input | ✅ | ❌ |
| Modified LLM required | ✅ | ❌ |

### Verdict

Context-Engine is **"ReFRAG-inspired"** in that it borrows:
- Small fixed-size chunking (16 tokens)
- Compressed vectors for fast gating (mini vectors)
- Span budgeting concepts

But it does **NOT** implement:
- The RL-based selective expansion
- Feeding embeddings directly to the decoder
- The core ReFRAG decoder architecture

The mini-vector gating is genuinely useful and provides ~10x speedup with minimal accuracy loss. The phi projection infrastructure exists but isn't connected to working code yet.

---

## References

- [Context-Engine GitHub](https://github.com/m1rl0k/Context-Engine)
- [REFRAG Paper (arXiv)](https://arxiv.org/pdf/2509.01092)
- [Johnson-Lindenstrauss Lemma](https://en.wikipedia.org/wiki/Johnson%E2%80%93Lindenstrauss_lemma)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [Sentence Transformers](https://www.sbert.net/)
