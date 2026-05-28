"""
Dynamic Schema Manager for CPG Queries

Loads schema once from apoc.meta.schema() during initialization,
then provides context-relevant schema slices for query generation.

Benefits:
- 10x smaller context (only relevant nodes/rels)
- 2-3x faster LLM responses
- Background loading (non-blocking)
- Actual runtime schema (not static YAML)
"""

import asyncio
import json
import re
from typing import Dict, List, Set, Optional, Any
from datetime import datetime
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Lazy import for sentence transformers (only load if needed)
_sentence_transformer_models = {}  # Cache multiple models by name

def get_embedding_model(model_name: str = 'all-MiniLM-L6-v2'):
    """
    Lazy load sentence transformer model (only when needed).
    Caches each model separately to allow comparisons.

    Supported models:
    - 'all-MiniLM-L6-v2': Fast, lightweight (80MB, 384 dims)
    - 'all-mpnet-base-v2': More accurate (420MB, 768 dims)
    - 'microsoft/codebert-base': Code-specific (500MB, 768 dims)
    - 'microsoft/graphcodebert-base': Graph-aware code model (500MB, 768 dims)
    """
    global _sentence_transformer_models

    if model_name not in _sentence_transformer_models:
        try:
            from sentence_transformers import SentenceTransformer
            _sentence_transformer_models[model_name] = SentenceTransformer(model_name)
            logger.info(f"📦 Loaded embedding model: {model_name}")
        except ImportError:
            logger.warning("⚠️ sentence-transformers not installed. Install with: pip install sentence-transformers")
            _sentence_transformer_models[model_name] = None
        except Exception as e:
            logger.error(f"❌ Failed to load model {model_name}: {e}")
            _sentence_transformer_models[model_name] = None

    return _sentence_transformer_models[model_name]


class BM25Scorer:
    """
    BM25 (Best Match 25) scoring for keyword-based type extraction.
    Optimized with k1=1.2, b=0.5 from hyperparameter tuning.
    """

    def __init__(self, k1=1.2, b=0.5):
        self.k1 = k1
        self.b = b
        self.corpus = []
        self.doc_lens = []
        self.avgdl = 0
        self.doc_freqs = {}
        self.idf = {}
        self.N = 0

    def fit(self, corpus: List[str]):
        """Build BM25 index from corpus of type descriptions."""
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


