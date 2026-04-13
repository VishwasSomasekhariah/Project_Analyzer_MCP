#!/usr/bin/env python3
"""
Compare extraction methods: Embeddings vs BM25 vs Hybrid.
Tests all 4 subqueries with each approach.
"""
import asyncio
import yaml
import sys
import time
import re
from typing import List, Dict, Tuple
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager, get_embedding_model
import numpy as np


class BM25Scorer:
    """Simple BM25 implementation for type extraction."""

    def __init__(self, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.corpus = []
        self.doc_lens = []
        self.avgdl = 0
        self.doc_freqs = {}
        self.idf = {}
        self.N = 0

    def fit(self, corpus: List[str]):
        """Build BM25 index from corpus."""
        self.corpus = corpus
        self.N = len(corpus)

        # Tokenize and compute document lengths
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        self.doc_lens = [len(tokens) for tokens in tokenized_corpus]
        self.avgdl = sum(self.doc_lens) / self.N if self.N > 0 else 0

        # Compute document frequencies
        for tokens in tokenized_corpus:
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        # Compute IDF scores
        for token, freq in self.doc_freqs.items():
            self.idf[token] = np.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text: lowercase + split on non-alphanumeric."""
        text = text.lower()
        # Split on non-alphanumeric, keep underscore
        tokens = re.findall(r'[a-z0-9_]+', text)
        return tokens

    def score(self, query: str) -> np.ndarray:
        """Compute BM25 scores for query against all documents."""
        query_tokens = self._tokenize(query)
        scores = np.zeros(self.N)

        for i, doc in enumerate(self.corpus):
            doc_tokens = self._tokenize(doc)
            doc_len = len(doc_tokens)

            # Count term frequencies in document
            term_freqs = {}
            for token in doc_tokens:
                term_freqs[token] = term_freqs.get(token, 0) + 1

            # Compute BM25 score
            score = 0.0
            for token in query_tokens:
                if token in term_freqs:
                    tf = term_freqs[token]
                    idf = self.idf.get(token, 0)

                    # BM25 formula
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                    score += idf * (numerator / denominator)

            scores[i] = score

        # Normalize to 0-1 range for comparability with embeddings
        if scores.max() > 0:
            scores = scores / scores.max()

        return scores


def extract_with_method(
    query_text: str,
    type_names: List[Tuple[str, str]],
    descriptions: List[str],
    method: str,
    bm25_scorer: BM25Scorer = None,
    embeddings: np.ndarray = None,
    embedding_model = None,
    threshold: float = 0.3,
    top_k: int = 5,
    alpha: float = 0.5
) -> Dict:
    """
    Extract types using specified method.

    Args:
        method: 'embeddings', 'bm25', or 'hybrid'
        alpha: Weight for hybrid (alpha*bm25 + (1-alpha)*embeddings)
    """
    start_time = time.time()

    if method == 'bm25':
        # Pure BM25 (already normalized to [0, 1] by dividing by max in score())
        scores = bm25_scorer.score(query_text)

    elif method == 'embeddings':
        # Pure embeddings (dot product)
        query_embedding = embedding_model.encode([query_text], convert_to_numpy=True)[0]
        raw_scores = np.dot(embeddings, query_embedding)

        # Normalize: dot product of unit vectors gives cosine similarity in [-1, 1]
        # Map to [0, 1]: (x + 1) / 2
        # However, for semantic text similarity, scores are typically positive [0, 1]
        # To be safe and consistent, we normalize to [0, 1] range
        scores = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min() + 1e-10)

    elif method == 'hybrid':
        # Hybrid: weighted combination with proper normalization
        bm25_scores = bm25_scorer.score(query_text)

        query_embedding = embedding_model.encode([query_text], convert_to_numpy=True)[0]
        embedding_raw = np.dot(embeddings, query_embedding)

        # Normalize both to [0, 1] using min-max normalization
        # BM25 is already in [0, 1] from score() method
        bm25_normalized = bm25_scores

        # Embeddings: normalize to [0, 1]
        embedding_min = embedding_raw.min()
        embedding_max = embedding_raw.max()
        embedding_normalized = (embedding_raw - embedding_min) / (embedding_max - embedding_min + 1e-10)

        # Combine with alpha weighting
        scores = alpha * bm25_normalized + (1 - alpha) * embedding_normalized

    else:
        raise ValueError(f"Unknown method: {method}")

    # Extract matches above threshold
    matches = []
    for idx, score in enumerate(scores):
        if score >= threshold:
            category, type_name = type_names[idx]
            matches.append((type_name, category, score))

    matches.sort(key=lambda x: x[2], reverse=True)

    # Split by category and apply top_k
    node_types = []
    rel_types = []

    for type_name, category, score in matches:
        if category == 'node' and len(node_types) < top_k:
            if type_name not in node_types:
                node_types.append(type_name)
        elif category == 'rel' and len(rel_types) < top_k:
            if type_name not in rel_types:
                rel_types.append(type_name)

    elapsed_ms = (time.time() - start_time) * 1000

    return {
        'node_types': node_types,
        'relationship_types': rel_types,
        'time_ms': elapsed_ms,
        'scores': scores,
        'matches': matches
    }


async def main():
    print("=" * 80)
    print("HYBRID EXTRACTION COMPARISON")
    print("Embeddings vs BM25 vs Hybrid (α=0.5)")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")

    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_hybrid_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing schema manager...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    # Get embedding data
    model = get_embedding_model()
    embeddings = schema_manager._type_embeddings['embeddings']
    type_names = schema_manager._type_embeddings['type_names']
    descriptions = schema_manager._type_embeddings['descriptions']

    # Initialize BM25 with type descriptions
    print("📊 Building BM25 index...")
    bm25 = BM25Scorer(k1=1.5, b=0.75)
    bm25.fit(descriptions)
    print(f"✅ BM25 index built for {len(descriptions)} types\n")

    # Test subqueries
    subqueries = [
        {
            "id": "SQ1",
            "text": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'"
        },
        {
            "id": "SQ2",
            "text": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name"
        },
        {
            "id": "SQ3",
            "text": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name"
        },
        {
            "id": "SQ4",
            "text": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name"
        }
    ]

    methods = [
        ('embeddings', 0.0),  # 0% BM25, 100% embeddings
        ('bm25', 1.0),        # 100% BM25, 0% embeddings
        ('hybrid', 0.5),      # 50% BM25, 50% embeddings
        ('hybrid', 0.7),      # 70% BM25, 30% embeddings
        ('hybrid', 0.3),      # 30% BM25, 70% embeddings
    ]

    all_results = []

    for subquery in subqueries:
        print("=" * 80)
        print(f"{subquery['id']}: {subquery['text'][:60]}...")
        print("=" * 80)
        print()

        results_for_query = []

        for method_name, alpha in methods:
            display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"

            result = extract_with_method(
                query_text=subquery['text'],
                type_names=type_names,
                descriptions=descriptions,
                method=method_name,
                bm25_scorer=bm25,
                embeddings=embeddings,
                embedding_model=model,
                threshold=0.3,
                top_k=5,
                alpha=alpha
            )

            results_for_query.append({
                'method': display_name,
                'result': result
            })

        # Display comparison table
        print(f"{'Method':<20} {'Nodes':<6} {'Rels':<6} {'Time (ms)':<10}")
        print("-" * 80)

        for r in results_for_query:
            method = r['method']
            res = r['result']
            node_count = len(res['node_types'])
            rel_count = len(res['relationship_types'])
            time_ms = res['time_ms']

            print(f"{method:<20} {node_count:<6} {rel_count:<6} {time_ms:<10.2f}")

        print()

        # Show detailed extraction for each method
        for r in results_for_query:
            method = r['method']
            res = r['result']

            print(f"── {method} ──")
            print(f"   Nodes: {res['node_types']}")
            print(f"   Rels:  {res['relationship_types']}")
            print()

        all_results.append({
            'subquery': subquery,
            'results': results_for_query
        })

    # Summary comparison
    print("=" * 80)
    print("PERFORMANCE SUMMARY")
    print("=" * 80)
    print()

    # Average extraction counts
    method_stats = {}
    for method_name, alpha in methods:
        display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"
        method_stats[display_name] = {
            'total_nodes': 0,
            'total_rels': 0,
            'total_time_ms': 0,
            'count': 0
        }

    for sq_results in all_results:
        for r in sq_results['results']:
            method = r['method']
            res = r['result']

            method_stats[method]['total_nodes'] += len(res['node_types'])
            method_stats[method]['total_rels'] += len(res['relationship_types'])
            method_stats[method]['total_time_ms'] += res['time_ms']
            method_stats[method]['count'] += 1

    print(f"{'Method':<20} {'Avg Nodes':<12} {'Avg Rels':<12} {'Avg Time (ms)':<15}")
    print("-" * 80)

    for method, stats in method_stats.items():
        avg_nodes = stats['total_nodes'] / stats['count']
        avg_rels = stats['total_rels'] / stats['count']
        avg_time = stats['total_time_ms'] / stats['count']

        print(f"{method:<20} {avg_nodes:<12.1f} {avg_rels:<12.1f} {avg_time:<15.2f}")

    print()
    print("=" * 80)
    print("DETAILED SCORE COMPARISON (SQ1)")
    print("=" * 80)
    print()

    # Show detailed scores for SQ1 to see how different methods score types
    sq1 = subqueries[0]

    # Get scores for each method
    method_scores = {}
    for method_name, alpha in [('embeddings', 0.0), ('bm25', 1.0), ('hybrid', 0.5)]:
        display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"

        result = extract_with_method(
            query_text=sq1['text'],
            type_names=type_names,
            descriptions=descriptions,
            method=method_name,
            bm25_scorer=bm25,
            embeddings=embeddings,
            embedding_model=model,
            threshold=0.0,  # Get all scores
            top_k=100,
            alpha=alpha
        )

        method_scores[display_name] = result['scores']

    # Create comparison table
    print(f"{'Type':<20} {'Category':<12} {'Embeddings':<12} {'BM25':<12} {'Hybrid(0.5)':<12}")
    print("-" * 80)

    # Sort by hybrid score
    hybrid_scores = method_scores['hybrid(α=0.5)']
    indices = np.argsort(hybrid_scores)[::-1][:15]  # Top 15

    for idx in indices:
        category, type_name = type_names[idx]
        cat_label = "Node" if category == 'node' else "Relationship"

        emb_score = method_scores['embeddings'][idx]
        bm25_score = method_scores['bm25'][idx]
        hybrid_score = method_scores['hybrid(α=0.5)'][idx]

        print(f"{type_name:<20} {cat_label:<12} {emb_score:>6.4f}      {bm25_score:>6.4f}      {hybrid_score:>6.4f}")

    print()
    print("=" * 80)
    print("KEY OBSERVATIONS")
    print("=" * 80)
    print()
    print("💡 Method Characteristics:")
    print()
    print("1. Pure Embeddings:")
    print("   • Captures semantic similarity")
    print("   • May miss exact keyword matches")
    print("   • Example: 'Type node' → Type scored only ~15%")
    print()
    print("2. Pure BM25:")
    print("   • Strong on keyword/term matching")
    print("   • Example: 'Function node' → Function should score high")
    print("   • Less sensitive to semantic variations")
    print()
    print("3. Hybrid (α=0.5):")
    print("   • Balances keyword matching + semantics")
    print("   • α=0.7 favors BM25 (more keyword-driven)")
    print("   • α=0.3 favors embeddings (more semantic)")
    print()

if __name__ == "__main__":
    asyncio.run(main())
