"""
Hybrid Vector Retriever

Wraps an MCP-connected vector database (Qdrant) with post-retrieval BM25 scoring
and Reciprocal Rank Fusion (RRF) reranking.

Design:
    1. Fetch vector_size = top_k * 5 results via qdrant-find (MCP tool)
    2. Parse <entry><content>...</content><metadata>...</metadata></entry> XML format
    3. Apply BM25 scoring on extracted content against the query
    4. Apply RRF(k=60) to combine vector rank + BM25 rank
    5. Return top_k reranked results as plain dicts

This is intentionally database-agnostic at the BM25/RRF layer — any MCP tool that
returns the same entry XML format can be used. Ported from the post-vector BM25
approach used in codebase_rag HybridLlamaIndexQueryService.
"""
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# BM25 parameters (literature defaults)
_BM25_K1 = 1.2
_BM25_B = 0.75
_BM25_MIN_SCORE = 0.1

# RRF constant (standard from literature; Google uses variants)
_RRF_K = 60


@dataclass
class VectorEntry:
    chunk_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    vector_rank: int = 0
    bm25_score: float = 0.0


def _parse_entry_xml(raw: str) -> Optional[VectorEntry]:
    """Parse one <entry>...</entry> string returned by qdrant-find."""
    content_match = re.search(r"<content>(.*?)</content>", raw, re.DOTALL)
    metadata_match = re.search(r"<metadata>(.*?)</metadata>", raw, re.DOTALL)

    content = content_match.group(1).strip() if content_match else raw.strip()
    metadata: Dict[str, Any] = {}

    if metadata_match:
        try:
            metadata = json.loads(metadata_match.group(1).strip())
            # Qdrant MCP nests metadata under a "metadata" key
            if "metadata" in metadata and isinstance(metadata["metadata"], dict):
                metadata = {**metadata, **metadata["metadata"]}
        except json.JSONDecodeError:
            pass

    chunk_id = (
        metadata.get("chunk_id")
        or metadata.get("id")
        or metadata.get("file_path", "")
        + f":{metadata.get('start_line', 0)}-{metadata.get('end_line', 0)}"
    )

    return VectorEntry(chunk_id=chunk_id, content=content, metadata=metadata)


def _parse_qdrant_response(raw_list: List[str]) -> List[VectorEntry]:
    """
    Convert raw qdrant-find response (list[str]) into VectorEntry objects.
    The first element is a human-readable summary string — skip it.
    Entries whose chunk_id starts with __ are internal metadata — skip those too.
    """
    entries = []
    for item in raw_list:
        if not isinstance(item, str):
            continue
        if item.startswith("<entry>"):
            entry = _parse_entry_xml(item)
            if entry and not entry.chunk_id.startswith("__"):
                entries.append(entry)
    return entries


def _calculate_bm25_scores(query: str, documents: List[str]) -> List[float]:
    """BM25 scoring — ported directly from codebase_rag HybridLlamaIndexQueryService."""
    if not documents:
        return []

    query_terms = query.lower().split()
    doc_terms_list = [doc.lower().split() for doc in documents]
    avg_doc_length = sum(len(d) for d in doc_terms_list) / len(doc_terms_list)

    # IDF per term
    total_docs = len(documents)
    idf: Dict[str, float] = {}
    for term in set(t for d in doc_terms_list for t in d):
        df = sum(1 for d in doc_terms_list if term in d)
        idf[term] = math.log((total_docs - df + 0.5) / (df + 0.5))

    scores = []
    for doc_terms in doc_terms_list:
        tf_map = Counter(doc_terms)
        doc_len = len(doc_terms)
        score = 0.0
        for term in query_terms:
            if term in tf_map:
                tf = tf_map[term]
                numerator = tf * (_BM25_K1 + 1)
                denominator = tf + _BM25_K1 * (1 - _BM25_B + _BM25_B * (doc_len / avg_doc_length))
                score += idf.get(term, 0.0) * (numerator / denominator)
        scores.append(max(0.0, score))

    return scores


def _rrf_rerank(entries: List[VectorEntry], top_k: int) -> List[VectorEntry]:
    """
    Reciprocal Rank Fusion — combines vector rank with BM25 rank.
    score(d) = 1/(k + vector_rank) + 1/(k + bm25_rank)
    """
    # Sort by BM25 score to get BM25 ranks
    bm25_ranked = sorted(
        [e for e in entries if e.bm25_score > _BM25_MIN_SCORE],
        key=lambda e: e.bm25_score,
        reverse=True,
    )
    bm25_rank_map = {e.chunk_id: rank for rank, e in enumerate(bm25_ranked)}

    rrf_scores: Dict[str, float] = {}
    for entry in entries:
        vector_contribution = 1.0 / (_RRF_K + entry.vector_rank + 1)
        bm25_rank = bm25_rank_map.get(entry.chunk_id)
        bm25_contribution = 1.0 / (_RRF_K + bm25_rank + 1) if bm25_rank is not None else 0.0
        rrf_scores[entry.chunk_id] = vector_contribution + bm25_contribution

    reranked = sorted(entries, key=lambda e: rrf_scores.get(e.chunk_id, 0.0), reverse=True)
    return reranked[:top_k]


class HybridVectorRetriever:
    """
    Hybrid vector retriever for any MCP-connected Qdrant collection.

    Usage:
        retriever = HybridVectorRetriever(session, collection_name)
        results = await retriever.search(query, top_k=5)
        # results: list of dicts with "content", "metadata", "score" keys
    """

    def __init__(self, session: Any, collection_name: str, top_k_multiplier: int = 5):
        self._session = session
        self._collection_name = collection_name
        self._top_k_multiplier = top_k_multiplier

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Perform hybrid vector + BM25 search with RRF reranking.

        Returns a list of dicts: {content, metadata, score, chunk_id}
        """
        fetch_size = min(top_k * self._top_k_multiplier, 200)
        logger.info(f"[HybridVectorRetriever] fetching {fetch_size} via qdrant-find for BM25 reranking")

        raw = await self._session.call_tool("qdrant-find", {
            "query": query,
            "collection_name": self._collection_name,
        })

        content = raw.content[0] if isinstance(raw.content, list) else raw.content
        text = content.text if hasattr(content, "text") else str(content)

        try:
            raw_list = json.loads(text)
        except json.JSONDecodeError:
            raw_list = [text]

        entries = _parse_qdrant_response(raw_list if isinstance(raw_list, list) else [raw_list])

        if not entries:
            logger.warning("[HybridVectorRetriever] no entries parsed from qdrant-find response")
            return []

        # Assign vector ranks
        for rank, entry in enumerate(entries):
            entry.vector_rank = rank

        # BM25 scoring
        documents = [e.content for e in entries]
        bm25_scores = _calculate_bm25_scores(query, documents)
        for entry, score in zip(entries, bm25_scores):
            entry.bm25_score = score

        logger.info(f"[HybridVectorRetriever] BM25 scored {len(entries)} docs, reranking with RRF")

        reranked = _rrf_rerank(entries, top_k)

        return [
            {
                "content": e.content,
                "metadata": e.metadata,
                "chunk_id": e.chunk_id,
            }
            for e in reranked
        ]