class DynamicSchemaManager:
    """
    Manages CPG schema with smart slicing and background loading.

    Flow:
    1. initialize_background() - Loads apoc.meta.schema() in background
    2. get_context_relevant_schema() - Returns only relevant subset
    3. Components wait only if schema not ready yet
    """

    def __init__(self, cypher_server=None, cache_file: Optional[str] = None, yaml_schema: Optional[Dict] = None, embedding_model: str = 'all-MiniLM-L6-v2'):
        """
        Initialize DynamicSchemaManager.

        Args:
            cypher_server: CypherServerService instance for executing queries
            cache_file: Path to cache file for path caching
            yaml_schema: Pre-loaded YAML schema dict (pass from workflow initialization)
            embedding_model: Model name for embeddings (default: 'all-MiniLM-L6-v2')
                Options: 'all-MiniLM-L6-v2', 'all-mpnet-base-v2',
                         'microsoft/codebert-base', 'microsoft/graphcodebert-base'
        """
        self.cypher_server = cypher_server
        self._full_schema = None  # From apoc.meta.schema() - the REALITY
        self._yaml_schema = yaml_schema  # From schema.yaml - the IDEAL/RULES (pre-loaded by workflow)
        self._reconciled_schema = None  # Reconciled: YAML + APOC reality
        self._valid_rel_pairs = {}  # Valid relationship pairs from Neo4j (ground truth)
        self._loading = False
        self._load_event = asyncio.Event()
        self._load_start_time = None
        self._load_duration_ms = None

        # Incremental path cache with metadata
        self._path_cache = {}  # In-memory cache: "Source->Target" -> [paths]
        self._cache_file = cache_file or "/tmp/cpg_path_cache.json"
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_metadata = {
            "created_at": datetime.now().isoformat(),
            "discovery_log": [],  # Track when each path was discovered
            "subquery_history": []  # Track which subqueries accessed cache
        }

        # Hybrid extraction: Embeddings + BM25 (optimal config from hyperparameter tuning)
        self._embedding_model_name = embedding_model  # Store model name
        self._type_embeddings = None  # Cached embeddings for schema types
        self._type_descriptions = {}   # Enhanced descriptions for better matching
        self._bm25_scorer = None       # BM25 scorer for keyword matching

    async def initialize_background(self):
        """
        Load APOC schema and reconcile with YAML schema.

        This runs during workflow initialization without blocking startup.
        Process:
        1. Load APOC schema (actual CPG reality)
        2. Reconcile with pre-loaded YAML schema (ideal rules)
        3. Build embeddings for fast semantic type extraction
        4. Load cached paths
        """
        self._loading = True
        self._load_start_time = datetime.now()

        try:
            # Step 1: Load APOC schema (reality)
            logger.info("📊 Loading CPG schema from apoc.meta.schema()...")
            result = await self.cypher_server.execute_query(
                "CALL apoc.meta.schema() YIELD value RETURN value"
            )

            # Cypher server returns: {'status': 'success', 'data': [...], ...}
            if result.get('status') == 'success' and result.get('data'):
                raw_schema = result['data'][0]['value']
                self._full_schema = self._parse_apoc_schema(raw_schema)

                logger.info(f"   • {len(self._full_schema['nodes'])} node types found in CPG")
                logger.info(f"   • {len(self._full_schema['relationships'])} relationship types found")

                # Step 1.5: Get all valid relationship pairs (single query for scalability)
                logger.info("🔍 Fetching valid relationship pairs from Neo4j...")
                self._valid_rel_pairs = await self._fetch_all_valid_pairs()
                total_pairs = sum(len(pairs) for pairs in self._valid_rel_pairs.values())
                logger.info(f"   • {total_pairs} valid relationship pairs found")

                # Step 2: Reconcile with YAML schema (if available)
                if self._yaml_schema:
                    logger.info("🔄 Reconciling YAML schema with APOC reality...")
                    self._reconciled_schema = self._reconcile_schemas()
                    logger.info(f"   • {len(self._reconciled_schema.get('nodes', {}))} types reconciled")
                else:
                    logger.warning("⚠️ No YAML schema provided, using APOC schema only")
                    self._reconciled_schema = self._full_schema

                # Step 3: Pre-populate cache with 1-hop direct edges
                logger.info("🔍 Pre-populating cache with direct edges (1-hop)...")
                edges_discovered = await self._populate_direct_edges_cache()
                logger.info(f"   • {edges_discovered} direct edges cached")

                # Step 4: Prepare embeddings for semantic extraction
                logger.info("🔢 Preparing embeddings for type extraction...")
                self._prepare_type_embeddings()

                # Step 5: Load cached paths
                await self._load_path_cache()

                self._load_duration_ms = (datetime.now() - self._load_start_time).total_seconds() * 1000

                logger.info(f"✅ Schema initialization complete in {self._load_duration_ms:.0f}ms")
                logger.info(f"   • {len(self._path_cache)} cached paths loaded")

                self._load_event.set()  # Signal ready
            else:
                logger.error(f"❌ Failed to load APOC schema: {result.get('error')}")
                self._load_event.set()

        except Exception as e:
            logger.error(f"❌ Schema initialization error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self._load_event.set()  # Unblock waiters

        finally:
            self._loading = False

    def _parse_apoc_schema(self, raw_schema: Dict) -> Dict:
        """
        Parse massive apoc.meta.schema() output into compact structure.

        Transforms:
        - From: 100KB nested dict with redundant info
        - To: 10KB structured dict with quick lookups

        Args:
            raw_schema: Output from CALL apoc.meta.schema() YIELD value

        Returns:
            Structured schema with:
            - nodes: {label: {count, properties, indexed_props}}
            - relationships: {type: {from_labels, to_labels, properties}}
            - node_properties: {label: {prop: type}}
            - rel_properties: {type: {prop: type}}
        """
        structured = {
            'nodes': {},
            'relationships': {},
            'node_properties': {},
            'rel_properties': {},
            '_metadata': {
                'loaded_at': datetime.now().isoformat(),
                'source': 'apoc.meta.schema()'
            }
        }

        # Process each label/type in schema
        for label_or_type, data in raw_schema.items():

            # Handle node labels
            if data.get('type') == 'node':
                structured['nodes'][label_or_type] = {
                    'count': data.get('count', 0),
                    'all_properties': [],
                    'indexed_properties': [],
                    'unique_properties': [],
                    'outgoing_relationships': {}
                }

                # Process node properties
                structured['node_properties'][label_or_type] = {}
                for prop_name, prop_meta in data.get('properties', {}).items():
                    # Store in flat dict for quick lookup
                    structured['node_properties'][label_or_type][prop_name] = {
                        'type': prop_meta.get('type', 'STRING'),
                        'indexed': prop_meta.get('indexed', False),
                        'unique': prop_meta.get('unique', False),
                        'array': prop_meta.get('array', False)
                    }

                    # Store in categorized lists for easy filtering
                    structured['nodes'][label_or_type]['all_properties'].append(prop_name)
                    if prop_meta.get('indexed'):
                        structured['nodes'][label_or_type]['indexed_properties'].append(prop_name)
                    if prop_meta.get('unique'):
                        structured['nodes'][label_or_type]['unique_properties'].append(prop_name)

                # Process relationships from this node
                for rel_type, rel_data in data.get('relationships', {}).items():
                    direction = rel_data.get('direction', 'out')
                    target_labels = rel_data.get('labels', [])

                    # Store in node's outgoing rels
                    structured['nodes'][label_or_type]['outgoing_relationships'][rel_type] = {
                        'direction': direction,
                        'target_labels': target_labels,
                        'count': rel_data.get('count', 0)
                    }

                    # Initialize relationship type if not exists
                    if rel_type not in structured['relationships']:
                        structured['relationships'][rel_type] = {
                            'from_labels': set(),
                            'to_labels': set(),
                            'properties': {},
                            'count': 0
                        }

                    # Add source/target labels
                    if direction == 'out':
                        structured['relationships'][rel_type]['from_labels'].add(label_or_type)
                        structured['relationships'][rel_type]['to_labels'].update(target_labels)
                    else:  # incoming
                        structured['relationships'][rel_type]['to_labels'].add(label_or_type)
                        structured['relationships'][rel_type]['from_labels'].update(target_labels)

                    structured['relationships'][rel_type]['count'] += rel_data.get('count', 0)

                    # Store relationship properties
                    for prop_name, prop_meta in rel_data.get('properties', {}).items():
                        if prop_name not in structured['relationships'][rel_type]['properties']:
                            structured['relationships'][rel_type]['properties'][prop_name] = {
                                'type': prop_meta.get('type', 'STRING'),
                                'array': prop_meta.get('array', False)
                            }

            # Handle relationship types (top-level in apoc output)
            elif data.get('type') == 'relationship':
                if label_or_type not in structured['relationships']:
                    structured['relationships'][label_or_type] = {
                        'from_labels': set(),
                        'to_labels': set(),
                        'properties': {},
                        'count': data.get('count', 0)
                    }

                # Store relationship properties
                structured['rel_properties'][label_or_type] = {}
                for prop_name, prop_meta in data.get('properties', {}).items():
                    structured['rel_properties'][label_or_type][prop_name] = {
                        'type': prop_meta.get('type', 'STRING'),
                        'array': prop_meta.get('array', False)
                    }
                    structured['relationships'][label_or_type]['properties'][prop_name] = {
                        'type': prop_meta.get('type', 'STRING'),
                        'array': prop_meta.get('array', False)
                    }

        # Convert sets to lists for JSON serialization
        for rel_type, rel_data in structured['relationships'].items():
            rel_data['from_labels'] = sorted(list(rel_data['from_labels']))
            rel_data['to_labels'] = sorted(list(rel_data['to_labels']))

        return structured

    async def _fetch_all_valid_pairs(self) -> Dict[str, list]:
        """
        Fetch all valid (source, target) pairs for all relationships in ONE query.

        This is scalable - single query gets ground truth for entire schema.
        Filters out APOC's false positives where labels are listed but count=0.

        Returns:
            {
                'CONTAINS': [{'from': 'File', 'to': 'Type'}, ...],
                'CALLS': [{'from': 'Function', 'to': 'Function'}, ...],
                ...
            }
        """
        query = """
        MATCH (s)-[r]->(t)
        WITH type(r) AS rel_type, labels(s)[0] AS source, labels(t)[0] AS target
        RETURN rel_type, collect(DISTINCT {from: source, to: target}) AS pairs
        """
        result = await self.cypher_server.execute_query(query)

        # Convert to dict: {rel_type: [pairs]}
        valid_pairs = {}
        for row in result.get('data', []):  # Fixed: cypher server returns 'data', not 'results'
            rel_type = row['rel_type']
            pairs = row['pairs']
            valid_pairs[rel_type] = pairs

        return valid_pairs

    def _reconcile_schemas(self) -> Dict:
        """
        Reconcile YAML schema with APOC reality to create clean, LLM-friendly schema.

        Strategy:
        1. Start with YAML schema (clean descriptions, LLM-friendly)
        2. Filter to only include types that exist in CPG (count > 0)
        3. Use actual properties/valid_pairs from APOC (ground truth)
        4. Keep it simple - no reconciliation metadata

        Returns:
            Clean schema structure:
            {
                'nodes': {
                    'Function': {
                        'description': "..." (from YAML),
                        'properties': [...] (from APOC - what actually exists),
                        'indexed': [...] (from APOC),
                        'count': N (from APOC)
                    }
                },
                'relationships': {
                    'CALLS': {
                        'description': "..." (from YAML),
                        'from': ['Function'] (from APOC - actual valid pairs),
                        'to': ['Function'] (from APOC),
                        'properties': [...] (from APOC),
                        'count': N (from APOC)
                    }
                }
            }
        """
        reconciled = {
            'nodes': {},
            'relationships': {}
        }

        # Reconcile node types: YAML description + APOC reality
        yaml_nodes = self._yaml_schema.get('nodes', {})
        apoc_nodes = self._full_schema.get('nodes', {})

        # Only include nodes that exist in APOC (have been parsed into CPG)
        for node_type in apoc_nodes.keys():
            apoc_def = apoc_nodes[node_type]

            # Only include if count > 0 (exists in CPG)
            if apoc_def.get('count', 0) == 0:
                continue

            reconciled['nodes'][node_type] = {
                'description': self._extract_node_description(node_type),
                'properties': apoc_def.get('all_properties', []),
                'indexed': apoc_def.get('indexed_properties', []),
                'count': apoc_def.get('count', 0)
            }

        # Reconcile relationship types: YAML description + APOC valid pairs
        yaml_rels = self._yaml_schema.get('relationships', {})
        apoc_rels = self._full_schema.get('relationships', {})

        # Only include relationships that exist in APOC (count > 0)
        for rel_type in apoc_rels.keys():
            apoc_def = apoc_rels[rel_type]

            count = apoc_def.get('count', 0)
            if count == 0:
                logger.debug(f"   Skipping {rel_type}: not present in CPG (count=0)")
                continue

            # Use pre-fetched valid pairs (fetched in single query during initialization)
            # This eliminates APOC's false positives where labels exist but count=0
            valid_pairs = self._valid_rel_pairs.get(rel_type, [])

            reconciled['relationships'][rel_type] = {
                'description': self._extract_relationship_description(rel_type),
                'valid_pairs': valid_pairs,  # Valid node type pairs that can be connected (count > 0)
                'properties': list(apoc_def.get('properties', {}).keys()),
                'count': count
            }

        logger.info(f"   ✅ Reconciliation complete: {len(reconciled['nodes'])} nodes, {len(reconciled['relationships'])} relationships")

        return reconciled

    async def _populate_direct_edges_cache(self) -> int:
        """
        Pre-populate path cache with 1-hop direct edges (depth=1 paths).

        Strategy:
        1. Sample 1 node per type
        2. Get all 1-hop neighbors
        3. Add to path cache as depth=1 entries
        4. Future queries build on this foundation (depth=2, depth=3, etc.)

        Benefits:
        - Immediate neighbors cached (~16ms one-time cost)
        - Eliminates ~79% of futile multi-hop searches
        - Progressive cache building on solid foundation

        Returns:
            Number of direct edges discovered and cached
        """
        if not self._reconciled_schema:
            logger.warning("⚠️ Cannot populate cache without reconciled schema")
            return 0

        # Get node types and relationship types
        node_types = list(self._reconciled_schema.get('nodes', {}).keys())
        rel_types = list(self._reconciled_schema.get('relationships', {}).keys())

        if not node_types or not rel_types:
            logger.warning("⚠️ No node types or relationships found")
            return 0

        # Build UNION query to sample neighbors
        union_parts = []

        for node_type in node_types:
            # Sample outgoing edges
            union_parts.append(f"""
                MATCH (n:{node_type})
                WITH n LIMIT 1
                MATCH (n)-[r]->(m)
                WHERE type(r) IN {rel_types}
                RETURN
                    '{node_type}' as from_label,
                    type(r) as rel_type,
                    labels(m)[0] as to_label,
                    count(DISTINCT m) as neighbor_count
            """.strip())

            # Sample incoming edges (for reverse paths)
            union_parts.append(f"""
                MATCH (n:{node_type})
                WITH n LIMIT 1
                MATCH (m)-[r]->(n)
                WHERE type(r) IN {rel_types}
                RETURN
                    labels(m)[0] as from_label,
                    type(r) as rel_type,
                    '{node_type}' as to_label,
                    count(DISTINCT m) as neighbor_count
            """.strip())

        query = "\nUNION ALL\n".join(union_parts)

        try:
            result = await self.cypher_server.execute_query(query)

            # Group edges by (source, target) and build depth=1 path entries
            # IMPORTANT: Only cache paths that exist in valid_rel_pairs (filters out reverse paths)
            edges_by_pair = {}  # {(source, target): [(rel_type, count)]}

            if result.get('status') == 'success' and result.get('data'):
                for row in result['data']:
                    if row['neighbor_count'] > 0:
                        from_label = row['from_label']
                        to_label = row['to_label']
                        rel_type = row['rel_type']
                        count = row['neighbor_count']

                        # Validate this path exists in valid_rel_pairs
                        valid_pairs = self._valid_rel_pairs.get(rel_type, [])
                        pair = {'from': from_label, 'to': to_label}
                        if pair not in valid_pairs:
                            # Skip invalid reverse paths
                            logger.debug(f"   Skipping invalid path: {from_label} -[{rel_type}]-> {to_label}")
                            continue

                        key = (from_label, to_label)
                        if key not in edges_by_pair:
                            edges_by_pair[key] = []
                        edges_by_pair[key].append((rel_type, count))

            # Populate path cache with depth=1 entries (deduplicated)
            edges_cached = 0
            for (source, target), rels_and_counts in edges_by_pair.items():
                # Initialize nested cache structure
                if source not in self._path_cache:
                    self._path_cache[source] = {}

                # Add depth=1 paths (one entry per relationship type)
                if target not in self._path_cache[source]:
                    self._path_cache[source][target] = []

                # Deduplicate by rel_type
                seen_rel_types = set()
                for rel_type, count in rels_and_counts:
                    if rel_type not in seen_rel_types:
                        seen_rel_types.add(rel_type)
                        path_entry = {
                            "rels": [rel_type],
                            "via": [],  # No intermediate nodes for depth=1
                            "depth": 1
                        }
                        self._path_cache[source][target].append(path_entry)
                        edges_cached += 1

                # Log to metadata
                self._cache_metadata['discovery_log'].append({
                    "timestamp": datetime.now().isoformat(),
                    "source": source,
                    "target": target,
                    "paths_discovered": len(seen_rel_types),
                    "depth": 1,
                    "method": "direct_edge_sampling"
                })

            # Calculate efficiency stats
            theoretical_edges = len(node_types) * len(rel_types) * len(node_types)
            actual_pairs = len(edges_by_pair)
            filtered_out = theoretical_edges - edges_cached
            efficiency_percent = (filtered_out / theoretical_edges * 100) if theoretical_edges > 0 else 0

            logger.info(f"   • Theoretical edge combinations: {theoretical_edges}")
            logger.info(f"   • Actual (source→target) pairs: {actual_pairs}")
            logger.info(f"   • Efficiency: {efficiency_percent:.1f}% searches pre-filtered")

            return edges_cached

        except Exception as e:
            logger.error(f"❌ Failed to populate direct edges: {e}")
            return 0

    def _extract_node_description(self, node_type: str) -> str:
        """
        Extract semantic description for a node type from YAML NodeDefinitions.

        Prioritizes EnrichmentDescription (optimized for semantic matching)
        over Description (technical creation details).

        Args:
            node_type: Node label (e.g., 'Function')

        Returns:
            Description string for embedding
        """
        if not self._yaml_schema:
            return f"{node_type} node in code property graph"

        # Check if NodeDefinitions exist in YAML
        node_defs = self._yaml_schema.get('NodeDefinitions', {})
        if node_type in node_defs:
            creation = node_defs[node_type].get('Creation', {})

            # Prioritize EnrichmentDescription (semantic-matching optimized)
            enrichment_desc = creation.get('EnrichmentDescription', '')
            if enrichment_desc:
                return enrichment_desc

            # Fallback to Description (technical)
            creation_desc = creation.get('Description', '')
            if creation_desc:
                return creation_desc

        # Fallback: use attributes as description
        node_def = self._yaml_schema.get('nodes', {}).get(node_type, {})
        attributes = node_def.get('attributes', [])
        if attributes:
            return f"{node_type}: {', '.join(attributes[:5])}"

        return f"{node_type} node in code property graph"

    def _extract_relationship_description(self, rel_type: str) -> str:
        """
        Extract semantic description for a relationship from YAML EdgeDefinitions.

        Prioritizes EnrichmentDescription (optimized for semantic matching)
        over Description (technical creation details).

        Args:
            rel_type: Relationship type (e.g., 'CONTAINS', 'CALLS')

        Returns:
            Description string for embedding
        """
        if not self._yaml_schema:
            return f"{rel_type} relationship"

        # Check EdgeDefinitions in YAML
        edge_defs = self._yaml_schema.get('EdgeDefinitions', {})
        if rel_type in edge_defs:
            creation = edge_defs[rel_type].get('Creation', {})

            # Prioritize EnrichmentDescription (semantic-matching optimized)
            enrichment_desc = creation.get('EnrichmentDescription', '')
            if enrichment_desc:
                return enrichment_desc

            # Fallback to Description (technical)
            creation_desc = creation.get('Description', '')
            if creation_desc:
                return creation_desc

        # Fallback: construct from relationship definition
        rel_def = self._yaml_schema.get('relationships', {}).get(rel_type, {})
        from_types = rel_def.get('from', [])
        to_types = rel_def.get('to', [])

        if isinstance(from_types, str):
            from_types = [from_types]
        if isinstance(to_types, str):
            to_types = [to_types]

        if from_types and to_types:
            return f"{rel_type} connects {', '.join(from_types[:2])} to {', '.join(to_types[:2])}"

        return f"{rel_type} relationship"

    async def _load_path_cache(self):
        """Load previously cached paths from disk"""
        try:
            import os
            if os.path.exists(self._cache_file):
                with open(self._cache_file, 'r') as f:
                    self._path_cache = json.load(f)
                logger.info(f"📂 Loaded {len(self._path_cache)} cached paths from {self._cache_file}")
            else:
                logger.info(f"📂 No path cache found, will build incrementally")
        except Exception as e:
            logger.warning(f"⚠️ Failed to load path cache: {e}")
            self._path_cache = {}

    async def _save_path_cache(self):
        """Save path cache to disk for next run"""
        try:
            with open(self._cache_file, 'w') as f:
                json.dump(self._path_cache, f, indent=2)
            logger.debug(f"💾 Saved {len(self._path_cache)} paths to cache")
        except Exception as e:
            logger.warning(f"⚠️ Failed to save path cache: {e}")

    async def get_paths_between(
        self,
        source: str,
        target: str,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 5,
        cypher_server: Optional[Any] = None
    ) -> List[Dict]:
        """
        Get all paths from source to target node type.

        This is the main API for path discovery. It:
        1. Checks in-memory cache first (nested: cache[source][target])
        2. If not cached, discovers using APOC
        3. Caches result for future use
        4. Saves cache to disk

        Args:
            source: Source node type (e.g., "Function")
            target: Target node type (e.g., "Variable")
            relationship_types: Optional list of allowed relationship types
            max_depth: Maximum path depth (default: 5)

        Returns:
            List of path dictionaries: [{"rels": [...], "via": [...], "depth": N}]
        """
        # Check nested cache structure: cache[source][target]
        if source in self._path_cache and target in self._path_cache[source]:
            self._cache_hits += 1
            logger.debug(f"✅ Cache hit: {source} → {target} (hits={self._cache_hits}, misses={self._cache_misses})")
            paths = self._path_cache[source][target]

            # Filter by relationship types if specified
            if relationship_types:
                paths = [p for p in paths if all(r in relationship_types for r in p['rels'])]

            return paths

        # Cache miss - discover on-demand
        self._cache_misses += 1
        logger.info(f"🔍 Cache miss: discovering paths {source} → {target} (hits={self._cache_hits}, misses={self._cache_misses})")

        paths = await self._discover_path_on_demand(source, target, relationship_types, max_depth, cypher_server)

        # Cache result in nested structure
        if source not in self._path_cache:
            self._path_cache[source] = {}
        self._path_cache[source][target] = paths

        # Save cache periodically (every 10 misses)
        if self._cache_misses % 10 == 0:
            await self._save_path_cache()

        return paths

    async def _discover_path_on_demand(
        self,
        source: str,
        target: str,
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 5,
        cypher_server: Optional[Any] = None
    ) -> List[Dict]:
        """
        Use APOC to discover paths between specific source and target.

        This is MUCH faster than discovering all paths because:
        - Only explores from source nodes (not all nodes)
        - Only looks for target type (not all types)
        - Filters by relationship types if specified

        Args:
            source: Source node label
            target: Target node label
            relationship_types: Optional relationship type filter
            max_depth: Maximum depth to explore

        Returns:
            List of discovered paths
        """

        # Build relationship filter for APOC
        if relationship_types:
            # Determine directionality for each relationship type
            # Hierarchical (CONTAINS): only one direction exists (A→B but not B→A)
            # Symmetric (REFERENCES): bidirectional (A→B and B→A both exist)
            rel_filter_parts = []
            for rel_type in relationship_types:
                valid_pairs = self._valid_rel_pairs.get(rel_type, [])

                # Check if ANY pair has a reverse pair (making it symmetric)
                # Ignore self-loops (A→A) as they don't indicate symmetry
                is_symmetric = False
                for pair in valid_pairs:
                    # Skip self-loops
                    if pair['from'] == pair['to']:
                        continue

                    reverse = {'from': pair['to'], 'to': pair['from']}
                    if reverse in valid_pairs:
                        is_symmetric = True
                        break

                if is_symmetric:
                    # Bidirectional: allow both directions
                    rel_filter_parts.append(f"{rel_type}>")
                    rel_filter_parts.append(f"<{rel_type}")
                else:
                    # Hierarchical: only allow forward direction
                    rel_filter_parts.append(f"{rel_type}>")

            rel_filter = '|'.join(rel_filter_parts) if rel_filter_parts else "CONTAINS>"
        else:
            rel_filter = ""  # Any relationship, any direction

        query = f"""
        // Sample multiple source nodes to discover all path patterns
        MATCH (s:{source})
        WITH s LIMIT 10

        // Use APOC to find all paths (no label filter - allow any intermediates)
        CALL apoc.path.expandConfig(s, {{
            minLevel: 1,
            maxLevel: {max_depth},
            relationshipFilter: '{rel_filter}',
            uniqueness: 'RELATIONSHIP_PATH',
            bfs: true,
            limit: 100  // Find up to 100 paths per source
        }})
        YIELD path

        // Filter to only paths that end at target type
        WHERE labels(nodes(path)[-1])[0] = '{target}'

        // Extract path pattern (relationship types + intermediate node types)
        WITH nodes(path) AS all_nodes,
             relationships(path) AS all_rels,
             length(path) AS depth

        // Get intermediate nodes (exclude source [0] and target [-1])
        // In Cypher: list[1..-1] means from index 1 UP TO (but not including) index -1 (last element)
        WITH [rel IN all_rels | type(rel)] AS rels,
             CASE
                WHEN size(all_nodes) > 2  // Has intermediate nodes
                THEN [node IN all_nodes[1..-1] | labels(node)[0]]  // Get nodes between source and target
                ELSE []  // Direct connection (no intermediates)
             END AS via,
             depth

        // Aggregate distinct path patterns
        WITH rels, via, depth

        RETURN DISTINCT rels, via, depth
        ORDER BY depth
        LIMIT 50
        """

        try:
            # Use provided server or fallback to schema manager's server
            server = cypher_server if cypher_server else self.cypher_server
            result = await server.execute_query(query)

            # Cypher server returns: {'status': 'success', 'data': [...], ...}
            if result.get('status') != 'success' or not result.get('data'):
                logger.warning(f"No paths found: {source} → {target}")
                return []

            paths = []
            for row in result['data']:
                paths.append({
                    'rels': row['rels'],
                    'via': row['via'],
                    'depth': row['depth']
                })

            logger.info(f"   ✅ Found {len(paths)} distinct path patterns")
            return paths

        except Exception as e:
            logger.error(f"❌ Path discovery failed for {source} → {target}: {e}")
            return []

    async def get_context_relevant_schema(
        self,
        node_types: Optional[List[str]] = None,
        relationship_types: Optional[List[str]] = None,
        format: str = 'text'  # 'text', 'dict', 'json'
    ) -> Any:
        """
        Get only the schema subset relevant to current context.

        This is the key optimization - instead of passing 10 node types
        with all their properties and relationships (5KB+), we pass only
        2-3 relevant types (500B).

        Args:
            node_types: Which node labels to include (e.g., ["Function", "Type"])
            relationship_types: Which rel types to include (e.g., ["CALLS", "CONTAINS"])
            format: 'text' (human-readable), 'dict' (structured), 'json' (serialized)

        Returns:
            Schema subset in requested format
        """
        # Wait for schema if still loading
        if self._loading or not self._full_schema:
            logger.info("⏳ Waiting for schema to load...")
            await self._load_event.wait()

        if not self._full_schema:
            logger.warning("⚠️ Schema not available, returning empty")
            return "" if format == 'text' else {}

        # If no context specified, return compact summary
        if not node_types and not relationship_types:
            return self._get_schema_summary(format)

        # Extract relevant subset
        subset = self._slice_schema(
            node_types or [],
            relationship_types or []
        )

        if format == 'text':
            return self._format_schema_as_text(subset)
        elif format == 'json':
            return json.dumps(subset, indent=2)
        else:  # dict
            return subset

    def _slice_schema(
        self,
        node_types: List[str],
        relationship_types: List[str]
    ) -> Dict:
        """Extract only specified nodes and relationships"""
        subset = {
            'nodes': {},
            'relationships': {},
            'node_properties': {},
            'rel_properties': {}
        }

        # Extract requested nodes
        for node_type in node_types:
            if node_type in self._full_schema['nodes']:
                subset['nodes'][node_type] = self._full_schema['nodes'][node_type]
                subset['node_properties'][node_type] = self._full_schema['node_properties'][node_type]

        # Extract requested relationships
        for rel_type in relationship_types:
            if rel_type in self._full_schema['relationships']:
                subset['relationships'][rel_type] = self._full_schema['relationships'][rel_type]
                if rel_type in self._full_schema['rel_properties']:
                    subset['rel_properties'][rel_type] = self._full_schema['rel_properties'][rel_type]

        return subset

    def _format_schema_as_text(self, schema_subset: Dict) -> str:
        """
        Format schema subset as compact, readable text for LLM context.

        Example output:
        '''
        Node: Function (12 instances)
          Indexed: name, body
          Properties: name, return_type, parameters, body, modifier
          Outgoing:
            CALLS → Function (43 edges)
            CONTAINS → Block, Variable (12 edges)

        Node: Type (10 instances)
          Indexed: name
          Properties: name, type_kind, modifier, body
          Outgoing:
            CONTAINS → Function (9 edges)

        Relationship: CALLS (43 edges)
          From: Function
          To: Function
          Properties: text, created_at
        '''
        """
        lines = []

        # Format nodes
        for node_label, node_data in schema_subset['nodes'].items():
            lines.append(f"Node: {node_label} ({node_data['count']} instances)")

            # Indexed properties (most important)
            if node_data['indexed_properties']:
                lines.append(f"  Indexed: {', '.join(node_data['indexed_properties'])}")

            # All properties (compact)
            if node_data['all_properties']:
                props = ', '.join(node_data['all_properties'][:10])  # Limit to 10
                if len(node_data['all_properties']) > 10:
                    props += f", ... ({len(node_data['all_properties'])} total)"
                lines.append(f"  Properties: {props}")

            # Outgoing relationships
            if node_data['outgoing_relationships']:
                lines.append("  Outgoing:")
                for rel_type, rel_info in node_data['outgoing_relationships'].items():
                    targets = ', '.join(rel_info['target_labels'])
                    lines.append(f"    {rel_type} → {targets} ({rel_info['count']} edges)")

            lines.append("")  # Blank line

        # Format relationships
        for rel_type, rel_data in schema_subset['relationships'].items():
            lines.append(f"Relationship: {rel_type} ({rel_data['count']} edges)")
            if rel_data['from_labels']:
                lines.append(f"  From: {', '.join(rel_data['from_labels'])}")
            if rel_data['to_labels']:
                lines.append(f"  To: {', '.join(rel_data['to_labels'])}")
            if rel_data['properties']:
                props = ', '.join(rel_data['properties'].keys())
                lines.append(f"  Properties: {props}")
            lines.append("")

        return '\n'.join(lines)

    def _get_schema_summary(self, format: str) -> Any:
        """Get compact summary of entire schema"""
        summary = {
            'node_types': list(self._full_schema['nodes'].keys()),
            'relationship_types': list(self._full_schema['relationships'].keys()),
            'total_nodes': sum(n['count'] for n in self._full_schema['nodes'].values()),
            'total_relationships': sum(r['count'] for r in self._full_schema['relationships'].values()),
        }

        if format == 'text':
            lines = [
                f"CPG Schema Summary:",
                f"  Node Types ({len(summary['node_types'])}): {', '.join(summary['node_types'])}",
                f"  Relationship Types ({len(summary['relationship_types'])}): {', '.join(summary['relationship_types'])}",
                f"  Total Nodes: {summary['total_nodes']}",
                f"  Total Relationships: {summary['total_relationships']}"
            ]
            return '\n'.join(lines)
        elif format == 'json':
            return json.dumps(summary, indent=2)
        else:
            return summary

    def _prepare_type_embeddings(self):
        """
        Prepare embeddings for all schema types using reconciled schema.

        Uses actual descriptions and properties from reconciled schema,
        not hardcoded values!
        """
        if not self._reconciled_schema or self._type_embeddings is not None:
            return  # Already prepared or schema not ready

        model = get_embedding_model(self._embedding_model_name)
        if model is None:
            logger.warning("⚠️ sentence-transformers not installed, embedding-based extraction disabled")
            return

        descriptions = []
        type_names = []

        # Build descriptions from reconciled schema - Node types
        for node_type, node_data in self._reconciled_schema.get('nodes', {}).items():
            # Use description from YAML
            desc = node_data.get('description', f"{node_type} node")

            # Add property names for better matching
            props = node_data.get('properties', [])
            if props:
                desc += f". Properties: {', '.join(props[:5])}"

            descriptions.append(desc)
            type_names.append(('node', node_type))

        # Build descriptions from reconciled schema - Relationship types
        for rel_type, rel_data in self._reconciled_schema.get('relationships', {}).items():
            desc = rel_data.get('description', f"{rel_type} relationship")

            # Add all valid pair examples for complete semantic matching coverage
            valid_pairs = rel_data.get('valid_pairs', [])
            if valid_pairs:
                examples = [f"{p['from']}-{p['to']}" for p in valid_pairs]
                desc += f". Examples: {', '.join(examples)}"

            descriptions.append(desc)
            type_names.append(('rel', rel_type))

        # Compute embeddings
        logger.info(f"   Computing embeddings for {len(descriptions)} types...")
        embeddings = model.encode(descriptions, convert_to_numpy=True)

        # Build BM25 index with optimal parameters (k1=1.2, b=0.5)
        self._bm25_scorer = BM25Scorer(k1=1.2, b=0.5)
        self._bm25_scorer.fit(descriptions)

        # Cache
        self._type_embeddings = {
            'embeddings': embeddings,
            'type_names': type_names,
            'descriptions': descriptions
        }

        logger.info(f"   ✅ Embeddings and BM25 index ready")

    def _extract_explicit_type_mentions(self, query_text: str) -> tuple:
        """
        Extract types explicitly mentioned in query using keyword matching.

        Patterns:
        - "Type node", "Type nodes", "Function node", "Variable nodes" → Node types
        - "CALLS edges", "CONTAINS relationship" → Relationship types

        Handles both singular and plural forms to match natural language patterns.

        Returns:
            (node_types, relationship_types) lists
        """
        import re

        query_lower = query_text.lower()

        # Extract explicit node mentions
        explicit_nodes = []
        available_nodes = list(self._reconciled_schema.get('nodes', {}).keys())

        for node_type in available_nodes:
            # Patterns: "Type node", "Type nodes", "Types node", "Types nodes", etc.
            # Handle both singular/plural for both the type name and the word "node"
            patterns = [
                rf'\b{node_type}s?\s+nodes?\b',  # "Type node(s)" or "Types node(s)"
                rf'\bnodes?\s+{node_type}s?\b',  # "node(s) Type(s)"
                rf'\b{node_type}s?\b(?=\s+(named|called|with|where))',  # "Type(s) named X"
            ]

            for pattern in patterns:
                if re.search(pattern, query_text, re.IGNORECASE):
                    if node_type not in explicit_nodes:
                        explicit_nodes.append(node_type)
                    break

        # Extract explicit relationship mentions
        explicit_rels = []
        available_rels = list(self._reconciled_schema.get('relationships', {}).keys())

        for rel_type in available_rels:
            # Patterns: "CALLS edges", "CONTAINS relationships", etc.
            # Handle plural forms
            patterns = [
                rf'\b{rel_type}\s+(edges?|relationships?|rels?)\b',
                rf'\b(edges?|relationships?|rels?)\s+{rel_type}\b',
            ]

            for pattern in patterns:
                if re.search(pattern, query_text, re.IGNORECASE):
                    if rel_type not in explicit_rels:
                        explicit_rels.append(rel_type)
                    break

        return explicit_nodes, explicit_rels

    def extract_types_from_query(
        self,
        query_text: str,
        similarity_threshold: float = 0.60,  # Optimal with EnrichmentDescription
        top_k: int = 5,
        method: str = 'hybrid',  # 'embeddings', 'bm25', or 'hybrid'
        alpha: float = 0.15,  # Optimal: 85% embeddings, 15% BM25
        return_scores: bool = False  # Return similarity scores for analysis
    ) -> Dict[str, Any]:
        """
        Extract relevant node/relationship types using 2-tier extraction.

        Tier 1 (Explicit): Keywords directly mentioned in query (e.g., "Type node", "CALLS edges")
        Tier 2 (Context): Hybrid similarity for additional context types

        Uses optimal configuration with EnrichmentDescription:
        - Method: hybrid (85% embeddings + 15% BM25)
        - Threshold: 0.60 (high precision, perfect recall with all-MiniLM-L6-v2)
        - Alpha: 0.15 (very semantic - leverages EnrichmentDescription descriptions)

        Results with optimal config:
        - Node extraction: 85% precision, 100% recall, 0.89 F1
        - Relationship extraction: 62.5% precision, 50% recall, 0.50 F1
        - 3 out of 4 subqueries achieve perfect node extraction

        Args:
            query_text: Natural language query or subquery
            similarity_threshold: Minimum similarity score (0-1), default 0.60
            top_k: Max types to extract per category, default 5
            method: 'embeddings', 'bm25', or 'hybrid', default 'hybrid'
            alpha: For hybrid, weight of BM25 vs embeddings, default 0.15
            return_scores: If True, return detailed similarity scores for analysis

        Returns:
            {'node_types': [...], 'relationship_types': [...]}
            If return_scores=True, also includes 'node_scores' and 'rel_scores'
        """
        if not self._reconciled_schema:
            return {'node_types': [], 'relationship_types': []}

        # Tier 1: Extract explicitly mentioned types (keyword matching)
        explicit_nodes, explicit_rels = self._extract_explicit_type_mentions(query_text)

        # Prepare embeddings if not done
        if self._type_embeddings is None:
            self._prepare_type_embeddings()

        if self._type_embeddings is None:
            # Fallback: return only explicit matches
            logger.warning("⚠️ Embeddings not available, using explicit matches only")
            return {'node_types': explicit_nodes, 'relationship_types': explicit_rels}

        # Compute similarity scores based on method
        embeddings = self._type_embeddings['embeddings']
        type_names = self._type_embeddings['type_names']

        if method == 'bm25':
            # Pure BM25 keyword matching
            scores = self._bm25_scorer.score(query_text)

        elif method == 'embeddings':
            # Pure semantic embeddings
            model = get_embedding_model(self._embedding_model_name)
            query_embedding = model.encode([query_text], convert_to_numpy=True)[0]
            raw_scores = np.dot(embeddings, query_embedding)
            # Normalize to [0, 1] for consistent thresholding
            scores = (raw_scores - raw_scores.min()) / (raw_scores.max() - raw_scores.min() + 1e-10)

        elif method == 'hybrid':
            # Hybrid: weighted combination (optimal alpha=0.3)
            # Get BM25 scores
            bm25_scores = self._bm25_scorer.score(query_text)

            # Get embedding scores
            model = get_embedding_model(self._embedding_model_name)
            query_embedding = model.encode([query_text], convert_to_numpy=True)[0]
            embedding_raw = np.dot(embeddings, query_embedding)

            # Normalize embeddings to [0, 1]
            embedding_min = embedding_raw.min()
            embedding_max = embedding_raw.max()
            embedding_normalized = (embedding_raw - embedding_min) / (embedding_max - embedding_min + 1e-10)

            # Combine: alpha*BM25 + (1-alpha)*embeddings
            scores = alpha * bm25_scores + (1 - alpha) * embedding_normalized

        else:
            raise ValueError(f"Unknown method: {method}. Use 'embeddings', 'bm25', or 'hybrid'")

        # Get top matches above threshold
        matches = []
        for idx, score in enumerate(scores):
            if score >= similarity_threshold:
                category, type_name = type_names[idx]
                matches.append((type_name, category, score))

        matches.sort(key=lambda x: x[2], reverse=True)

        # Split by category (from similarity-based extraction)
        similarity_nodes = []
        similarity_rels = []

        for type_name, category, sim in matches:
            if category == 'node':
                if type_name not in similarity_nodes and type_name not in explicit_nodes:
                    similarity_nodes.append(type_name)
            elif category == 'rel':
                if type_name not in similarity_rels and type_name not in explicit_rels:
                    similarity_rels.append(type_name)

        # Merge: Explicit first (Tier 1), then similarity-based (Tier 2)
        node_types = explicit_nodes + similarity_nodes
        rel_types = explicit_rels + similarity_rels

        if explicit_nodes:
            logger.info(f"🔍 Stage 1 - Explicit match: nodes={explicit_nodes}, rels={explicit_rels}")
        logger.info(f"🔍 Stage 1 - After embedding expansion: nodes={node_types}, rels={rel_types}")

        result = {
            'node_types': node_types,
            'relationship_types': rel_types
        }

        # Include detailed scores if requested
        if return_scores:
            # Build score dictionaries - include ALL types with scores, even below threshold
            node_scores = {}
            rel_scores = {}

            # First, add all types from similarity scoring (including below threshold)
            for idx, score in enumerate(scores):
                category, type_name = type_names[idx]
                if category == 'node':
                    node_scores[type_name] = {
                        'score': float(score),
                        'tier': 'explicit' if type_name in explicit_nodes else 'similarity',
                        'extracted': type_name in node_types,
                        'above_threshold': bool(score >= similarity_threshold)  # Convert to Python bool
                    }
                elif category == 'rel':
                    rel_scores[type_name] = {
                        'score': float(score),
                        'tier': 'explicit' if type_name in explicit_rels else 'similarity',
                        'extracted': type_name in rel_types,
                        'above_threshold': bool(score >= similarity_threshold)  # Convert to Python bool
                    }

            # Override tier for explicit types (they may have similarity scores too)
            for node in explicit_nodes:
                if node in node_scores:
                    node_scores[node]['tier'] = 'explicit'
                    node_scores[node]['extracted'] = True
                else:
                    # Shouldn't happen, but just in case
                    node_scores[node] = {
                        'score': 1.0,  # Perfect score for explicit matches
                        'tier': 'explicit',
                        'extracted': True,
                        'above_threshold': True
                    }

            for rel in explicit_rels:
                if rel in rel_scores:
                    rel_scores[rel]['tier'] = 'explicit'
                    rel_scores[rel]['extracted'] = True
                else:
                    rel_scores[rel] = {
                        'score': 1.0,
                        'tier': 'explicit',
                        'extracted': True,
                        'above_threshold': True
                    }

            result['node_scores'] = node_scores
            result['rel_scores'] = rel_scores
            result['threshold'] = similarity_threshold
            result['method'] = method
            result['alpha'] = alpha

        return result

    async def get_context_for_query(
        self,
        query_text: str,
        format: str = 'text',
        include_paths: bool = True
    ) -> Dict[str, Any]:
        """
        ONE-STOP method: Extract types, get schema, discover paths.

        This is the main API for CoT workflows!

        Args:
            query_text: Natural language query
            format: 'text' or 'dict'
            include_paths: Whether to discover paths

        Returns:
            {
                'extracted_types': {'node_types': [...], 'relationship_types': [...]},
                'schema_context': "..." (formatted schema),
                'paths_context': "..." (formatted paths),
                'cache_stats': {...}
            }

        Example:
            context = await manager.get_context_for_query("What functions call Main?")
            # Use in LLM prompt:
            prompt = f"{context['schema_context']}\n\n{context['paths_context']}\n\nQuery: ..."
        """
        # Wait for schema
        if self._loading or not self._reconciled_schema:
            logger.info("⏳ Waiting for schema...")
            await self._load_event.wait()

        if not self._reconciled_schema:
            return {
                'extracted_types': {'node_types': [], 'relationship_types': []},
                'schema_context': '',
                'paths_context': '',
                'cache_stats': self.get_cache_stats()
            }

        # Step 1: Extract types
        extracted = self.extract_types_from_query(query_text)

        # Step 2: Get schema slice
        schema_context = await self.get_context_relevant_schema(
            node_types=extracted['node_types'],
            relationship_types=extracted['relationship_types'],
            format=format
        )

        # Step 3: Discover paths (if requested)
        paths_context = ""
        if include_paths and len(extracted['node_types']) >= 2:
            logger.info(f"🛤️  Discovering paths...")

            for i, source in enumerate(extracted['node_types']):
                for target in extracted['node_types'][i+1:]:
                    await self.get_paths_between(source, target, max_depth=3)
                    await self.get_paths_between(target, source, max_depth=3)

            paths_context = await self.get_relevant_paths_for_nodes(
                node_types=extracted['node_types'],
                format='text'
            )

        return {
            'extracted_types': extracted,
            'schema_context': schema_context,
            'paths_context': paths_context if paths_context else "No paths discovered.",
            'cache_stats': self.get_cache_stats()
        }

    def _get_relationships_for_nodes(self, node_types: List[str]) -> List[str]:
        """
        Get ALL relationships that connect the given node types based on valid node pairs.

        This ensures complete graph connectivity information regardless of query wording.
        Instead of using semantic similarity to filter relationships, we use the actual
        valid node pairs from the reconciled schema to determine which relationships exist
        between the extracted nodes.

        Args:
            node_types: List of node type names (e.g., ['Function', 'Type'])

        Returns:
            List of relationship type names that connect any of the given nodes

        Example:
            For nodes=['Function', 'Type']:
            - IMPLEMENTS has valid pairs with (Function, Type) → Include ✅
            - CONTAINS has valid pairs with (Function, Block) → Include ✅
            - CALLS has valid pairs with (Function, Function) → Include ✅
        """
        if not node_types:
            return []

        node_set = set(node_types)

        # Check ALL relationships and include if ANY valid pair connects our nodes
        relationship_types = [
            rel_type
            for rel_type, rel_info in self._reconciled_schema.get('relationships', {}).items()
            if any(pair.get('from') in node_set or pair.get('to') in node_set
                   for pair in rel_info.get('valid_pairs', []))
        ]

        logger.info(f"🔗 Valid pair-based extraction: {len(relationship_types)} relationships connect {len(node_types)} nodes")

        return relationship_types

    async def get_schema_for_subquery(
        self,
        subquery_text: str,
        format: str = 'text',
        max_path_depth: int = 5,
        cypher_server: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        **PRIMARY API**: Get schema context for a subquery with optimal extraction.

        Uses hybrid extraction for NODE types + valid pair-based relationship extraction:
        - NODE extraction: hybrid (85% embeddings + 15% BM25) with threshold 0.60
        - RELATIONSHIP extraction: valid pair-based (ALL relationships connecting the nodes)

        This approach ensures:
        - Accurate node extraction based on query semantics
        - Complete relationship information regardless of query wording
        - No missed relationships due to embedding semantic mismatches

        Process:
        1. Extract node types (embedding-based hybrid method)
        2. Get ALL relationships connecting those nodes (valid pair-based)
        3. Get schema context for extracted types
        4. Discover and cache paths between node types
        5. Return complete schema package for Cypher generation

        Args:
            subquery_text: Natural language subquery or query
            format: 'text' (for LLM prompts) or 'dict' (for programmatic use)
            max_path_depth: Maximum path depth to discover (default 5)
            cypher_server: Optional cypher server to use for path discovery (defaults to self.cypher_server)

        Returns:
            {
                'node_types': ['Function', 'Type', ...],
                'relationship_types': ['CALLS', 'DECLARES', ...],
                'node_schemas': {node_type: {properties, description, ...}},
                'relationship_schemas': {rel_type: {from, to, description, ...}},
                'paths': [{'from': 'Function', 'to': 'Type', 'rels': ['DECLARES'], ...}],
                'schema_text': "formatted schema for LLM prompt",
                'extraction_method': 'hybrid',
                'extraction_params': {'threshold': 0.60, 'alpha': 0.15}
            }

        Example:
            # In CoT agent node:
            result = await schema_manager.get_schema_for_subquery(
                "locate Function node F where F.name='CreateWorkers'"
            )

            # Use in Cypher generation prompt:
            prompt = f\"\"\"
            {result['schema_text']}

            Generate Cypher for: {subquery_text}
            \"\"\"
        """
        # Wait for schema if still loading
        if self._loading or not self._reconciled_schema:
            logger.info("⏳ Waiting for schema...")
            await self._load_event.wait()

        if not self._reconciled_schema:
            return self._empty_schema_response()

        # Step 1: Extract NODE types using optimal hybrid method with EnrichmentDescription
        # NOTE: We only use embeddings for NODE extraction, not relationships
        extracted = self.extract_types_from_query(
            query_text=subquery_text,
            similarity_threshold=0.60,
            top_k=5,
            method='hybrid',
            alpha=0.15
        )

        node_types = extracted['node_types']
        # DEPRECATED: relationship_types = extracted['relationship_types']
        # The embedding-based relationship extraction is unreliable (e.g., "instantiated"
        # doesn't match "IMPLEMENTS" or "CONTAINS"). Instead, we use valid_pairs.

        # Step 1b: Get ALL relationships that connect the extracted nodes (valid pair-based)
        # This ensures complete graph connectivity regardless of query wording
        relationship_types = self._get_relationships_for_nodes(node_types)

        logger.info(f"📊 Stage 2 - Embedding-based rels (deprecated): nodes={extracted['node_types']}, rels={extracted['relationship_types']}")
        logger.info(f"✅ Stage 2 - Valid pair-based rels (FINAL): nodes={node_types}, rels={relationship_types}")

        # Step 2: Get detailed schema for extracted types
        # Note: reconciled_schema only contains types that actually exist in CPG (count > 0)
        node_schemas = {}
        for node_type in node_types:
            if node_type in self._reconciled_schema.get('nodes', {}):
                node_schemas[node_type] = self._reconciled_schema['nodes'][node_type]

        relationship_schemas = {}
        for rel_type in relationship_types:
            if rel_type in self._reconciled_schema.get('relationships', {}):
                relationship_schemas[rel_type] = self._reconciled_schema['relationships'][rel_type]
            else:
                # Relationship was extracted but doesn't exist in CPG (not in reconciled schema)
                logger.warning(f"⚠️  Skipping {rel_type}: not in reconciled schema (doesn't exist in CPG)")

        # Update relationship_types to only include those that exist in reconciled schema
        relationship_types = list(relationship_schemas.keys())

        # Step 3: Discover and cache paths between node types
        paths = []
        if len(node_types) >= 2:
            logger.info(f"🛤️  Discovering paths between {len(node_types)} node types...")

            for source in node_types:
                for target in node_types:
                    if source != target:
                        # Use extracted relationships to filter (faster + more relevant)
                        discovered_paths = await self.get_paths_between(
                            source=source,
                            target=target,
                            relationship_types=relationship_types if relationship_types else None,
                            max_depth=max_path_depth,
                            cypher_server=cypher_server
                        )

                        for path in discovered_paths:
                            paths.append({
                                'from': source,
                                'to': target,
                                'rels': path['rels'],
                                'via': path.get('via', []),
                                'depth': path['depth']
                            })

            logger.info(f"   ✅ Discovered {len(paths)} path patterns")

        # Step 4: Format schema text for LLM
        schema_text = self._format_schema_for_llm(
            node_schemas=node_schemas,
            relationship_schemas=relationship_schemas,
            paths=paths
        )

        return {
            'node_types': node_types,
            'relationship_types': relationship_types,
            'node_schemas': node_schemas,
            'relationship_schemas': relationship_schemas,
            'paths': paths,
            'schema_text': schema_text if format == 'text' else '',
            'extraction_method': 'hybrid',
            'extraction_params': {
                'threshold': 0.60,
                'alpha': 0.15,
                'top_k': 5
            },
            'cache_stats': self.get_cache_stats()
        }

    def _empty_schema_response(self) -> Dict[str, Any]:
        """Return empty schema response when schema not ready."""
        return {
            'node_types': [],
            'relationship_types': [],
            'node_schemas': {},
            'relationship_schemas': {},
            'paths': [],
            'schema_text': '',
            'extraction_method': 'hybrid',
            'extraction_params': {'threshold': 0.60, 'alpha': 0.15},
            'cache_stats': self.get_cache_stats()
        }

    def _format_schema_for_llm(
        self,
        node_schemas: Dict,
        relationship_schemas: Dict,
        paths: List[Dict]
    ) -> str:
        """Format schema into LLM-friendly text."""
        lines = []

        lines.append("=== CPG Schema Context ===")
        lines.append("")

        # Node types
        if node_schemas:
            lines.append("Node Types:")
            for node_type, schema in node_schemas.items():
                lines.append(f"  • {node_type}")
                if 'description' in schema:
                    lines.append(f"      {schema['description']}")
                if 'actual_properties' in schema:
                    props = schema['actual_properties'][:5]  # Top 5 properties
                    lines.append(f"      Properties: {', '.join(props)}")
            lines.append("")

        # Relationship types
        if relationship_schemas:
            lines.append("Relationship Types:")
            for rel_type, schema in relationship_schemas.items():
                from_labels = schema.get('actual_from_labels', [])
                to_labels = schema.get('actual_to_labels', [])
                from_str = ', '.join(from_labels[:2]) if from_labels else '?'
                to_str = ', '.join(to_labels[:2]) if to_labels else '?'

                lines.append(f"  • {rel_type}: ({from_str})-[:{rel_type}]->({to_str})")
                if 'description' in schema:
                    lines.append(f"      {schema['description']}")
            lines.append("")

        # Path patterns
        if paths:
            lines.append("Path Patterns (cached):")
            # Group by depth
            depth_groups = {}
            for path in paths:
                depth = path['depth']
                if depth not in depth_groups:
                    depth_groups[depth] = []
                depth_groups[depth].append(path)

            for depth in sorted(depth_groups.keys()):
                lines.append(f"  Depth {depth}:")
                for path in depth_groups[depth][:10]:  # Max 10 paths per depth
                    rel_chain = " → ".join(path['rels'])
                    via_str = f" (via {', '.join(path['via'])})" if path.get('via') else ""
                    lines.append(f"      ({path['from']})-[{rel_chain}]->({path['to']}){via_str}")
            lines.append("")

        return '\n'.join(lines)

    def is_ready(self) -> bool:
        """Check if schema is loaded and ready"""
        return self._full_schema is not None

    def get_full_schema(self) -> Optional[Dict]:
        """Get entire parsed schema (for debugging/export)"""
        return self._full_schema

    async def save_to_file(self, filepath: str):
        """Save parsed schema to JSON file for inspection"""
        if self._loading:
            await self._load_event.wait()

        if self._full_schema:
            with open(filepath, 'w') as f:
                json.dump(self._full_schema, f, indent=2, default=str)
            logger.info(f"💾 Schema saved to {filepath}")
        else:
            logger.warning("⚠️ No schema to save")

    async def shutdown(self):
        """Save cache and show statistics before shutdown"""
        await self._save_path_cache()

        total_requests = self._cache_hits + self._cache_misses
        if total_requests > 0:
            hit_rate = (self._cache_hits / total_requests) * 100
            logger.info(f"📊 Path Cache Statistics:")
            logger.info(f"   • Total requests: {total_requests}")
            logger.info(f"   • Cache hits: {self._cache_hits} ({hit_rate:.1f}%)")
            logger.info(f"   • Cache misses: {self._cache_misses}")
            logger.info(f"   • Unique paths cached: {len(self._path_cache)}")

    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        total = self._cache_hits + self._cache_misses
        return {
            'total_requests': total,
            'cache_hits': self._cache_hits,
            'cache_misses': self._cache_misses,
            'hit_rate': (self._cache_hits / total * 100) if total > 0 else 0,
            'cached_paths': sum(len(targets) for targets in self._path_cache.values())
        }

    async def get_relevant_paths_for_nodes(
        self,
        node_types: List[str],
        format: str = 'text'
    ) -> str:
        """
        Format already-cached paths for a set of node types (for LLM context).

        ⚠️ IMPORTANT: This method does NOT discover new paths!

        It only formats paths that are already in the cache. This ensures truly
        on-demand discovery where paths are only discovered when specifically
        needed by a subquery.

        CORRECT USAGE PATTERN:
        1. Extract SPECIFIC source/target from subquery
        2. Call get_paths_between(source, target) for ONLY that pair
        3. Use this method to format the cached results

        WRONG USAGE PATTERN:
        ❌ Don't call this with all extracted nodes expecting it to discover paths
        ❌ That would trigger combinatorial discovery (N×N paths)

        Args:
            node_types: List of node types to format cached paths for
            format: 'text' (human-readable) or 'dict' (structured)

        Returns:
            Formatted path information for cached paths only

        Example output (text format):
        '''
        Paths from Function:
          → Type: REFERENCES (depth 1), IMPLEMENTS→IMPLEMENTS (depth 2)

        Paths from Type:
          → Variable: CONTAINS (depth 1)
        '''
        """
        if format == 'dict':
            result = {}
            for source in node_types:
                # Only return paths that are ALREADY CACHED
                if source in self._path_cache:
                    for target, paths in self._path_cache[source].items():
                        if target in node_types and paths:
                            if source not in result:
                                result[source] = {}
                            result[source][target] = paths
            return result

        # Text format for LLM context - only cached paths
        lines = []
        for source in node_types:
            # Only look at cached paths, don't discover new ones
            if source not in self._path_cache:
                continue

            source_paths = []

            # Directly iterate over cached targets (no unnecessary loops)
            for target, paths in self._path_cache[source].items():
                # Only include if target is in the requested node types
                if target not in node_types or not paths:
                    continue

                # Format paths: "Variable: CONTAINS (depth 1), REFERENCES (depth 1)"
                path_strs = []
                for path in paths[:3]:  # Show top 3 paths
                    rel_str = '→'.join(path['rels'])
                    path_strs.append(f"{rel_str} (depth {path['depth']})")

                if path_strs:
                    source_paths.append(f"  → {target}: {', '.join(path_strs)}")

            if source_paths:
                lines.append(f"Paths from {source}:")
                lines.extend(source_paths)
                lines.append("")

        return '\n'.join(lines) if lines else "No paths found between specified nodes."
