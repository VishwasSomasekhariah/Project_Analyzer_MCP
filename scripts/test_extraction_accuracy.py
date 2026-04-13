#!/usr/bin/env python3
"""
Measure extraction accuracy against ground-truth labels.
Computes precision, recall, and F1 score for each method.
"""
import asyncio
import yaml
import sys
import re
from typing import List, Dict, Tuple, Set
sys.path.insert(0, '/opt/genpod')

from src.core.cypher_server_service import create_cypher_server_service
from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager, get_embedding_model
import numpy as np


class BM25Scorer:
    """Simple BM25 implementation."""

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
    """Compute precision, recall, F1."""
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

    return {
        'precision': precision,
        'recall': recall,
        'f1': f1,
        'tp': len(predicted & ground_truth),
        'fp': len(predicted - ground_truth),
        'fn': len(ground_truth - predicted)
    }


async def main():
    print("=" * 80)
    print("EXTRACTION ACCURACY EVALUATION")
    print("Precision, Recall, F1 against Ground Truth")
    print("=" * 80)
    print()

    # Initialize
    server = await create_cypher_server_service("neo4j_config.json")
    with open("src/schemas/project_knowledgebase_graph_schema.yaml", 'r') as f:
        yaml_schema = yaml.safe_load(f)

    schema_manager = DynamicSchemaManager(
        cypher_server=server,
        cache_file="/tmp/test_accuracy_cache.json",
        yaml_schema=yaml_schema
    )

    print("Initializing...")
    await schema_manager.initialize_background()
    print("✅ Initialized\n")

    model = get_embedding_model()
    embeddings = schema_manager._type_embeddings['embeddings']
    type_names = schema_manager._type_embeddings['type_names']
    descriptions = schema_manager._type_embeddings['descriptions']

    print("Building BM25 index...")
    bm25 = BM25Scorer(k1=1.5, b=0.75)
    bm25.fit(descriptions)
    print("✅ BM25 ready\n")

    # Ground truth labels (manually annotated)
    test_cases = [
        {
            "id": "SQ1",
            "text": "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
            "ground_truth_nodes": {"Function", "Type"},  # Explicit mentions
            "ground_truth_rels": {"CONTAINS", "DEFINED_IN"},  # "contained" = CONTAINS, Function in Type = DEFINED_IN
        },
        {
            "id": "SQ2",
            "text": "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
            "ground_truth_nodes": {"Function", "Type"},  # Explicit mentions
            "ground_truth_rels": {"CALLS", "DECLARES"},  # Explicit "CALLS edges", "declaring" = DECLARES
        },
        {
            "id": "SQ3",
            "text": "locate all return-statement Statement nodes within F and for each returned expression that is a new instantiation, resolve the constructor call and retrieve the associated Type name",
            "ground_truth_nodes": {"Statement", "Function", "Type"},  # Statement, F=Function, Type
            "ground_truth_rels": {"CONTAINS", "CALLS"},  # "within F" = CONTAINS, "constructor call" = CALLS
        },
        {
            "id": "SQ4",
            "text": "locate Variable nodes V declared in F whose initial_value expressions include new instantiations and for each instantiation identify the Type node C and retrieve C.name",
            "ground_truth_nodes": {"Variable", "Function", "Type"},  # Explicit mentions
            "ground_truth_rels": {"DECLARES", "CONTAINS"},  # "declared" = DECLARES, "in F" = CONTAINS
        }
    ]

    methods = [
        ('embeddings', 0.0),
        ('bm25', 1.0),
        ('hybrid', 0.5),
        ('hybrid', 0.6),
        ('hybrid', 0.7),
    ]

    all_metrics = {m[0] if m[0] != 'hybrid' else f"hybrid(α={m[1]})": [] for m in methods}

    for test_case in test_cases:
        print("=" * 80)
        print(f"{test_case['id']}: {test_case['text'][:60]}...")
        print("=" * 80)
        print()

        print(f"Ground Truth:")
        print(f"  Nodes: {sorted(test_case['ground_truth_nodes'])}")
        print(f"  Rels:  {sorted(test_case['ground_truth_rels'])}")
        print()

        for method_name, alpha in methods:
            display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"

            result = extract_with_method(
                query_text=test_case['text'],
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

            predicted_nodes = set(result['node_types'])
            predicted_rels = set(result['relationship_types'])

            node_metrics = compute_metrics(predicted_nodes, test_case['ground_truth_nodes'])
            rel_metrics = compute_metrics(predicted_rels, test_case['ground_truth_rels'])

            all_metrics[display_name].append({
                'test_id': test_case['id'],
                'nodes': node_metrics,
                'rels': rel_metrics,
                'predicted_nodes': predicted_nodes,
                'predicted_rels': predicted_rels
            })

        # Display comparison table for this query
        print(f"{'Method':<20} {'Node P/R/F1':<25} {'Rel P/R/F1':<25}")
        print("-" * 80)

        for method_name, alpha in methods:
            display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"
            metrics = all_metrics[display_name][-1]

            node_prf = f"{metrics['nodes']['precision']:.2f}/{metrics['nodes']['recall']:.2f}/{metrics['nodes']['f1']:.2f}"
            rel_prf = f"{metrics['rels']['precision']:.2f}/{metrics['rels']['recall']:.2f}/{metrics['rels']['f1']:.2f}"

            print(f"{display_name:<20} {node_prf:<25} {rel_prf:<25}")

        print()

        # Show what was missed/extra
        for method_name, alpha in methods:
            display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"
            metrics = all_metrics[display_name][-1]

            node_fp = metrics['predicted_nodes'] - test_case['ground_truth_nodes']
            node_fn = test_case['ground_truth_nodes'] - metrics['predicted_nodes']
            rel_fp = metrics['predicted_rels'] - test_case['ground_truth_rels']
            rel_fn = test_case['ground_truth_rels'] - metrics['predicted_rels']

            if node_fp or node_fn or rel_fp or rel_fn:
                print(f"── {display_name} ──")
                if node_fn:
                    print(f"   ❌ Missed nodes: {node_fn}")
                if node_fp:
                    print(f"   ⚠️  Extra nodes:  {node_fp}")
                if rel_fn:
                    print(f"   ❌ Missed rels:  {rel_fn}")
                if rel_fp:
                    print(f"   ⚠️  Extra rels:   {rel_fp}")

        print()

    # Overall summary
    print("=" * 80)
    print("OVERALL ACCURACY SUMMARY")
    print("=" * 80)
    print()

    print(f"{'Method':<20} {'Avg Node F1':<15} {'Avg Rel F1':<15} {'Combined F1':<15}")
    print("-" * 80)

    for method_name, alpha in methods:
        display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"
        metrics_list = all_metrics[display_name]

        avg_node_f1 = np.mean([m['nodes']['f1'] for m in metrics_list])
        avg_rel_f1 = np.mean([m['rels']['f1'] for m in metrics_list])
        combined_f1 = (avg_node_f1 + avg_rel_f1) / 2

        print(f"{display_name:<20} {avg_node_f1:<15.3f} {avg_rel_f1:<15.3f} {combined_f1:<15.3f}")

    print()
    print("=" * 80)
    print("WINNER ANALYSIS")
    print("=" * 80)
    print()

    # Find best method
    best_method = None
    best_f1 = 0.0
    for method_name, alpha in methods:
        display_name = method_name if method_name != 'hybrid' else f"hybrid(α={alpha})"
        metrics_list = all_metrics[display_name]
        avg_node_f1 = np.mean([m['nodes']['f1'] for m in metrics_list])
        avg_rel_f1 = np.mean([m['rels']['f1'] for m in metrics_list])
        combined_f1 = (avg_node_f1 + avg_rel_f1) / 2

        if combined_f1 > best_f1:
            best_f1 = combined_f1
            best_method = display_name

    print(f"🏆 Best Method: {best_method} (F1={best_f1:.3f})")
    print()
    print("Explanation:")
    print("  • Precision: Of extracted types, how many are correct?")
    print("  • Recall: Of correct types, how many were extracted?")
    print("  • F1: Harmonic mean of precision and recall")
    print()

if __name__ == "__main__":
    asyncio.run(main())
