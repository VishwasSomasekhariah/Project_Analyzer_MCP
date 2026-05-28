#!/usr/bin/env python3
"""
Comprehensive hyperparameter tuning for type extraction.
Grid search over: threshold, alpha, top_k, BM25 params.
"""
import asyncio
import yaml
import sys
import re
from typing import List, Dict, Tuple, Set
from itertools import product
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager, get_embedding_model
import numpy as np


class BM25Scorer:
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
        self.corpus = corpus
        self.N = len(corpus)
        tokenized_corpus = [self._tokenize(doc) for doc in corpus]
        self.doc_lens = [len(tokens) for tokens in tokenized_corpus]
        self.avgdl = sum(self.doc_lens) / self.N if self.N > 0 else 0

        for tokens in tokenized_corpus:
            unique_tokens = set(tokens)
            for token in unique_tokens:
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        for token, freq in self.doc_freqs.items():
            self.idf[token] = np.log((self.N - freq + 0.5) / (freq + 0.5) + 1.0)

    def _tokenize(self, text: str) -> List[str]:
        text = text.lower()
        tokens = re.findall(r'[a-z0-9_]+', text)
        return tokens

    def score(self, query: str) -> np.ndarray:
        query_tokens = self._tokenize(query)
        scores = np.zeros(self.N)

        for i, doc in enumerate(self.corpus):
            doc_tokens = self._tokenize(doc)
            doc_len = len(doc_tokens)
            term_freqs = {}
            for token in doc_tokens:
                term_freqs[token] = term_freqs.get(token, 0) + 1

            score = 0.0
            for token in query_tokens:
                if token in term_freqs:
                    tf = term_freqs[token]
                    idf = self.idf.get(token, 0)
                    numerator = tf * (self.k1 + 1)
                    denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                    score += idf * (numerator / denominator)

            scores[i] = score

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
    if method == 'bm25':
        scores = bm25_scorer.score(query_text)
    elif method == 'embeddings':
        query_embedding = embedding_model.encode([query_text], convert_to_numpy=True)[0]
        raw_scores = np.dot(embeddings, query_embedding)
        scores = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min() + 1e-10)
    elif method == 'hybrid':
        bm25_scores = bm25_scorer.score(query_text)
        query_embedding = embedding_model.encode([query_text], convert_to_numpy=True)[0]
        embedding_raw = np.dot(embeddings, query_embedding)
        embedding_min = embedding_raw.min()
        embedding_max = embedding_raw.max()
        embedding_normalized = (embedding_raw - embedding_min) / (embedding_max - embedding_min + 1e-10)
        scores = alpha * bm25_scores + (1 - alpha) * embedding_normalized

    matches = []
    for idx, score in enumerate(scores):
        if score >= threshold:
            category, type_name = type_names[idx]
            matches.append((type_name, category, score))

    matches.sort(key=lambda x: x[2], reverse=True)

    node_types = []
    rel_types = []
    for type_name, category, score in matches:
        if category == 'node' and len(node_types) < top_k:
            if type_name not in node_types:
                node_types.append(type_name)
        elif category == 'rel' and len(rel_types) < top_k:
            if type_name not in rel_types:
                rel_types.append(type_name)

    return {'node_types': node_types, 'relationship_types': rel_types}


def compute_metrics(predicted: Set[str], ground_truth: Set[str]) -> Dict:
    if len(predicted) == 0:
        precision = 0.0
    else:
        precision = len(predicted & ground_truth) / len(predicted)

    if len(ground_truth) == 0:
        recall = 0.0
    else:
        recall = len(predicted & ground_truth) / len(ground_truth)

    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * (precision * recall) / (precision + recall)

    return {'precision': precision, 'recall': recall, 'f1': f1}


