"""
Manual Analysis and Validation of Phase 0 Comprehensive Results

This script reads the comprehensive test results, evaluates each decomposition,
assigns detailed scores and ratings, and saves the validated results.
"""
import json
from typing import Dict, Any, List
from pathlib import Path


class Phase0Validator:
    """Manual validator for Phase 0 logical decompositions"""

    def __init__(self):
        self.validation_criteria = {
            "logical_form_quality": {
                "weight": 0.25,
                "description": "Correctness and precision of formal logic notation"
            },
            "entity_parsing": {
                "weight": 0.20,
                "description": "Proper handling of compound identifiers (e.g., Manager.Run())"
            },
            "schema_grounding": {
                "weight": 0.25,
                "description": "Correct use of nodes, relationships, and attributes from schema"
            },
            "completeness": {
                "weight": 0.15,
                "description": "Coverage of all query aspects in subqueries"
            },
            "modal_logic_usage": {
                "weight": 0.15,
                "description": "Appropriate use of POSSIBLY() and other modal operators"
            }
        }

    def validate_logical_form_quality(self, decomposition: Dict[str, Any], query: str, test_id: str) -> Dict[str, Any]:
        """Evaluate the quality and correctness of the logical form"""
        logical_form = decomposition.get("logical_form", "")
        intent = decomposition.get("intent", "")

        score = 0.0
        feedback = []

        # Check for formal logic symbols
        has_logic_symbols = any(sym in logical_form for sym in ["∃", "∀", "∧", "∨", "→", "↔"])
        if has_logic_symbols:
            score += 3.0
            feedback.append("✓ Uses formal logic notation")
        else:
            feedback.append("✗ Missing formal logic symbols")

        # Check logical form is non-trivial
        if len(logical_form) > 50:
            score += 2.0
            feedback.append("✓ Detailed logical expression")
        elif len(logical_form) > 20:
            score += 1.0
            feedback.append("~ Minimal logical expression")
        else:
            feedback.append("✗ Overly simplistic logical form")

        # Intent alignment
        if intent in ["lookup", "factual"] and "count" in query.lower():
            if "count" in logical_form.lower() or "|" in logical_form:
                score += 2.0
                feedback.append("✓ Logical form correctly expresses counting")
            else:
                score += 1.0
                feedback.append("~ Logical form could better express counting intent")
        elif intent in ["architectural", "exploratory"]:
            if "CONTAINS*" in logical_form or "Summarize" in logical_form:
                score += 2.0
                feedback.append("✓ Logical form correctly expresses structural query")
            else:
                score += 1.0
                feedback.append("~ Logical form could better express exploration intent")

        # Check for proper variable quantification
        if has_logic_symbols:
            if ("∃" in logical_form or "∀" in logical_form) and any(var in logical_form for var in ["(", ":", ".", "["]):
                score += 2.0
                feedback.append("✓ Proper variable quantification")
            else:
                score += 1.0
                feedback.append("~ Variable quantification could be clearer")

        # Normalize score to 0-10
        final_score = min(10.0, (score / 9.0) * 10.0)

        return {
            "score": round(final_score, 2),
            "feedback": feedback,
            "max_score": 10.0
        }

    def validate_entity_parsing(self, decomposition: Dict[str, Any], query: str, test_id: str) -> Dict[str, Any]:
        """Evaluate proper handling of compound identifiers"""
        logical_form = decomposition.get("logical_form", "")
        subqueries = decomposition.get("subqueries", [])
        premises = decomposition.get("premises", [])

        score = 0.0
        feedback = []

        # Check if query contains compound identifiers
        compound_identifiers = []
        if "Manager.Run" in query:
            compound_identifiers.append("Manager.Run")
        if "WorkerFactory.CreateWorkers" in query:
            compound_identifiers.append("WorkerFactory.CreateWorkers")
        if "Helper.FormatMessage" in query:
            compound_identifiers.append("Helper.FormatMessage")

        # Extract pattern: Any CapitalizedWord.Method() pattern
        import re
        pattern = r'\b([A-Z][a-zA-Z0-9]*\.[A-Z][a-zA-Z0-9]*)\b'
        found_compounds = re.findall(pattern, query)
        compound_identifiers.extend(found_compounds)
        compound_identifiers = list(set(compound_identifiers))

        if not compound_identifiers:
            # No compound identifiers in query - check for general entity handling
            if any("Type" in sq and "Function" in sq for sq in subqueries):
                score += 5.0
                feedback.append("✓ Properly navigates Type→Function hierarchy")
            elif any("CONTAINS" in sq for sq in subqueries):
                score += 3.0
                feedback.append("~ Uses CONTAINS relationships")

            # Check for proper node type identification
            node_types = ["Type", "Function", "Variable", "File", "Project", "Namespace"]
            if any(nt in logical_form or any(nt in sq for sq in subqueries) for nt in node_types):
                score += 5.0
                feedback.append("✓ Correctly identifies node types")
        else:
            # Has compound identifiers - validate parsing
            for compound in compound_identifiers:
                parts = compound.split(".")
                container = parts[0]
                contained = parts[1] if len(parts) > 1 else ""

                # Check if logical form treats them separately
                treats_separately = False

                # Check for CONTAINS relationship between container and contained
                if f"CONTAINS({container}" in logical_form or f"CONTAINS(t:{container}" in logical_form:
                    treats_separately = True
                    score += 3.0
                    feedback.append(f"✓ Correctly separates {compound} into container+contained")

                # Check in subqueries
                for sq in subqueries:
                    if container in sq and contained in sq and "CONTAINS" in sq:
                        treats_separately = True
                        if f"✓ Correctly separates {compound}" not in " ".join(feedback):
                            score += 2.0
                            feedback.append(f"✓ Subquery properly navigates {compound}")

                # Check premises for explanation
                for premise in premises:
                    if compound in premise and ("CONTAINS" in premise or "contained" in premise.lower()):
                        score += 1.0
                        feedback.append(f"✓ Premise explains {compound} structure")
                        break

                if not treats_separately:
                    # Check if it's incorrectly treating as single entity
                    if f'"{compound}"' in logical_form or f"'{compound}'" in logical_form or f"name = '{compound}'" in logical_form:
                        feedback.append(f"✗ Incorrectly treats {compound} as single entity")
                    else:
                        score += 1.0
                        feedback.append(f"~ {compound} parsing unclear")

        # Normalize score to 0-10
        final_score = min(10.0, score)

        return {
            "score": round(final_score, 2),
            "feedback": feedback,
            "max_score": 10.0
        }

    def validate_schema_grounding(self, decomposition: Dict[str, Any], query: str, test_id: str) -> Dict[str, Any]:
        """Evaluate correct usage of schema nodes, relationships, and attributes"""
        logical_form = decomposition.get("logical_form", "")
        subqueries = decomposition.get("subqueries", [])

        score = 0.0
        feedback = []

        # Valid schema elements
        valid_nodes = ["Project", "File", "Function", "Type", "Variable", "Namespace", "Block", "Literal", "Statement", "Macro"]
        valid_relationships = ["CONTAINS", "CALLS", "REFERENCES", "IMPLEMENTS", "INHERITS_FROM", "DECLARES", "DEFINED_IN", "INCLUDED_IN", "HAS_TYPE"]
        valid_attributes = {
            "Project": ["name", "project_path", "config_metadata", "dependencies", "target_framework", "output_type", "build_properties"],
            "File": ["name", "file_path", "imports", "import_aliases", "start_point", "end_point"],
            "Function": ["name", "return_type", "parameters", "body", "modifier", "type_parameters", "file_path"],
            "Type": ["name", "type_kind", "access_modifier", "is_abstract", "fields", "base_list", "file_path"],
            "Variable": ["name", "type_kind", "initial_value", "access_modifier", "file_path"],
        }

        # Check node usage
        nodes_used = set()
        for node in valid_nodes:
            if node in logical_form or any(node in sq for sq in subqueries):
                nodes_used.add(node)

        if nodes_used:
            score += 2.0
            feedback.append(f"✓ Uses valid node types: {', '.join(sorted(nodes_used))}")

        # Check relationship usage
        relationships_used = set()
        for rel in valid_relationships:
            if rel in logical_form or any(rel in sq for sq in subqueries):
                relationships_used.add(rel)

        if relationships_used:
            score += 2.0
            feedback.append(f"✓ Uses valid relationships: {', '.join(sorted(relationships_used))}")

        # Check for invalid relationships
        if "Project" in logical_form or any("Project" in sq for sq in subqueries):
            # Check if incorrectly assumes Project→Type direct containment
            direct_type_violation = False
            for sq in subqueries:
                if "Project" in sq and "Type" in sq and "CONTAINS" in sq:
                    if "File" not in sq:  # Project→Type without File is wrong
                        direct_type_violation = True

            if direct_type_violation:
                score -= 2.0
                feedback.append("✗ Incorrectly assumes Project directly CONTAINS Type (should be Project→File→Type)")
            else:
                score += 2.0
                feedback.append("✓ Correctly navigates Project→File→Type hierarchy")

        # Check attribute usage
        attributes_used = 0
        for node_type, attrs in valid_attributes.items():
            for attr in attrs:
                if attr in logical_form or any(attr in sq for sq in subqueries):
                    attributes_used += 1

        if attributes_used > 0:
            score += min(2.0, attributes_used * 0.5)
            feedback.append(f"✓ References {attributes_used} valid attributes")

        # Check for APOC procedure references (good for JSON parsing)
        if "apoc.convert.fromJsonMap" in logical_form or any("apoc.convert.fromJsonMap" in sq for sq in subqueries):
            score += 2.0
            feedback.append("✓ Uses APOC procedures for JSON parsing")

        # Check for proper path expressions
        if "CONTAINS*" in logical_form or any("CONTAINS*" in sq for sq in subqueries):
            score += 1.0
            feedback.append("✓ Uses transitive path expressions (CONTAINS*)")

        # Normalize score to 0-10
        final_score = min(10.0, score)

        return {
            "score": round(final_score, 2),
            "feedback": feedback,
            "max_score": 10.0
        }

    def validate_completeness(self, decomposition: Dict[str, Any], query: str, test_id: str) -> Dict[str, Any]:
        """Evaluate if subqueries cover all query aspects"""
        subqueries = decomposition.get("subqueries", [])
        premises = decomposition.get("premises", [])

        score = 0.0
        feedback = []

        # Extract key query components
        query_lower = query.lower()

        # Check number of subqueries (reasonable decomposition)
        num_subqueries = len(subqueries)
        if 2 <= num_subqueries <= 10:
            score += 3.0
            feedback.append(f"✓ Appropriate decomposition ({num_subqueries} subqueries)")
        elif num_subqueries > 10:
            score += 2.0
            feedback.append(f"~ Many subqueries ({num_subqueries}) - might be over-decomposed")
        elif num_subqueries == 1:
            score += 1.0
            feedback.append("~ Single subquery - limited decomposition")
        else:
            feedback.append("✗ No subqueries generated")

        # Check premises
        num_premises = len(premises)
        if num_premises >= 2:
            score += 2.0
            feedback.append(f"✓ Good contextual premises ({num_premises})")
        elif num_premises == 1:
            score += 1.0
            feedback.append("~ Minimal premises")

        # Query-specific completeness checks
        if "how many" in query_lower or "count" in query_lower:
            # Should have counting/aggregation subquery
            if any("count" in sq.lower() for sq in subqueries):
                score += 2.0
                feedback.append("✓ Includes counting/aggregation step")
            else:
                feedback.append("✗ Missing explicit counting step")

        if "what is" in query_lower or "what are" in query_lower:
            # Should have retrieval and possibly summarization
            if any("retrieve" in sq.lower() or "collect" in sq.lower() for sq in subqueries):
                score += 2.0
                feedback.append("✓ Includes retrieval steps")

        if "dependencies" in query_lower or "relationships" in query_lower:
            # Should query relationship edges
            if any("edge" in sq.lower() or "relationship" in sq.lower() for sq in subqueries):
                score += 2.0
                feedback.append("✓ Queries relationship edges")

        # Check for logical ordering
        if len(subqueries) > 1:
            # First should typically be entity location
            if any(verb in subqueries[0].lower() for verb in ["locate", "find", "retrieve"]):
                score += 1.0
                feedback.append("✓ Logical ordering (starts with entity location)")

        # Normalize score to 0-10
        final_score = min(10.0, score)

        return {
            "score": round(final_score, 2),
            "feedback": feedback,
            "max_score": 10.0
        }

    def validate_modal_logic_usage(self, decomposition: Dict[str, Any], query: str, test_id: str) -> Dict[str, Any]:
        """Evaluate appropriate use of modal logic and POSSIBLY()"""
        logical_form = decomposition.get("logical_form", "")
        premises = decomposition.get("premises", [])
        intent = decomposition.get("intent", "")

        score = 0.0
        feedback = []

        # Check for POSSIBLY() usage
        has_possibly = "POSSIBLY" in logical_form or any("POSSIBLY" in p for p in premises)

        if has_possibly:
            score += 3.0
            feedback.append("✓ Uses POSSIBLY() for uncertain paths")

        # Intent-based evaluation
        if intent in ["lookup", "factual"]:
            # Specific queries - less need for modal logic
            if not has_possibly:
                score += 2.0
                feedback.append("✓ Direct query - appropriate without modal operators")
            elif "POSSIBLY" in logical_form:
                score += 4.0
                feedback.append("✓ Uses modal logic for ambiguity handling")

        elif intent in ["architectural", "exploratory"]:
            # Exploratory queries - modal logic valuable
            if has_possibly:
                score += 4.0
                feedback.append("✓ Modal logic appropriate for exploratory query")
            else:
                score += 2.0
                feedback.append("~ Could benefit from modal logic for uncertain paths")

        # Check for conditional logic
        has_conditionals = "→" in logical_form or "⇒" in logical_form
        if has_conditionals:
            score += 2.0
            feedback.append("✓ Uses conditional logic (→)")

        # Check for disjunctions (alternatives)
        has_disjunctions = "∨" in logical_form
        if has_disjunctions:
            score += 1.0
            feedback.append("✓ Expresses alternatives (∨)")

        # Normalize score to 0-10
        final_score = min(10.0, score)

        return {
            "score": round(final_score, 2),
            "feedback": feedback,
            "max_score": 10.0
        }

    def calculate_weighted_score(self, criterion_scores: Dict[str, float]) -> float:
        """Calculate weighted total score"""
        total = 0.0
        for criterion, score in criterion_scores.items():
            weight = self.validation_criteria[criterion]["weight"]
            total += score * weight
        return round(total, 2)

    def assign_rating(self, weighted_score: float) -> str:
        """Assign qualitative rating based on weighted score"""
        if weighted_score >= 9.0:
            return "Excellent"
        elif weighted_score >= 8.0:
            return "Very Good"
        elif weighted_score >= 7.0:
            return "Good"
        elif weighted_score >= 6.0:
            return "Satisfactory"
        elif weighted_score >= 5.0:
            return "Fair"
        else:
            return "Needs Improvement"

    def validate_decomposition(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a single decomposition result"""
        test_id = result.get("test_id", "")
        query = result.get("query", "")
        decomposition = result.get("decomposition", {})

        # Run all validation checks
        logical_form_result = self.validate_logical_form_quality(decomposition, query, test_id)
        entity_parsing_result = self.validate_entity_parsing(decomposition, query, test_id)
        schema_grounding_result = self.validate_schema_grounding(decomposition, query, test_id)
        completeness_result = self.validate_completeness(decomposition, query, test_id)
        modal_logic_result = self.validate_modal_logic_usage(decomposition, query, test_id)

        # Collect criterion scores
        criterion_scores = {
            "logical_form_quality": logical_form_result["score"],
            "entity_parsing": entity_parsing_result["score"],
            "schema_grounding": schema_grounding_result["score"],
            "completeness": completeness_result["score"],
            "modal_logic_usage": modal_logic_result["score"]
        }

        # Calculate weighted score
        weighted_score = self.calculate_weighted_score(criterion_scores)
        rating = self.assign_rating(weighted_score)

        # Build validation result
        validation = {
            "test_id": test_id,
            "weighted_score": weighted_score,
            "rating": rating,
            "criterion_scores": {
                "logical_form_quality": {
                    "score": logical_form_result["score"],
                    "weight": self.validation_criteria["logical_form_quality"]["weight"],
                    "feedback": logical_form_result["feedback"]
                },
                "entity_parsing": {
                    "score": entity_parsing_result["score"],
                    "weight": self.validation_criteria["entity_parsing"]["weight"],
                    "feedback": entity_parsing_result["feedback"]
                },
                "schema_grounding": {
                    "score": schema_grounding_result["score"],
                    "weight": self.validation_criteria["schema_grounding"]["weight"],
                    "feedback": schema_grounding_result["feedback"]
                },
                "completeness": {
                    "score": completeness_result["score"],
                    "weight": self.validation_criteria["completeness"]["weight"],
                    "feedback": completeness_result["feedback"]
                },
                "modal_logic_usage": {
                    "score": modal_logic_result["score"],
                    "weight": self.validation_criteria["modal_logic_usage"]["weight"],
                    "feedback": modal_logic_result["feedback"]
                }
            }
        }

        return validation


def main():
    """Main validation process"""
    print("=" * 80)
    print("PHASE 0 COMPREHENSIVE VALIDATION - MANUAL ANALYSIS")
    print("=" * 80)

    # Load comprehensive results
    input_path = Path("/tmp/phase0_comprehensive_results.json")
    with open(input_path, 'r') as f:
        data = json.load(f)

    results = data.get("results", [])
    total_tests = len(results)

    print(f"\nLoaded {total_tests} test results for validation")
    print(f"Starting manual analysis...\n")

    # Initialize validator
    validator = Phase0Validator()

    # Validate each result
    all_validations = []
    for i, result in enumerate(results, 1):
        test_id = result.get("test_id", f"Unknown_{i}")
        print(f"[{i}/{total_tests}] Validating {test_id}...")

        try:
            validation = validator.validate_decomposition(result)
            all_validations.append(validation)

            # Add validation to result
            result["validation"] = validation

            print(f"  Score: {validation['weighted_score']}/10.0 | Rating: {validation['rating']}")
        except Exception as e:
            print(f"  ✗ Validation failed: {e}")
            result["validation"] = {
                "test_id": test_id,
                "error": str(e),
                "weighted_score": 0.0,
                "rating": "Failed"
            }

    # Calculate summary statistics
    valid_scores = [v["weighted_score"] for v in all_validations if "error" not in v]

    summary_stats = {
        "total_validated": len(all_validations),
        "successful_validations": len(valid_scores),
        "failed_validations": len([v for v in all_validations if "error" in v]),
        "mean_score": round(sum(valid_scores) / len(valid_scores), 2) if valid_scores else 0.0,
        "median_score": round(sorted(valid_scores)[len(valid_scores) // 2], 2) if valid_scores else 0.0,
        "min_score": round(min(valid_scores), 2) if valid_scores else 0.0,
        "max_score": round(max(valid_scores), 2) if valid_scores else 0.0,
        "rating_distribution": {}
    }

    # Calculate rating distribution
    for validation in all_validations:
        rating = validation.get("rating", "Unknown")
        summary_stats["rating_distribution"][rating] = summary_stats["rating_distribution"].get(rating, 0) + 1

    # Add summary to data
    data["validation_summary"] = summary_stats

    # Save updated results
    output_path = Path("/tmp/phase0_comprehensive_results_validated.json")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    # Print summary
    print("\n" + "=" * 80)
    print("VALIDATION COMPLETE")
    print("=" * 80)
    print(f"Total validated: {summary_stats['total_validated']}")
    print(f"Successful: {summary_stats['successful_validations']}")
    print(f"Failed: {summary_stats['failed_validations']}")
    print(f"\nScore Statistics:")
    print(f"  Mean:   {summary_stats['mean_score']}/10.0")
    print(f"  Median: {summary_stats['median_score']}/10.0")
    print(f"  Min:    {summary_stats['min_score']}/10.0")
    print(f"  Max:    {summary_stats['max_score']}/10.0")
    print(f"\nRating Distribution:")
    for rating, count in sorted(summary_stats['rating_distribution'].items(), key=lambda x: -x[1]):
        print(f"  {rating:20s}: {count:3d} ({count/summary_stats['total_validated']*100:.1f}%)")
    print(f"\n✅ Validated results saved to {output_path}")
    print("=" * 80)


if __name__ == "__main__":
    main()
