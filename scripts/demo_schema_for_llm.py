"""
Demo: Using Schema Manager for LLM-Guided Query Generation

Shows the CORRECT on-demand usage pattern:
1. Process each subquery individually
2. Extract SPECIFIC source/target for that subquery
3. Call get_paths_between() for ONLY that pair
4. Use get_relevant_paths_for_nodes() to format cached paths
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.core.workflow.dynamic_schema_manager import DynamicSchemaManager
from test_dynamic_schema_simple import SubprocessCypherServer


async def demo_on_demand_discovery():
    """Demonstrate CORRECT on-demand schema usage"""

    print("=" * 80)
    print("🎯 Demo: On-Demand Schema-Guided Query Generation")
    print("=" * 80)
    print()

    # Initialize schema manager
    neo4j_config = "/opt/genpod/neo4j_config.json"
    cypher_server = SubprocessCypherServer(neo4j_config)
    schema_manager = DynamicSchemaManager(cypher_server, cache_file="/tmp/demo_cache.json")

    await schema_manager.initialize_background()
    print()

    # Example query
    print("Example Query:")
    print("-" * 80)

    query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"

    subqueries = [
        "locate Function node F where F.name='CreateWorkers' and F is contained in a Type node named 'WorkerFactory'",
        "collect all CALLS edges from F to constructor Functions ctorFn and for each ctorFn locate its declaring Type node C and retrieve C.name",
        "locate all return-statement Statement nodes within F",
        "locate Variable nodes V declared in F whose initial_value expressions include new instantiations"
    ]

    print(f"Query: {query}")
    print()
    print("Subqueries:")
    for i, sq in enumerate(subqueries, 1):
        print(f"  {i}. {sq}")
    print()

    # Process EACH subquery individually (on-demand)
    print("=" * 80)
    print("Step 1: Process Subqueries ONE AT A TIME (On-Demand Discovery)")
    print("=" * 80)
    print()

    # Subquery 1: "locate Function node F... in a Type node"
    print("Subquery 1: Locate Function within Type")
    print("-" * 80)
    print("Extracted nodes: Type, Function")
    print("Need path: Type → Function")
    print()

    # Discover ONLY the specific path needed
    paths = await schema_manager.get_paths_between("Type", "Function")
    if paths:
        print(f"✅ Found {len(paths)} path(s):")
        for p in paths[:2]:
            rels = ' → '.join(p['rels'])
            print(f"   • {rels} (depth {p['depth']})")
    else:
        print("⚠️ No path found (Type doesn't CONTAIN Function in this CPG)")
    print()

    # Subquery 2: "CALLS edges from F to constructor Functions... to Type node"
    print("Subquery 2: Function CALLS constructors, get declaring Type")
    print("-" * 80)
    print("Extracted nodes: Function, Type")
    print("Need path: Function → Type")
    print()

    paths = await schema_manager.get_paths_between("Function", "Type")
    if paths:
        print(f"✅ Found {len(paths)} path(s):")
        for p in paths[:3]:
            rels = ' → '.join(p['rels'])
            print(f"   • {rels} (depth {p['depth']})")
    else:
        print("⚠️ No path found")
    print()

    # Subquery 3: "return-statement Statement nodes within F"
    print("Subquery 3: Find Statement nodes within Function")
    print("-" * 80)
    print("Extracted nodes: Function, Statement")
    print("Need path: Function → Statement")
    print()

    paths = await schema_manager.get_paths_between("Function", "Statement")
    if paths:
        print(f"✅ Found {len(paths)} path(s):")
        for p in paths[:2]:
            rels = ' → '.join(p['rels'])
            print(f"   • {rels} (depth {p['depth']})")
    else:
        print("⚠️ No path found")
    print()

    # Step 2: Now format ALL cached paths for LLM context
    print("=" * 80)
    print("Step 2: Format Cached Paths for LLM Context (No Discovery!)")
    print("=" * 80)
    print()

    print("Using get_relevant_paths_for_nodes() to FORMAT cached paths...")
    print("(This does NOT trigger any new APOC calls)")
    print()

    cached_nodes = ["Type", "Function", "Statement"]
    relevant_paths = await schema_manager.get_relevant_paths_for_nodes(cached_nodes)
    print(relevant_paths)

    # Step 3: Build LLM prompt with path info
    print("=" * 80)
    print("Step 3: LLM Prompt with Schema Context (Example)")
    print("=" * 80)
    print()

    # Get node properties for the first subquery
    node_properties = {}
    for node in ["Type", "Function"]:
        if node in schema_manager._full_schema.get('node_properties', {}):
            props = schema_manager._full_schema['node_properties'][node]
            # Get indexed properties (most important)
            indexed = [p for p, meta in props.items() if meta.get('indexed')]
            node_properties[node] = indexed[:5]  # Top 5

    llm_prompt = f"""Generate a Cypher query to answer this subquery:

Subquery: {subqueries[0]}

CPG Schema Context (from cache):
{relevant_paths}

Node Properties:
"""
    for node, props in node_properties.items():
        llm_prompt += f"  {node}: {', '.join(props)}\n"

    llm_prompt += """
Requirements:
- Use the exact relationship paths shown above
- Match nodes by their indexed properties
- Return the requested information

Cypher Query:"""

    print(llm_prompt)
    print()

    # Show cache structure
    print("=" * 80)
    print("📊 Cache Structure (Nested: {source: {target: [paths]}})")
    print("=" * 80)
    print()

    print("Current cache contents:")
    for source, targets in schema_manager._path_cache.items():
        print(f"\n{source}:")
        for target, paths in targets.items():
            print(f"  → {target}: {len(paths)} path(s)")

    print()

    # Show statistics
    stats = schema_manager.get_cache_stats()
    print("=" * 80)
    print("📈 Cache Statistics")
    print("=" * 80)
    print()
    print(f"  Total path lookups: {stats['total_requests']}")
    print(f"  Cache hits: {stats['cache_hits']} ({stats['hit_rate']:.1f}%)")
    print(f"  Paths cached: {stats['cached_paths']}")
    print()

    # Show benefits
    print("=" * 80)
    print("💡 Key Benefits of On-Demand Discovery")
    print("=" * 80)
    print()

    print("✅ ADVANTAGES:")
    print("   1. Only 3 APOC calls (one per specific path needed)")
    print("   2. No wasted computation on unused paths")
    print("   3. Cache builds organically based on actual queries")
    print("   4. Scales to any graph size (no upfront pre-computation)")
    print("   5. get_relevant_paths_for_nodes() only FORMATS cached data")
    print()

    print("❌ OLD APPROACH (would do combinatorial discovery):")
    print("   • Would call get_paths_between() for ALL node combinations")
    print("   • 12 APOC calls for 4 node types (4×3 = 12 combinations)")
    print("   • Many discovered paths would never be used")
    print("   • Initial query processing would be very slow")
    print()

    await schema_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(demo_on_demand_discovery())
