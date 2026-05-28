"""
Test Approach Packet Builder End-to-End

Tests the complete flow:
1. Phase 0: Query decomposition
2. Post-processing: Dependency analysis
3. Packet building: Self-contained approach packets

Validates that packets are fully self-contained with all context.
"""
import asyncio
import yaml
import json
from pathlib import Path

from src.core.llm_service import LLMService
from src.core.workflow.research_engine import ResearchEngine


async def test_packet_builder():
    """Test complete packet building flow"""

    # Initialize services
    llm_service = LLMService()
    research_engine = ResearchEngine(llm_service)

    # Load schema
    schema_path = Path("src/schemas/project_knowledgebase_graph_schema.yaml")
    with open(schema_path, 'r') as f:
        schema = yaml.safe_load(f)

    # Test with T039 (complex query with 11 subqueries)
    test_query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"
    intent = {
        "intent_type": "lookup",
        "confidence": 0.95,
        "reasoning": "Query asks for specific classes created by factory method",
        "expected_result_type": "List of class names"
    }

    print("=" * 80)
    print("TESTING APPROACH PACKET BUILDER END-TO-END")
    print("=" * 80)
    print()
    print(f"Query: {test_query}")
    print()

    try:
        # Prepare state
        state = {
            'user_query': test_query,
            'intent': intent,
            'schema': schema
        }

        # STEP 1: Phase 0 Decomposition
        print("🔍 STEP 1: Phase 0 Decomposition")
        print("-" * 80)
        decomposition = await research_engine._decompose_user_query(state)

        print(f"✅ Decomposition complete:")
        print(f"   Logical Form: {decomposition['logical_form'][:80]}...")
        print(f"   Premises: {len(decomposition['premises'])}")
        print(f"   Subqueries: {len(decomposition['subqueries'])}")
        print()

        # STEP 2: Dependency Analysis
        print("🔍 STEP 2: Dependency Analysis")
        print("-" * 80)
        dependency_analysis = await research_engine._analyze_dependencies(decomposition)

        print(f"✅ Dependency analysis complete:")
        print(f"   Enhanced Premises: {len(dependency_analysis['premises'])}")
        print(f"   Enhanced Subqueries: {len(dependency_analysis['subqueries'])}")
        print(f"   Execution Groups: {len(dependency_analysis['execution_groups'])}")
        print()

        # STEP 3: Build Approach Packets
        print("🔍 STEP 3: Build Self-Contained Approach Packets")
        print("-" * 80)
        packet_collection = research_engine._build_approach_packets(
            decomposition,
            dependency_analysis
        )

        print(f"✅ Packet collection built:")
        print(f"   Total Packets: {packet_collection['total_subqueries']}")
        print(f"   Execution Groups: {len(packet_collection['execution_groups'])}")
        print()

        # STEP 4: Validate Packets are Self-Contained
        print("🔍 STEP 4: Validate Self-Containment")
        print("=" * 80)
        print()

        packets = packet_collection['packets']

        # Pick a packet from the middle to validate
        test_packet_id = 'SQ5'
        if test_packet_id in packets:
            packet = packets[test_packet_id]

            print(f"Examining packet: {test_packet_id}")
            print("-" * 80)
            print()

            # Check all required fields
            print("✅ SELF-CONTAINMENT VALIDATION:")
            print()

            print(f"1. ID: {packet['id']}")
            print(f"2. Text: {packet['text'][:70]}...")
            print()

            print(f"3. Logical Form (embedded):")
            print(f"   {packet['logical_form'][:70]}...")
            print()

            print(f"4. Premises (embedded, not references):")
            for premise in packet['premises']:
                print(f"   - {premise['id']}: {premise['text'][:60]}...")
            print()

            print(f"5. Dependencies:")
            print(f"   - Depends on subqueries: {packet['depends_on_subqueries']}")
            print(f"   - Execution group: {packet['execution_group']}")
            print()

            print(f"6. Execution metadata:")
            print(f"   - Status: {packet['status']}")
            print(f"   - Input data placeholder: {packet['input_data']}")
            print(f"   - Result placeholder: {packet['result']}")
            print()

            # Verify self-containment
            validation_passed = True
            validation_errors = []

            # Check all required fields exist
            required_fields = ['id', 'text', 'logical_form', 'premises', 'depends_on_subqueries',
                             'execution_group', 'status', 'input_data', 'result']
            for field in required_fields:
                if field not in packet:
                    validation_errors.append(f"Missing field: {field}")
                    validation_passed = False

            # Check premises are embedded (have 'id' and 'text', not just IDs)
            if 'premises' in packet:
                for premise in packet['premises']:
                    if not isinstance(premise, dict) or 'id' not in premise or 'text' not in premise:
                        validation_errors.append(f"Premise not properly embedded: {premise}")
                        validation_passed = False

            # Check logical form is present
            if not packet.get('logical_form') or len(packet['logical_form']) < 10:
                validation_errors.append("Logical form missing or too short")
                validation_passed = False

            if validation_passed:
                print("✅ VALIDATION PASSED: Packet is fully self-contained!")
                print()
                print("   Mini CoT agent can execute this packet with:")
                print("   - Full query context (logical form)")
                print("   - All assumptions (embedded premises)")
                print("   - Clear task (subquery text)")
                print("   - Dependency info (for scheduling)")
                print("   - NO external lookups needed!")
            else:
                print("❌ VALIDATION FAILED:")
                for error in validation_errors:
                    print(f"   - {error}")

        print()
        print("=" * 80)
        print("PACKET STRUCTURE SUMMARY")
        print("=" * 80)
        print()

        # Show execution plan
        print("EXECUTION PLAN:")
        for i, group in enumerate(packet_collection['execution_groups'], 1):
            print(f"  Group {i}: {', '.join(group)} ({len(group)} packets in parallel)")

        print()
        print("PACKET EXAMPLES:")
        print()

        # Show first packet from each execution group
        for i, group in enumerate(packet_collection['execution_groups'][:3], 1):
            if group:
                packet_id = group[0]
                packet = packets[packet_id]
                print(f"Group {i} Example ({packet_id}):")
                print(f"  Text: {packet['text'][:60]}...")
                print(f"  Premises: {len(packet['premises'])} embedded")
                print(f"  Depends on: {packet['depends_on_subqueries'] or 'None (can run immediately)'}")
                print()

        # Save to file
        output_file = "/tmp/approach_packets_test.json"
        with open(output_file, 'w') as f:
            json.dump({
                "decomposition": decomposition,
                "dependency_analysis": dependency_analysis,
                "packet_collection": packet_collection
            }, f, indent=2)

        print("=" * 80)
        print(f"✅ Complete test data saved to: {output_file}")
        print("=" * 80)

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_packet_builder())