async def main():
    print("=" * 80)
    print("HYPERPARAMETER TUNING")
    print("Grid search over: method, threshold, alpha, top_k, BM25 params")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")
    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_tuning_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    model = get_embedding_model()
    embeddings = schema_manager._type_embeddings['embeddings']
    type_names = schema_manager._type_embeddings['type_names']
    descriptions = schema_manager._type_embeddings['descriptions']

    # Ground truth
    test_cases = [
        {
            "id": "SQ1",
            "text": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
            "ground_truth_nodes": {"Function", "Type"},
            "ground_truth_rels": {"CONTAINS", "DEFINED_IN"},
        },
        {
            "id": "SQ2",
            "text": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
            "ground_truth_nodes": {"Function", "Type"},
            "ground_truth_rels": {"CALLS", "DECLARES"},
        },
        {
            "id": "SQ3",
            "text": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
            "ground_truth_nodes": {"Statement", "Function", "Type"},
            "ground_truth_rels": {"CONTAINS", "CALLS"},
        },
        {
            "id": "SQ4",
            "text": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
            "ground_truth_nodes": {"Variable", "Function", "Type"},
            "ground_truth_rels": {"DECLARES", "CONTAINS"},
        }
    ]

    # Hyperparameter grid
    param_grid = {
        'method': ['embeddings', 'bm25', 'hybrid'],
        'threshold': [0.15, 0.20, 0.25, 0.30],
        'alpha': [0.3, 0.4, 0.5, 0.6, 0.7],  # Only for hybrid
        'top_k': [5, 7, 10],
        'bm25_k1': [1.2, 1.5, 1.8],
        'bm25_b': [0.5, 0.75, 1.0],
    }

    print(f"Grid search space:")
    print(f"  Methods: {len(param_grid['method'])}")
    print(f"  Thresholds: {len(param_grid['threshold'])}")
    print(f"  Alphas (hybrid only): {len(param_grid['alpha'])}")
    print(f"  Top-k values: {len(param_grid['top_k'])}")
    print(f"  BM25 k1 values: {len(param_grid['bm25_k1'])}")
    print(f"  BM25 b values: {len(param_grid['bm25_b'])}")
    print()

    # Calculate total combinations
    embeddings_combos = len(param_grid['threshold']) * len(param_grid['top_k']) * len(param_grid['bm25_k1']) * len(param_grid['bm25_b'])
    bm25_combos = len(param_grid['threshold']) * len(param_grid['top_k']) * len(param_grid['bm25_k1']) * len(param_grid['bm25_b'])
    hybrid_combos = len(param_grid['threshold']) * len(param_grid['alpha']) * len(param_grid['top_k']) * len(param_grid['bm25_k1']) * len(param_grid['bm25_b'])

    total_combos = embeddings_combos + bm25_combos + hybrid_combos
    print(f"Total configurations to test: {total_combos}")
    print(f"  Embeddings: {embeddings_combos}")
    print(f"  BM25: {bm25_combos}")
    print(f"  Hybrid: {hybrid_combos}")
    print()

    # Run grid search
    results = []
    tested = 0

    for bm25_k1 in param_grid['bm25_k1']:
        for bm25_b in param_grid['bm25_b']:
            # Build BM25 scorer with these params
            print(f"\rBuilding BM25 scorer (k1={bm25_k1}, b={bm25_b})...", end='')
            bm25 = BM25Scorer(k1=bm25_k1, b=bm25_b)
            bm25.fit(descriptions)

            for method in param_grid['method']:
                for threshold in param_grid['threshold']:
                    for top_k in param_grid['top_k']:
                        # Alpha only matters for hybrid
                        alphas_to_test = param_grid['alpha'] if method == 'hybrid' else [0.0]

                        for alpha in alphas_to_test:
                            tested += 1
                            print(f"\rTesting configuration {tested}/{total_combos}...", end='')

                            # Test on all queries
                            all_node_f1 = []
                            all_rel_f1 = []

                            for test_case in test_cases:
                                result = extract_with_method(
                                    query_text=test_case['text'],
                                    type_names=type_names,
                                    descriptions=descriptions,
                                    method=method,
                                    bm25_scorer=bm25,
                                    embeddings=embeddings,
                                    embedding_model=model,
                                    threshold=threshold,
                                    top_k=top_k,
                                    alpha=alpha
                                )

                                predicted_nodes = set(result['node_types'])
                                predicted_rels = set(result['relationship_types'])

                                node_metrics = compute_metrics(predicted_nodes, test_case['ground_truth_nodes'])
                                rel_metrics = compute_metrics(predicted_rels, test_case['ground_truth_rels'])

                                all_node_f1.append(node_metrics['f1'])
                                all_rel_f1.append(rel_metrics['f1'])

                            # Compute average F1
                            avg_node_f1 = np.mean(all_node_f1)
                            avg_rel_f1 = np.mean(all_rel_f1)
                            combined_f1 = (avg_node_f1 + avg_rel_f1) / 2

                            results.append({
                                'method': method,
                                'threshold': threshold,
                                'alpha': alpha if method == 'hybrid' else None,
                                'top_k': top_k,
                                'bm25_k1': bm25_k1,
                                'bm25_b': bm25_b,
                                'node_f1': avg_node_f1,
                                'rel_f1': avg_rel_f1,
                                'combined_f1': combined_f1
                            })

    print()  # New line after progress
    print()
    print("=" * 80)
    print("GRID SEARCH COMPLETE")
    print("=" * 80)
    print()

    # Sort by combined F1
    results.sort(key=lambda x: x['combined_f1'], reverse=True)

    # Top 10 configurations
    print("TOP 10 CONFIGURATIONS")
    print("=" * 80)
    print()

    print(f"{'Rank':<5} {'Method':<12} {'Thresh':<8} {'Alpha':<8} {'Top-K':<7} {'BM25-k1':<9} {'BM25-b':<8} {'F1':<8}")
    print("-" * 80)

    for rank, config in enumerate(results[:10], 1):
        method = config['method']
        threshold = config['threshold']
        alpha = f"{config['alpha']:.1f}" if config['alpha'] is not None else "N/A"
        top_k = config['top_k']
        bm25_k1 = config['bm25_k1']
        bm25_b = config['bm25_b']
        f1 = config['combined_f1']

        print(f"{rank:<5} {method:<12} {threshold:<8.2f} {alpha:<8} {top_k:<7} {bm25_k1:<9.1f} {bm25_b:<8.2f} {f1:<8.3f}")

    print()
    print("=" * 80)
    print("BEST CONFIGURATION")
    print("=" * 80)
    print()

    best = results[0]
    print(f"🏆 Method: {best['method']}")
    print(f"   Threshold: {best['threshold']}")
    if best['alpha'] is not None:
        print(f"   Alpha: {best['alpha']}")
    print(f"   Top-K: {best['top_k']}")
    print(f"   BM25 k1: {best['bm25_k1']}")
    print(f"   BM25 b: {best['bm25_b']}")
    print()
    print(f"   Node F1: {best['node_f1']:.3f}")
    print(f"   Rel F1: {best['rel_f1']:.3f}")
    print(f"   Combined F1: {best['combined_f1']:.3f}")
    print()

    # Analysis by hyperparameter
    print("=" * 80)
    print("HYPERPARAMETER IMPACT ANALYSIS")
    print("=" * 80)
    print()

    # Group by method
    print("By Method:")
    for method in param_grid['method']:
        method_results = [r for r in results if r['method'] == method]
        avg_f1 = np.mean([r['combined_f1'] for r in method_results])
        print(f"  {method:<12}: avg F1 = {avg_f1:.3f}")
    print()

    # Group by threshold
    print("By Threshold:")
    for threshold in param_grid['threshold']:
        thresh_results = [r for r in results if r['threshold'] == threshold]
        avg_f1 = np.mean([r['combined_f1'] for r in thresh_results])
        print(f"  {threshold:.2f}        : avg F1 = {avg_f1:.3f}")
    print()

    # Group by alpha (hybrid only)
    print("By Alpha (hybrid only):")
    hybrid_results = [r for r in results if r['method'] == 'hybrid']
    for alpha in param_grid['alpha']:
        alpha_results = [r for r in hybrid_results if r['alpha'] == alpha]
        if alpha_results:
            avg_f1 = np.mean([r['combined_f1'] for r in alpha_results])
            print(f"  {alpha:.1f}          : avg F1 = {avg_f1:.3f}")
    print()

    # Group by top_k
    print("By Top-K:")
    for top_k in param_grid['top_k']:
        topk_results = [r for r in results if r['top_k'] == top_k]
        avg_f1 = np.mean([r['combined_f1'] for r in topk_results])
        print(f"  {top_k:<3}          : avg F1 = {avg_f1:.3f}")
    print()

    print("=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    print()
    print(f"Use the best configuration:")
    print(f"  Method: {best['method']}")
    print(f"  Threshold: {best['threshold']}")
    if best['alpha'] is not None:
        print(f"  Alpha: {best['alpha']}")
    print(f"  Top-K: {best['top_k']}")
    print(f"  BM25 k1: {best['bm25_k1']}, b: {best['bm25_b']}")
    print()
    print(f"Expected Combined F1: {best['combined_f1']:.3f}")
    print()

if __name__ == "__main__":
    asyncio.run(main())
