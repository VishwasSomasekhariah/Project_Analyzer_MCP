# Enterprise Codebase Indexing Guide

**Lessons from Augment Code's Context Engine**

This guide documents the architectural patterns and techniques used by Augment Code for indexing massive codebases (500k+ files), based on analysis of their public blog posts, documentation, and the [auggie-context-mcp](https://github.com/aj47/auggie-context-mcp) project.

---

## Table of Contents

- [Overview](#overview)
- [1. The Scale Challenge](#1-the-scale-challenge)
- [2. Quantized Vector Search (ANN)](#2-quantized-vector-search-ann)
- [3. Real-Time Index Updates](#3-real-time-index-updates)
- [4. Per-Developer Personalized Indexes](#4-per-developer-personalized-indexes)
- [5. Security: Proof of Possession](#5-security-proof-of-possession)
- [6. Embedding Strategy](#6-embedding-strategy)
- [7. Helpfulness Over Relevance](#7-helpfulness-over-relevance)
- [8. Implementation Patterns](#8-implementation-patterns)
- [9. What's Confirmed vs Unconfirmed](#9-whats-confirmed-vs-unconfirmed)
- [References](#references)

---

## Overview

Augment Code is a commercial AI coding assistant that claims to handle codebases with **500,000+ files** across multiple repositories. Their core technology is the **Context Engine**, which provides:

- Sub-second search across massive codebases
- Real-time index updates (seconds, not minutes)
- Per-developer personalized views
- Cross-repository understanding
- Security via hash verification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    AUGMENT CONTEXT ENGINE ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  Developer  │    │  Developer  │    │  Developer  │    │  Developer  │  │
│  │   Branch A  │    │   Branch B  │    │   Branch C  │    │   Main      │  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘  │
│         │                  │                  │                  │          │
│         └──────────────────┼──────────────────┼──────────────────┘          │
│                            ▼                                                 │
│                   ┌─────────────────┐                                       │
│                   │  Content Tracker │  ← Millisecond sync                  │
│                   │  (File Hashes)   │                                       │
│                   └────────┬────────┘                                       │
│                            │                                                 │
│              ┌─────────────┼─────────────┐                                  │
│              ▼             ▼             ▼                                  │
│      ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                       │
│      │  Quantized  │ │   Fresh     │ │  Stale      │                       │
│      │   Index     │ │  Embeddings │ │   Index     │                       │
│      │  (Fast ANN) │ │  (Precise)  │ │  (Fallback) │                       │
│      └──────┬──────┘ └──────┬──────┘ └──────┬──────┘                       │
│             │               │               │                               │
│             └───────────────┼───────────────┘                               │
│                             ▼                                               │
│                    ┌─────────────────┐                                      │
│                    │  Hybrid Search  │                                      │
│                    │  (Best of Both) │                                      │
│                    └─────────────────┘                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 1. The Scale Challenge

### The Problem

Traditional vector search is **O(n)** - you compare the query against every document:

```
Codebase: 500,000 files
Embedding dimension: 768
Comparisons per search: 500,000 × 768 = 384 million operations

At 1ns per operation: ~400ms per search
With multiple queries: Unacceptable latency
```

### Why Standard Solutions Fall Short

| Approach | Problem at Scale |
|----------|------------------|
| **Brute force** | O(n) - too slow |
| **Standard HNSW** | Memory explosion (768-dim × 500k) |
| **Reduce dimensions** | Loses accuracy |
| **Shard by repo** | Cross-repo queries fail |

### Augment's Insight

> "Entries that are closest to each other can be grouped for search, while entries far apart can be quickly ruled out."

This is the foundation of their **quantized ANN** approach.

---

## 2. Quantized Vector Search (ANN)

### The Core Technique

Transform full embeddings into compressed "neighborhood fingerprints":

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         QUANTIZATION PROCESS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Full Embedding (768 floats = 3KB):                                         │
│  [0.234, -0.891, 0.445, 0.112, -0.667, 0.823, ...]                          │
│                                                                              │
│                           ↓ Quantize                                         │
│                                                                              │
│  Bit Vector (768 bits = 96 bytes):                                          │
│  [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1, ...]                                  │
│                                                                              │
│  Compression: 32× smaller                                                    │
│  Speed: Hamming distance (XOR + popcount) vs dot product                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Two-Phase Search

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         TWO-PHASE SEARCH                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: FAST COARSE SEARCH (Quantized)                                    │
│  ────────────────────────────────────────                                   │
│                                                                              │
│  Query → Quantize → Search bit vectors                                      │
│                                                                              │
│  • Hamming distance: XOR + popcount (CPU optimized)                         │
│  • 32× less memory bandwidth                                                │
│  • Returns ~100-500 candidate IDs                                           │
│  • "Which neighborhoods might have what I need?"                            │
│                                                                              │
│  PHASE 2: PRECISE RERANKING (Full Embeddings)                               │
│  ────────────────────────────────────────────                               │
│                                                                              │
│  Query → Full similarity on candidates only                                 │
│                                                                              │
│  • Cosine similarity with full 768-dim vectors                              │
│  • Only ~100-500 comparisons (not 500k!)                                    │
│  • Returns final top-K results                                              │
│  • "Of these candidates, which are best?"                                   │
│                                                                              │
│  RESULT: 10-100× faster, 99.9% same quality                                 │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Quantization Approaches

| Method | Description | Trade-off |
|--------|-------------|-----------|
| **Binary** | Sign of each dimension (1 bit) | Fastest, lowest accuracy |
| **Scalar** | Uniform quantization (4-8 bits) | Balanced |
| **Product** | Codebook-based (PQ, OPQ) | Best accuracy, slower |
| **Learned** | Neural compression | Highest accuracy, training needed |

### Implementation Sketch

```python
import numpy as np

class BinaryQuantizer:
    """Simple sign-based binary quantization."""

    def quantize(self, vector: np.ndarray) -> np.ndarray:
        """Convert float vector to binary (sign-based)."""
        return np.packbits((vector > 0).astype(np.uint8))

    def hamming_distance(self, a: np.ndarray, b: np.ndarray) -> int:
        """Fast hamming distance using XOR + popcount."""
        xor = np.bitwise_xor(a, b)
        return np.unpackbits(xor).sum()

class ScalarQuantizer:
    """Scalar quantization to 8-bit integers."""

    def __init__(self):
        self.min_val = None
        self.max_val = None

    def fit(self, vectors: np.ndarray):
        """Learn quantization range from data."""
        self.min_val = vectors.min(axis=0)
        self.max_val = vectors.max(axis=0)

    def quantize(self, vector: np.ndarray) -> np.ndarray:
        """Quantize to uint8."""
        normalized = (vector - self.min_val) / (self.max_val - self.min_val + 1e-8)
        return (normalized * 255).astype(np.uint8)

    def dequantize(self, quantized: np.ndarray) -> np.ndarray:
        """Reconstruct approximate float vector."""
        normalized = quantized.astype(np.float32) / 255.0
        return normalized * (self.max_val - self.min_val) + self.min_val
```

### Product Quantization (Advanced)

```python
class ProductQuantizer:
    """Product quantization for better accuracy."""

    def __init__(self, n_subvectors: int = 8, n_centroids: int = 256):
        self.n_subvectors = n_subvectors  # Split vector into 8 parts
        self.n_centroids = n_centroids    # 256 centroids per subvector
        self.codebooks = None             # Shape: (8, 256, subvec_dim)

    def fit(self, vectors: np.ndarray):
        """Train codebooks using k-means on each subvector."""
        from sklearn.cluster import KMeans

        dim = vectors.shape[1]
        subvec_dim = dim // self.n_subvectors

        self.codebooks = []
        for i in range(self.n_subvectors):
            start = i * subvec_dim
            end = start + subvec_dim
            subvectors = vectors[:, start:end]

            kmeans = KMeans(n_clusters=self.n_centroids)
            kmeans.fit(subvectors)
            self.codebooks.append(kmeans.cluster_centers_)

    def quantize(self, vector: np.ndarray) -> np.ndarray:
        """Encode vector as sequence of centroid indices."""
        dim = len(vector)
        subvec_dim = dim // self.n_subvectors

        codes = []
        for i in range(self.n_subvectors):
            start = i * subvec_dim
            end = start + subvec_dim
            subvec = vector[start:end]

            # Find nearest centroid
            distances = np.linalg.norm(self.codebooks[i] - subvec, axis=1)
            codes.append(np.argmin(distances))

        return np.array(codes, dtype=np.uint8)  # 8 bytes instead of 3KB!
```

---

## 3. Real-Time Index Updates

### The Challenge

Codebases change constantly. Traditional approaches:

```
Traditional:
  Code change → Re-embed → Rebuild index → Available
  Latency: Minutes to hours

  Problem: Recently changed code (often most important) is stale
```

### Augment's Hybrid Approach

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    HYBRID FRESH/STALE INDEXING                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Content Tracking System                                                     │
│  ───────────────────────                                                    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  File: src/auth.py                                                   │   │
│  │  Hash: a3f8b2c1...                                                   │   │
│  │  Last Modified: 2024-01-15 10:32:45                                  │   │
│  │  Index State: QUANTIZED (in fast index)                              │   │
│  ├─────────────────────────────────────────────────────────────────────┤   │
│  │  File: src/auth.py (MODIFIED)                                        │   │
│  │  Hash: b7e2d4f9...                                                   │   │
│  │  Last Modified: 2024-01-15 14:21:03                                  │   │
│  │  Index State: FRESH_ONLY (not yet quantized)                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Search Strategy                                                             │
│  ───────────────                                                            │
│                                                                              │
│  1. Check content tracker for current file hashes                           │
│  2. For files IN quantized index: Use fast ANN search                       │
│  3. For FRESH files (changed): Use full embedding similarity                │
│  4. Merge results, prioritize fresh files                                   │
│                                                                              │
│  Background Process                                                          │
│  ──────────────────                                                         │
│                                                                              │
│  • Continuously rebuilds quantized index                                    │
│  • Old index remains valid while new one builds                             │
│  • Atomic swap when ready                                                   │
│  • Zero downtime, always searchable                                         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Pattern

```python
from dataclasses import dataclass
from typing import Dict, Set, List
import hashlib
import time

@dataclass
class FileState:
    path: str
    content_hash: str
    embedding: List[float]
    last_modified: float
    in_quantized_index: bool

class HybridIndex:
    """Hybrid index with fresh and quantized layers."""

    def __init__(self):
        self.content_tracker: Dict[str, FileState] = {}
        self.quantized_index = QuantizedIndex()  # Fast ANN
        self.fresh_embeddings: Dict[str, List[float]] = {}  # Recently changed
        self.quantized_hashes: Set[str] = set()  # Hashes in quantized index

    def update_file(self, path: str, content: str, embedding: List[float]):
        """Update file in index (real-time)."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # Always store fresh embedding immediately
        self.fresh_embeddings[path] = embedding

        # Update content tracker
        self.content_tracker[path] = FileState(
            path=path,
            content_hash=content_hash,
            embedding=embedding,
            last_modified=time.time(),
            in_quantized_index=content_hash in self.quantized_hashes,
        )

    def search(self, query_embedding: List[float], limit: int = 10) -> List[dict]:
        """Hybrid search across fresh and quantized indexes."""

        # Identify which files need fresh search
        fresh_paths = set()
        quantized_paths = set()

        for path, state in self.content_tracker.items():
            if state.in_quantized_index and state.content_hash in self.quantized_hashes:
                quantized_paths.add(path)
            else:
                fresh_paths.add(path)

        results = []

        # Search quantized index (fast)
        if quantized_paths:
            quantized_results = self.quantized_index.search(
                query_embedding,
                limit=limit * 2,
                filter_paths=quantized_paths,
            )
            results.extend(quantized_results)

        # Search fresh embeddings (precise)
        if fresh_paths:
            for path in fresh_paths:
                if path in self.fresh_embeddings:
                    score = cosine_similarity(query_embedding, self.fresh_embeddings[path])
                    results.append({"path": path, "score": score, "fresh": True})

        # Merge and sort
        results.sort(key=lambda x: x["score"], reverse=True)

        return results[:limit]

    def rebuild_quantized_index(self):
        """Background job to rebuild quantized index."""
        # Collect all current embeddings
        all_embeddings = []
        all_paths = []
        all_hashes = []

        for path, state in self.content_tracker.items():
            all_embeddings.append(state.embedding)
            all_paths.append(path)
            all_hashes.append(state.content_hash)

        # Build new quantized index
        new_index = QuantizedIndex()
        new_index.build(all_embeddings, all_paths)

        # Atomic swap
        self.quantized_index = new_index
        self.quantized_hashes = set(all_hashes)

        # Update tracker
        for path, state in self.content_tracker.items():
            state.in_quantized_index = True

        # Clear fresh cache for quantized files
        self.fresh_embeddings.clear()
```

### Graceful Degradation

```python
class ResilientSearch:
    """Search that gracefully degrades when index is unavailable."""

    def search(self, query_embedding: List[float], limit: int = 10) -> List[dict]:
        """Search with fallback strategies."""

        # Try quantized index first (fastest)
        try:
            if self.quantized_index.is_ready():
                return self._hybrid_search(query_embedding, limit)
        except Exception:
            pass

        # Fallback to stale quantized index
        try:
            if self.stale_quantized_index is not None:
                results = self.stale_quantized_index.search(query_embedding, limit * 2)
                # Supplement with fresh embeddings
                return self._merge_with_fresh(results, query_embedding, limit)
        except Exception:
            pass

        # Final fallback: brute force on fresh embeddings
        return self._brute_force_search(query_embedding, limit)
```

---

## 4. Per-Developer Personalized Indexes

### The Concept

Different developers see different views of the codebase:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PER-DEVELOPER INDEX VIEWS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Shared Base Index (main branch)                                            │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Quantized embeddings for all files in main                          │   │
│  │  ~500,000 files, stable, rebuilt nightly                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Developer A (feature/auth-refactor)                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Base: main                                                          │   │
│  │  Modified: src/auth/*.py (15 files)                                  │   │
│  │  Added: src/auth/oauth2.py                                           │   │
│  │  Deleted: src/auth/legacy.py                                         │   │
│  │                                                                       │   │
│  │  Search View: Base index + overlay of modified files                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Developer B (bugfix/payment-edge-case)                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Base: main                                                          │   │
│  │  Modified: src/payments/processor.py (1 file)                        │   │
│  │                                                                       │   │
│  │  Search View: Base index + overlay of 1 modified file                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Pattern

```python
from dataclasses import dataclass, field
from typing import Dict, Set, Optional
import time

@dataclass
class DeveloperView:
    """Per-developer overlay on shared index."""
    developer_id: str
    base_branch: str
    current_branch: str

    # Overlay data
    modified_files: Dict[str, List[float]] = field(default_factory=dict)
    added_files: Dict[str, List[float]] = field(default_factory=dict)
    deleted_files: Set[str] = field(default_factory=set)

    # Metadata
    last_sync: float = 0
    local_changes: Dict[str, str] = field(default_factory=dict)  # path -> hash

class PersonalizedIndexManager:
    """Manages per-developer index views."""

    def __init__(self, shared_index: SharedIndex):
        self.shared_index = shared_index
        self.developer_views: Dict[str, DeveloperView] = {}

    def get_or_create_view(self, developer_id: str, branch: str) -> DeveloperView:
        """Get or create developer's personalized view."""
        key = f"{developer_id}:{branch}"

        if key not in self.developer_views:
            self.developer_views[key] = DeveloperView(
                developer_id=developer_id,
                base_branch="main",
                current_branch=branch,
            )

        return self.developer_views[key]

    def sync_local_changes(
        self,
        developer_id: str,
        branch: str,
        changes: Dict[str, tuple]  # path -> (content, embedding)
    ):
        """Sync developer's local changes to their view."""
        view = self.get_or_create_view(developer_id, branch)

        for path, (content, embedding) in changes.items():
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # Check if file exists in shared index
            if self.shared_index.has_file(path):
                view.modified_files[path] = embedding
            else:
                view.added_files[path] = embedding

            view.local_changes[path] = content_hash

        view.last_sync = time.time()

    def search_for_developer(
        self,
        developer_id: str,
        branch: str,
        query_embedding: List[float],
        limit: int = 10,
    ) -> List[dict]:
        """Search with developer's personalized view."""
        view = self.get_or_create_view(developer_id, branch)

        # Search shared index, excluding deleted/modified files
        excluded_paths = view.deleted_files | set(view.modified_files.keys())

        shared_results = self.shared_index.search(
            query_embedding,
            limit=limit * 2,
            exclude_paths=excluded_paths,
        )

        # Search overlay (modified + added files)
        overlay_results = []

        for path, embedding in {**view.modified_files, **view.added_files}.items():
            score = cosine_similarity(query_embedding, embedding)
            overlay_results.append({
                "path": path,
                "score": score,
                "source": "local",
            })

        # Merge results
        all_results = shared_results + overlay_results
        all_results.sort(key=lambda x: x["score"], reverse=True)

        return all_results[:limit]
```

---

## 5. Security: Proof of Possession

### The Problem

In multi-repo environments, developers shouldn't see code they don't have access to.

Traditional approach:
```
Developer A searches → Server returns results from ALL repos
Problem: A might see snippets from repos they can't access
```

### Augment's Solution: Hash Verification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PROOF OF POSSESSION SECURITY                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Step 1: Client sends file hashes (not content)                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Client → Server:                                                    │   │
│  │  {                                                                   │   │
│  │    "query": "authentication flow",                                   │   │
│  │    "known_hashes": [                                                 │   │
│  │      "a3f8b2c1...",  // src/auth.py                                 │   │
│  │      "b7e2d4f9...",  // src/users.py                                │   │
│  │      "c9d1e5a2...",  // src/login.py                                │   │
│  │      ...                                                             │   │
│  │    ]                                                                 │   │
│  │  }                                                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Step 2: Server filters results by hash match                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Server logic:                                                       │   │
│  │                                                                       │   │
│  │  results = search(query)                                             │   │
│  │  filtered = []                                                       │   │
│  │                                                                       │   │
│  │  for result in results:                                              │   │
│  │      if result.hash in client_known_hashes:                          │   │
│  │          filtered.append(result)  # Client has this file            │   │
│  │      else:                                                           │   │
│  │          skip  # Don't reveal files client doesn't have             │   │
│  │                                                                       │   │
│  │  return filtered                                                     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  Key Insight: Hash proves possession without transmitting content           │
│                                                                              │
│  • Client computed hash → Client has the file                               │
│  • Can't guess hashes → Can't access files you don't have                   │
│  • Server never sends content → Only confirms what client already has       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Implementation Pattern

```python
import hashlib
from typing import Set, List

class SecureSearchServer:
    """Server-side search with proof of possession."""

    def __init__(self, index: VectorIndex):
        self.index = index

    def search(
        self,
        query_embedding: List[float],
        client_hashes: Set[str],
        limit: int = 10,
    ) -> List[dict]:
        """Search with hash-based access control."""

        # Get more results than needed (some will be filtered)
        raw_results = self.index.search(query_embedding, limit=limit * 5)

        # Filter to only files client can prove possession of
        accessible_results = []

        for result in raw_results:
            file_hash = result.get("content_hash")

            if file_hash in client_hashes:
                # Client has this file - include in results
                accessible_results.append(result)
            # else: Client doesn't have file - exclude silently

        return accessible_results[:limit]

class SecureSearchClient:
    """Client-side search with hash generation."""

    def __init__(self, workspace_path: str):
        self.workspace = workspace_path
        self.file_hashes = self._compute_workspace_hashes()

    def _compute_workspace_hashes(self) -> Set[str]:
        """Compute hashes of all files in workspace."""
        hashes = set()

        for path in walk_files(self.workspace):
            content = read_file(path)
            file_hash = hashlib.sha256(content.encode()).hexdigest()
            hashes.add(file_hash)

        return hashes

    def search(self, query: str) -> List[dict]:
        """Search with proof of possession."""
        query_embedding = self.embed(query)

        # Send query + hashes to server
        response = self.server.search(
            query_embedding=query_embedding,
            client_hashes=self.file_hashes,
            limit=10,
        )

        return response
```

---

## 6. Embedding Strategy

### What We Know (Confirmed)

| Aspect | Details |
|--------|---------|
| **Custom training** | They mention "research-driven embeddings" |
| **Paired training** | Embedding + retrieval trained together |
| **Code-specific** | Optimized for code, not general text |

### What's Unconfirmed

| Claim | Status |
|-------|--------|
| **Fully custom model** | Unverified - could be fine-tuned |
| **Architecture details** | Not disclosed |
| **Training data** | Not disclosed |

### Recommended Approach

Since Augment's embedding model is proprietary, use available code-specific models:

| Model | Provider | Quality | Notes |
|-------|----------|---------|-------|
| `BAAI/bge-base-en-v1.5` | Open | Good | General purpose, solid baseline |
| `voyage-code-3` | Voyage AI | Better | Code-specific, API-based |
| `Qodo-Embed-1` | Qodo | Better | Code-specific, open-source |
| `CodeSage` | Microsoft | Good | Code-specific |

### Fine-Tuning for Your Codebase

```python
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader

def fine_tune_for_codebase(
    base_model: str = "BAAI/bge-base-en-v1.5",
    training_pairs: List[tuple],  # (query, relevant_code)
):
    """Fine-tune embedding model on your codebase."""

    model = SentenceTransformer(base_model)

    # Prepare training data
    train_examples = [
        InputExample(texts=[query, code], label=1.0)
        for query, code in training_pairs
    ]

    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=16)

    # Use contrastive loss
    train_loss = losses.CosineSimilarityLoss(model)

    # Fine-tune
    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=3,
        warmup_steps=100,
    )

    return model
```

---

## 7. Helpfulness Over Relevance

### The Insight

> Augment prioritizes **"helpfulness over relevance"**

```
Query: "how does authentication work"

Relevant (but not helpful):
  • test_auth.py - mentions "authentication" 50 times
  • auth_types.d.ts - type definitions
  • README.md - documentation about auth

Helpful:
  • auth_service.py - actual authentication logic
  • login_handler.py - implements the flow
  • session_manager.py - manages user sessions
```

### Implementing Helpfulness

```python
class HelpfulnessScorer:
    """Score results by helpfulness, not just relevance."""

    def __init__(self):
        self.file_patterns = {
            # Boost helpful patterns
            "implementation": 1.5,    # *_service.py, *_handler.py
            "core_logic": 1.4,        # Non-test, non-type files

            # Penalize less helpful patterns
            "test_file": 0.6,         # test_*.py, *_test.py
            "type_definitions": 0.7,  # *.d.ts, types.py
            "generated": 0.3,         # *.generated.*, *_pb2.py
            "vendor": 0.4,            # vendor/*, node_modules/*
            "documentation": 0.8,     # *.md, docs/*
        }

    def score(self, result: dict) -> float:
        """Adjust relevance score by helpfulness."""
        path = result["path"]
        base_score = result["score"]

        multiplier = 1.0

        # Apply pattern-based adjustments
        if self._is_test_file(path):
            multiplier *= self.file_patterns["test_file"]

        if self._is_type_definition(path):
            multiplier *= self.file_patterns["type_definitions"]

        if self._is_implementation(path):
            multiplier *= self.file_patterns["implementation"]

        if self._is_vendor(path):
            multiplier *= self.file_patterns["vendor"]

        return base_score * multiplier

    def _is_test_file(self, path: str) -> bool:
        return "test" in path.lower() or path.endswith("_test.py")

    def _is_type_definition(self, path: str) -> bool:
        return path.endswith(".d.ts") or "types" in path.lower()

    def _is_implementation(self, path: str) -> bool:
        indicators = ["service", "handler", "controller", "manager", "processor"]
        return any(ind in path.lower() for ind in indicators)

    def _is_vendor(self, path: str) -> bool:
        vendors = ["vendor/", "node_modules/", "third_party/", ".venv/"]
        return any(v in path for v in vendors)

def search_with_helpfulness(
    query: str,
    index: VectorIndex,
    scorer: HelpfulnessScorer,
    limit: int = 10,
) -> List[dict]:
    """Search with helpfulness-adjusted ranking."""

    # Get more results than needed
    raw_results = index.search(query, limit=limit * 3)

    # Adjust scores by helpfulness
    for result in raw_results:
        result["helpfulness_score"] = scorer.score(result)

    # Re-rank by helpfulness
    raw_results.sort(key=lambda x: x["helpfulness_score"], reverse=True)

    return raw_results[:limit]
```

---

## 8. Implementation Patterns

### Complete Search Pipeline

```python
class EnterpriseCodeSearch:
    """Enterprise-scale code search following Augment patterns."""

    def __init__(self):
        # Core components
        self.embedder = SentenceTransformer("BAAI/bge-base-en-v1.5")
        self.quantizer = ProductQuantizer(n_subvectors=8, n_centroids=256)

        # Index layers
        self.quantized_index = QuantizedIndex()
        self.fresh_embeddings = {}
        self.content_tracker = ContentTracker()

        # Personalization
        self.developer_views = {}

        # Scoring
        self.helpfulness_scorer = HelpfulnessScorer()
        self.reranker = CrossEncoderReranker()

    def index_file(self, path: str, content: str, developer_id: str = None):
        """Index a file with real-time update."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        embedding = self.embedder.encode(content)

        # Update content tracker
        self.content_tracker.update(path, content_hash, embedding)

        # Store in fresh layer (immediate availability)
        self.fresh_embeddings[path] = embedding

        # Update developer view if specified
        if developer_id:
            view = self.developer_views.get(developer_id)
            if view:
                view.modified_files[path] = embedding

    def search(
        self,
        query: str,
        developer_id: str,
        client_hashes: Set[str],
        limit: int = 10,
    ) -> List[dict]:
        """Full search pipeline."""

        query_embedding = self.embedder.encode(query)

        # 1. Two-phase quantized search
        quantized_results = self._quantized_search(query_embedding, limit * 3)

        # 2. Fresh file search
        fresh_results = self._fresh_search(query_embedding, limit * 2)

        # 3. Developer overlay
        if developer_id in self.developer_views:
            overlay_results = self._overlay_search(
                developer_id, query_embedding, limit
            )
        else:
            overlay_results = []

        # 4. Merge all results
        all_results = self._merge_results(
            quantized_results, fresh_results, overlay_results
        )

        # 5. Security filter (proof of possession)
        accessible_results = [
            r for r in all_results
            if r["content_hash"] in client_hashes
        ]

        # 6. Helpfulness adjustment
        for result in accessible_results:
            result["final_score"] = self.helpfulness_scorer.score(result)

        accessible_results.sort(key=lambda x: x["final_score"], reverse=True)

        # 7. Rerank top candidates
        top_candidates = accessible_results[:limit * 2]
        reranked = self.reranker.rerank(query, top_candidates, limit)

        return reranked
```

---

## 9. What's Confirmed vs Unconfirmed

### Confirmed (From Public Sources)

| Feature | Source |
|---------|--------|
| Quantized ANN search | Blog post on vector search |
| Real-time index updates | Blog post on real-time indexing |
| Proof of possession security | Blog post on security model |
| 500k+ file scale | Marketing + case studies |
| Custom code completion model | RLDB blog post |

### Unconfirmed / Marketing Claims

| Claim | Status |
|-------|--------|
| "Custom embedding model" | Only appears in marketing copy |
| "Trained in pairs" | No technical details |
| Which embedding model | Never specified |
| Embedding architecture | Not disclosed |
| Training methodology | Not disclosed |

### Likely Implementation

Based on industry patterns:

```
Most likely:
├── Fine-tuned open-source embedding (e.g., CodeBERT family)
├── Custom retrieval/ranking layer (confirmed)
├── Standard quantization (PQ or ScaNN)
└── Custom integration infrastructure

Less likely:
├── Fully custom embedding trained from scratch
└── Novel embedding architecture
```

---

## References

### Augment Sources
- [Context Engine Overview](https://www.augmentcode.com/context-engine)
- [Quantized Vector Search Blog](https://www.augmentcode.com/blog/repo-scale-100M-line-codebase-quantized-vector-search)
- [Real-Time Index Blog](https://www.augmentcode.com/blog/a-real-time-index-for-your-codebase-secure-personal-scalable)
- [RLDB Training Blog](https://www.augmentcode.com/blog/reinforcement-learning-from-developer-behaviors)
- [Available Models Documentation](https://docs.augmentcode.com/models/available-models)

### Technical References
- [Product Quantization for ANN](https://ieeexplore.ieee.org/document/5432202)
- [ScaNN: Efficient Vector Search](https://github.com/google-research/google-research/tree/master/scann)
- [FAISS Library](https://github.com/facebookresearch/faiss)
- [Qdrant Quantization](https://qdrant.tech/documentation/guides/quantization/)

### Related Projects
- [auggie-context-mcp](https://github.com/aj47/auggie-context-mcp) - MCP wrapper for Augment CLI
- [Context-Engine](https://github.com/m1rl0k/Context-Engine) - Open-source alternative
