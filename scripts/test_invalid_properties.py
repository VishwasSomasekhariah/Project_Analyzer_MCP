from src.core.workflow.cypher_query_validator import create_default_validator

validator = create_default_validator()

# Test 1: Valid property
print("=" * 80)
print("Test 1: Valid property (Function.name)")
print("=" * 80)
query1 = "MATCH (f:Function) WHERE f.name = 'CreateWorkers' RETURN f.name"
result1 = validator.validate(query1)
print(f"Result: {'✅ VALID' if result1.is_valid else '❌ INVALID'}")
for issue in result1.issues:
    print(f"  {issue.severity.value.upper()}: {issue.message}")

# Test 2: Invalid property
print("\n" + "=" * 80)
print("Test 2: Invalid property (Function.invalid_property)")
print("=" * 80)
query2 = "MATCH (f:Function) WHERE f.invalid_property = 'test' RETURN f.name"
result2 = validator.validate(query2)
print(f"Result: {'✅ VALID' if result2.is_valid else '❌ INVALID'}")
for issue in result2.issues:
    print(f"  {issue.severity.value.upper()}: {issue.message}")
    if issue.suggestion:
        print(f"  SUGGESTION: {issue.suggestion}")

# Test 3: Typo in property name
print("\n" + "=" * 80)
print("Test 3: Typo in property (Function.naem instead of name)")
print("=" * 80)
query3 = "MATCH (f:Function) WHERE f.naem = 'CreateWorkers' RETURN f.name"
result3 = validator.validate(query3)
print(f"Result: {'✅ VALID' if result3.is_valid else '❌ INVALID'}")
for issue in result3.issues:
    print(f"  {issue.severity.value.upper()}: {issue.message}")
    if issue.suggestion:
        print(f"  SUGGESTION: {issue.suggestion}")
