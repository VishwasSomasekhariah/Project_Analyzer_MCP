"""
Test Cypher Query Validator with real queries from benchmark results
"""

import json
from pathlib import Path
from src.core.workflow.cypher_query_validator import (
    create_default_validator,
    ValidationSeverity
)


def load_queries_from_benchmark(result_file: str) -> list:
    """Load queries from a benchmark result JSON file"""
    with open(result_file, 'r') as f:
        data = json.load(f)

    queries = data.get('query_history', [])
    return queries


def validate_query(validator, query: str, query_num: int):
    """Validate a single query and print results"""
    result = validator.validate(query)

    # Determine status
    if result.is_valid:
        status = "✅ VALID"
        color = "\033[92m"  # Green
    else:
        status = "❌ INVALID"
        color = "\033[91m"  # Red

    reset = "\033[0m"

    print(f"\n{color}{'='*80}{reset}")
    print(f"{color}Query #{query_num}: {status}{reset}")
    print(f"{color}{'='*80}{reset}")
    print(f"\nQuery:\n{query[:200]}{'...' if len(query) > 200 else ''}")

    # Show extracted components
    if result.extracted_nodes:
        print(f"\n📦 Nodes: {len(result.extracted_nodes)}")
        for alias, label, props in result.extracted_nodes[:5]:
            print(f"   ({alias or '_'}:{label})")
        if len(result.extracted_nodes) > 5:
            print(f"   ... and {len(result.extracted_nodes) - 5} more")

    if result.extracted_relationships:
        print(f"\n🔗 Edges: {len(result.extracted_relationships)}")
        for from_label, rel_type, to_label in result.extracted_relationships[:5]:
            print(f"   ({from_label})-[:{rel_type}]->({to_label})")
        if len(result.extracted_relationships) > 5:
            print(f"   ... and {len(result.extracted_relationships) - 5} more")

    # Show issues
    errors = result.get_errors()
    warnings = result.get_warnings()

    if errors:
        print(f"\n🔴 ERRORS ({len(errors)}):")
        for issue in errors:
            print(f"   • {issue.location}: {issue.message}")
            if issue.suggestion:
                print(f"     💡 {issue.suggestion}")

    if warnings:
        print(f"\n🟡 WARNINGS ({len(warnings)}):")
        for issue in warnings[:3]:  # Limit warnings
            print(f"   • {issue.location}: {issue.message}")
        if len(warnings) > 3:
            print(f"   ... and {len(warnings) - 3} more warnings")

    return result.is_valid


def test_benchmark_queries(result_file: str, max_queries: int = None):
    """Test all queries from a benchmark result file"""
    print("="*80)
    print(f" Testing Queries from: {Path(result_file).name}")
    print("="*80)

    validator = create_default_validator()
    queries = load_queries_from_benchmark(result_file)

    if max_queries:
        queries = queries[:max_queries]

    print(f"\nFound {len(queries)} queries to validate\n")

    results = []
    for i, query in enumerate(queries, 1):
        is_valid = validate_query(validator, query, i)
        results.append((i, query[:100], is_valid))

    # Print summary
    print("\n" + "="*80)
    print(" VALIDATION SUMMARY")
    print("="*80)

    valid_count = sum(1 for _, _, is_valid in results if is_valid)
    invalid_count = len(results) - valid_count

    print(f"\n✅ Valid queries:   {valid_count}/{len(results)} ({valid_count/len(results)*100:.1f}%)")
    print(f"❌ Invalid queries: {invalid_count}/{len(results)} ({invalid_count/len(results)*100:.1f}%)")

    if invalid_count > 0:
        print(f"\nInvalid queries:")
        for num, query_snippet, is_valid in results:
            if not is_valid:
                print(f"  #{num}: {query_snippet}...")

    return valid_count, invalid_count


def test_specific_queries():
    """Test specific problematic query patterns"""
    validator = create_default_validator()

    print("\n" + "="*80)
    print(" TESTING SPECIFIC QUERY PATTERNS")
    print("="*80)

    # Test 1: Invalid edge (Statement-IMPLEMENTS->Type)
    print("\n--- Test 1: Invalid cardinality (Statement-IMPLEMENTS->Type) ---")
    query1 = """
    MATCH (s:Statement)-[:IMPLEMENTS]->(instantiatedType:Type)
    RETURN instantiatedType.name
    """
    result1 = validator.validate(query1)
    print(f"Result: {'✅ VALID' if result1.is_valid else '❌ INVALID'}")
    for issue in result1.get_errors():
        print(f"  Error: {issue.message}")

    # Test 2: Invalid edge (File-CONTAINS->Function)
    print("\n--- Test 2: Invalid cardinality (File-CONTAINS->Function) ---")
    query2 = """
    MATCH (file:File)-[:CONTAINS]->(func:Function)
    RETURN func.name
    """
    result2 = validator.validate(query2)
    print(f"Result: {'✅ VALID' if result2.is_valid else '❌ INVALID'}")
    for issue in result2.get_errors():
        print(f"  Error: {issue.message}")

    # Test 3: Valid chain (Project->File->Type->Function)
    print("\n--- Test 3: Valid chain (Project->File->Type->Function) ---")
    query3 = """
    MATCH (project:Project)-[:CONTAINS]->(file:File)
          -[:CONTAINS]->(type:Type)
          -[:CONTAINS]->(func:Function)
    RETURN func.name
    """
    result3 = validator.validate(query3)
    print(f"Result: {'✅ VALID' if result3.is_valid else '❌ INVALID'}")
    for issue in result3.get_errors():
        print(f"  Error: {issue.message}")

    return result1.is_valid, result2.is_valid, result3.is_valid


def main():
    """Main test runner"""
    # Test with benchmark results
    benchmark_files = [
        "benchmark_results_lookup_query/run_2_output.json",
        "benchmark_results/run_1_output.json"  # WorkerFactory query
    ]

    for benchmark_file in benchmark_files:
        if Path(benchmark_file).exists():
            print("\n\n")
            valid, invalid = test_benchmark_queries(benchmark_file, max_queries=11)

            if invalid > 0:
                print(f"\n⚠️  Found {invalid} invalid queries in {benchmark_file}")
        else:
            print(f"\n⚠️  Benchmark file not found: {benchmark_file}")

    # Test specific patterns
    print("\n\n")
    test_specific_queries()


if __name__ == "__main__":
    main()
