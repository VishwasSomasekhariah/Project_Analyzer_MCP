"""
APOC Procedure Cache System

Queries Neo4j once at workflow initialization to cache all APOC procedures,
their signatures, and descriptions. Organizes by category for easy lookup.

This cache is purely data-driven and doesn't assume what procedures exist.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime


class APOCProcedureCache:
    """
    Cache for APOC procedures retrieved from Neo4j.
    Initialized once per workflow and stored in memory.
    """

    def __init__(self, cache_file: Optional[Path] = None):
        """
        Initialize the APOC procedure cache.

        Args:
            cache_file: Optional path to save/load cache from disk
        """
        self.cache_file = cache_file or Path("/opt/genpod/.cache/apoc_procedures.json")
        self.procedures: Dict[str, Dict] = {}
        self.categories: Dict[str, List[str]] = {}
        self.initialized = False
        self.metadata = {}

    async def initialize(self, cypher_server, relevant_categories: Optional[List[str]] = None) -> Dict:
        """
        Initialize cache by querying Neo4j for APOC procedures.

        Strategy:
        1. Fetch all procedure names (fast, small response)
        2. Group by category
        3. Fetch details only for relevant categories (selective caching)

        Args:
            cypher_server: CypherServerInstance (from src.core.workflow.cypher_server_pool)
            relevant_categories: Optional list of categories to cache. If None, uses default CPG-relevant set.

        Returns:
            Dictionary with cache statistics
        """
        if self.initialized:
            return self._get_cache_stats()

        # Default: Only cache categories relevant for CPG RAG workflows
        if relevant_categories is None:
            relevant_categories = [
                'apoc.path',      # Path traversal
                'apoc.paths',     # Path operations
                'apoc.algo',      # Graph algorithms
                'apoc.graph',     # Graph operations
                'apoc.meta',      # Schema introspection
                'apoc.schema',    # Schema operations
                'apoc.node',      # Node operations
                'apoc.nodes',     # Node utilities
                'apoc.rel',       # Relationship operations
                'apoc.cypher',    # Cypher utilities
                'apoc.coll',      # Collection utilities
                'apoc.map',       # Map utilities
                'apoc.neighbors', # Neighbor operations
            ]

        print("Initializing APOC procedure cache...")

        # Step 1: Fetch all procedure names (fast!)
        names_query = """
        CALL apoc.help("") YIELD name
        RETURN name
        ORDER BY name
        """

        print("  [1/2] Fetching all procedure names...", flush=True)

        try:
            print("    Executing names query...", flush=True)
            result = await cypher_server.execute_query(names_query, limit=1000)
            print(f"    Got result: status={result.get('status')}", flush=True)

            if result.get('status') == 'error':
                error_msg = result.get('error', '')
                print(f"  ⚠️  Error: {error_msg}")
                all_names = []
            else:
                all_names = [row['name'] for row in result.get('data', [])]
                print(f"  ✓ Found {len(all_names)} procedures")

        except Exception as e:
            print(f"  ⚠️  Exception during fetch: {e}")
            all_names = []

        # Step 2: Group by category
        categories_map = {}
        for name in all_names:
            category = self._extract_category(name)
            if category not in categories_map:
                categories_map[category] = []
            categories_map[category].append(name)

        print(f"  ✓ Grouped into {len(categories_map)} categories")

        # Step 3: Fetch details for grouped categories (batched queries)
        print(f"  [2/2] Fetching details for {len(relevant_categories)} relevant categories...")
        all_procedures = []

        # Group categories into logical batches for efficient fetching
        category_groups = {
            'path_ops': ['apoc.path', 'apoc.paths', 'apoc.algo', 'apoc.neighbors'],
            'graph_schema': ['apoc.graph', 'apoc.meta', 'apoc.schema'],
            'node_rel_ops': ['apoc.node', 'apoc.nodes', 'apoc.rel'],
            'utilities': ['apoc.cypher', 'apoc.coll', 'apoc.map'],
        }

        print(f"    Fetching in {len(category_groups)} grouped queries...")

        for i, (group_name, group_categories) in enumerate(category_groups.items(), 1):
            # Build WHERE clause for multiple categories
            # Example: WHERE name STARTS WITH 'apoc.path.' OR name STARTS WITH 'apoc.paths.'
            where_clauses = [f"name STARTS WITH '{cat}.'" for cat in group_categories]
            where_clause = " OR ".join(where_clauses)

            group_query = f"""
            CALL apoc.help("") YIELD name, text, signature, type
            WHERE {where_clause}
            RETURN name, text, signature, type
            ORDER BY name
            """

            try:
                # Larger limit for grouped queries (could have 100+ procedures)
                result = await cypher_server.execute_query(group_query, limit=200)

                if result.get('status') == 'error':
                    print(f"    [{i}/{len(category_groups)}] ⚠️  {group_name}: {result.get('error')}")
                    continue

                group_procs = self._parse_neo4j_result(result)
                all_procedures.extend(group_procs)

                cats_str = ", ".join(group_categories)
                print(f"    [{i}/{len(category_groups)}] {group_name} ({cats_str}): {len(group_procs)} procedures", flush=True)

            except Exception as e:
                print(f"    [{i}/{len(category_groups)}] ⚠️  {group_name}: {e}")

        print(f"  ✓ Fetched details for {len(all_procedures)} procedures")

        try:
            # Build cache from all fetched procedures
            self._build_cache(all_procedures)

            # Save to disk
            self._save_to_disk()

            self.initialized = True

            stats = self._get_cache_stats()
            print(f"✓ APOC cache initialized: {stats['total_procedures']} procedures, {stats['total_categories']} categories")

            return stats

        except Exception as e:
            print(f"Error initializing APOC cache: {e}")
            # Try loading from disk as fallback
            if self.cache_file.exists():
                print("Loading from cached file...")
                self._load_from_disk()
                self.initialized = True
                return self._get_cache_stats()
            raise

    def _parse_neo4j_result(self, result: Dict) -> List[Dict]:
        """
        Parse cypher_server result into list of procedure dictionaries.

        Args:
            result: Dict from cypher_server.execute_query() with keys: status, data, error

        Returns:
            List of procedure dictionaries
        """
        procedures = []

        try:
            # Check if query was successful
            if result.get('status') == 'error':
                print(f"Error querying APOC procedures: {result.get('error')}")
                return procedures

            # Extract data (list of result rows)
            data = result.get('data', [])

            # Each row should have: name, text, signature, type
            for row in data:
                if isinstance(row, dict):
                    proc = {
                        'name': row.get('name', ''),
                        'text': row.get('text', ''),
                        'signature': row.get('signature', ''),
                        'type': row.get('type', 'procedure')
                    }

                    # Only add if it has a valid name
                    if proc['name'] and proc['name'].startswith('apoc.'):
                        procedures.append(proc)

        except Exception as e:
            print(f"Warning: Could not parse result: {e}")

        return procedures

    def _build_cache(self, procedures_data: List[Dict]):
        """Build internal cache structures from procedure data."""
        for proc in procedures_data:
            name = proc.get('name', '')
            if not name or not name.startswith('apoc.'):
                continue

            # Store procedure details
            self.procedures[name] = {
                'name': name,
                'signature': proc.get('signature', ''),
                'description': proc.get('text', ''),
                'type': proc.get('type', 'procedure'),
                'category': self._extract_category(name),
                'subcategory': self._extract_subcategory(name)
            }

            # Organize by category
            category = self._extract_category(name)
            if category not in self.categories:
                self.categories[category] = []
            self.categories[category].append(name)

        # Store metadata
        self.metadata = {
            'initialized_at': datetime.utcnow().isoformat(),
            'total_procedures': len(self.procedures),
            'total_categories': len(self.categories)
        }

    def _extract_category(self, name: str) -> str:
        """Extract main category from procedure name (e.g., 'apoc.path')."""
        parts = name.split('.')
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return name

    def _extract_subcategory(self, name: str) -> Optional[str]:
        """Extract subcategory if it exists (e.g., 'expandConfig' from 'apoc.path.expandConfig')."""
        parts = name.split('.')
        if len(parts) >= 3:
            return parts[2]
        return None

    def get_by_category(self, category: str) -> List[Dict]:
        """
        Get all procedures in a category.

        Args:
            category: Category name (e.g., 'apoc.path', 'apoc.algo')

        Returns:
            List of procedure dictionaries
        """
        procedure_names = self.categories.get(category, [])
        return [self.procedures[name] for name in procedure_names]

    def get_category_by_prefix(self, prefix: str) -> List[Dict]:
        """
        Get procedures by category prefix dynamically.

        Args:
            prefix: Category prefix (e.g., 'apoc.path')

        Returns:
            List of matching procedures
        """
        results = []
        for name, proc in self.procedures.items():
            if name.startswith(prefix):
                results.append(proc)
        return results

    def get_all_categories(self) -> Dict[str, int]:
        """
        Get all discovered categories with procedure counts.
        Returns what actually exists, not what we assume.

        Returns:
            Dictionary of {category: count}
        """
        return {cat: len(procs) for cat, procs in self.categories.items()}

    def get_procedures_by_category(self, category: str) -> List[Dict]:
        """
        Alias for get_by_category for API consistency.
        """
        return self.get_by_category(category)

    def get_total_procedures(self) -> int:
        """
        Get total number of procedures in cache.
        """
        return len(self.procedures)

    def get_procedure(self, name: str) -> Optional[Dict]:
        """
        Get a specific procedure by name.

        Args:
            name: Full procedure name (e.g., 'apoc.path.expandConfig')

        Returns:
            Procedure dictionary or None
        """
        return self.procedures.get(name)

    def search(self, keyword: str) -> List[Dict]:
        """
        Search procedures by keyword in name or description.

        Args:
            keyword: Search term

        Returns:
            List of matching procedures
        """
        keyword_lower = keyword.lower()
        results = []

        for proc in self.procedures.values():
            if (keyword_lower in proc['name'].lower() or
                keyword_lower in proc['description'].lower()):
                results.append(proc)

        return results

    def get_relevant_for_path_discovery(self) -> Dict[str, List[Dict]]:
        """
        Get procedures most relevant for path discovery and graph traversal.
        Uses keyword search to find relevant procedures, not hardcoded categories.

        Returns:
            Dictionary organized by discovered relevance
        """
        # Search by keywords instead of assuming categories exist
        relevant_keywords = {
            'path_traversal': ['path', 'traverse', 'expand', 'walk'],
            'algorithms': ['algo', 'allSimplePaths', 'dijkstra', 'spanning'],
            'graph_operations': ['graph', 'subgraph', 'nodes', 'relationships'],
            'schema_introspection': ['meta', 'schema', 'type', 'relationship'],
        }

        results = {}
        for use_case, keywords in relevant_keywords.items():
            matches: Set[str] = set()
            for keyword in keywords:
                found = self.search(keyword)
                matches.update(proc['name'] for proc in found)

            results[use_case] = [self.procedures[name] for name in matches if name in self.procedures]

        return results

    def format_for_llm(self, category: str) -> str:
        """
        Format procedures in a category for LLM consumption.

        Args:
            category: Category to format

        Returns:
            Formatted string with procedure signatures and descriptions
        """
        procedures = self.get_by_category(category)

        if not procedures:
            return f"No procedures found in category: {category}"

        output = [f"## {category} Procedures\n"]

        for proc in procedures:
            output.append(f"### {proc['name']}")
            output.append(f"**Signature:** `{proc['signature']}`")
            output.append(f"**Description:** {proc['description']}")
            output.append("")

        return "\n".join(output)

    def format_relevant_for_prompt(self) -> str:
        """
        Format relevant APOC procedures for inclusion in prompts.

        Returns:
            Formatted string with procedures organized by use case
        """
        relevant = self.get_relevant_for_path_discovery()

        output = ["# Available APOC Procedures for Path Discovery\n"]

        for use_case, procedures in relevant.items():
            if not procedures:
                continue

            output.append(f"## {use_case.replace('_', ' ').title()}\n")

            for proc in procedures:
                output.append(f"- **{proc['name']}**")
                output.append(f"  - Signature: `{proc['signature']}`")
                output.append(f"  - {proc['description']}")
                output.append("")

        return "\n".join(output)

    def _get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        return {
            'total_procedures': len(self.procedures),
            'total_categories': len(self.categories),
            'categories': list(self.categories.keys()),
            'initialized': self.initialized,
            'metadata': self.metadata
        }

    def _save_to_disk(self):
        """Save cache to disk."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        cache_data = {
            'procedures': self.procedures,
            'categories': self.categories,
            'metadata': self.metadata
        }

        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)

        print(f"✓ APOC cache saved to: {self.cache_file}")

    def _load_from_disk(self):
        """Load cache from disk."""
        if not self.cache_file.exists():
            raise FileNotFoundError(f"Cache file not found: {self.cache_file}")

        with open(self.cache_file, 'r') as f:
            cache_data = json.load(f)

        self.procedures = cache_data.get('procedures', {})
        self.categories = cache_data.get('categories', {})
        self.metadata = cache_data.get('metadata', {})
        self.initialized = True

        print(f"✓ APOC cache loaded from disk: {len(self.procedures)} procedures")


# Singleton instance
_apoc_cache: Optional[APOCProcedureCache] = None


def get_apoc_cache() -> APOCProcedureCache:
    """Get the global APOC cache instance."""
    global _apoc_cache
    if _apoc_cache is None:
        _apoc_cache = APOCProcedureCache()
    return _apoc_cache


async def initialize_apoc_cache(cypher_server) -> Dict:
    """
    Initialize the global APOC cache.
    Should be called once at workflow initialization.

    Args:
        cypher_server: CypherServerInstance (from src.core.workflow.cypher_server_pool)

    Returns:
        Cache statistics
    """
    cache = get_apoc_cache()
    return await cache.initialize(cypher_server)
