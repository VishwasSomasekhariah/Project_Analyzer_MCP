#!/usr/bin/env python3
"""Test script to validate Actor-Critic validation system against T060 hallucination scenario."""

import asyncio
import json
import time
import logging
from mcp_use import MCPClient

# Enable verbose logging to see Actor-Critic stages
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def test_actor_critic_validation():
    """Test the Actor-Critic validation system with the T060 hallucination scenario."""
    
    print("🧪 Testing Actor-Critic Validation System")
    print("=" * 60)
    
    # T060 scenario data
    test_query = "Which class method formats the notification message that gets printed to console in each worker?"
    expected_ground_truth = "Utilities.Helper.FormatMessage"
    previous_hallucinated_response = "The `Process` method in the `WorkerC` class formats the notification message"
    
    print(f"📝 Test Query: {test_query}")
    print(f"🎯 Expected Ground Truth: {expected_ground_truth}")
    print(f"❌ Previous Hallucinated Response: {previous_hallucinated_response}")
    print()
    
    # Connect to MCP server using config file (like working test script)
    client = MCPClient("/opt/genpod/file_watcher_mcp_config.json")
    
    try:
        # Create session (like working test script)
        session = await client.create_session("mcp-analysis-server")
        print("🔗 Connected to MCP server")
        
        # Test vector_only query with Actor-Critic validation
        print("\n🎭 Testing vector_only_query with Actor-Critic validation...")
        start_time = time.time()
        
        result = await session.call_tool(
            "query_vector_only",
            {
                "query": test_query,
                "collection_name": "helloworldapp-benchmarking", 
                "max_results": 15,
                "output_format": "json"
            }
        )
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Parse result - extract content text first (like working test script)
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        try:
            result_data = json.loads(content_text)
        except json.JSONDecodeError:
            result_data = {"error": "JSON parsing failed", "raw_response": content_text}
        
        print(f"⏱️  Processing time: {processing_time:.2f}s")
        print(f"📊 Status: {result_data.get('status', 'unknown')}")
        print(f"📊 Raw results count: {len(result_data.get('raw_results', []))}")
        
        # Analyze the AI response for hallucination
        ai_response = result_data.get('ai_response', '')
        print(f"\n🤖 AI Response:")
        print("-" * 40)
        print(ai_response)
        print("-" * 40)
        
        # Validation analysis
        print(f"\n🔍 Validation Analysis:")
        
        # Check if response mentions the correct method
        mentions_helper_format = "Helper.FormatMessage" in ai_response or "FormatMessage" in ai_response
        mentions_utilities_helper = "Utilities.Helper" in ai_response
        mentions_process_method = "Process" in ai_response and "method" in ai_response
        mentions_worker_class = any(worker in ai_response for worker in ["WorkerA", "WorkerB", "WorkerC"])
        
        print(f"  ✅ Mentions FormatMessage: {mentions_helper_format}")
        print(f"  ✅ Mentions Utilities.Helper: {mentions_utilities_helper}")
        print(f"  ⚠️  Mentions Process method: {mentions_process_method}")
        print(f"  ⚠️  Mentions Worker classes: {mentions_worker_class}")
        
        # Determine if hallucination is fixed
        if mentions_helper_format and mentions_utilities_helper:
            if mentions_process_method and not mentions_helper_format:
                validation_result = "❌ HALLUCINATION DETECTED"
                validation_details = "Still incorrectly identifies Process method instead of FormatMessage"
            else:
                validation_result = "✅ HALLUCINATION FIXED"
                validation_details = "Correctly identifies Utilities.Helper.FormatMessage method"
        elif mentions_process_method and mentions_worker_class:
            validation_result = "❌ HALLUCINATION PERSISTS" 
            validation_details = "Still incorrectly focuses on Process method in worker classes"
        else:
            validation_result = "🤔 UNCLEAR RESPONSE"
            validation_details = "Response doesn't clearly identify the formatting method"
        
        print(f"\n📋 Final Assessment:")
        print(f"  Result: {validation_result}")
        print(f"  Details: {validation_details}")
        
        # Check raw results for ground truth availability
        raw_results = result_data.get('raw_results', [])
        helper_method_found = False
        format_message_found = False
        
        for i, raw_result in enumerate(raw_results[:5]):  # Check top 5
            content = raw_result.get('content', '')
            if 'FormatMessage' in content and 'Helper' in content:
                helper_method_found = True
                format_message_found = True
                print(f"  🎯 Ground truth found in result #{i+1} (score: {raw_result.get('score', 0):.3f})")
                break
        
        if helper_method_found:
            if validation_result == "✅ HALLUCINATION FIXED":
                print(f"\n🎉 SUCCESS: Actor-Critic validation system successfully prevented hallucination!")
                print(f"  - Ground truth was available in retrieved results")
                print(f"  - AI correctly identified the FormatMessage method")
                print(f"  - Factual accuracy improved while maintaining comprehensive analysis")
            else:
                print(f"\n⚠️  PARTIAL SUCCESS: Ground truth available but response still has issues")
                print(f"  - Need to review validation prompts or logic")
        else:
            print(f"\n❓ INCONCLUSIVE: Ground truth not clearly present in top results")
        
        # Save detailed results
        test_results = {
            "test_scenario": "T060_actor_critic_validation",
            "timestamp": time.strftime("%Y%m%d_%H%M%S"),
            "query": test_query,
            "expected_ground_truth": expected_ground_truth,
            "ai_response": ai_response,
            "processing_time": processing_time,
            "validation_result": validation_result,
            "validation_details": validation_details,
            "mentions_helper_format": mentions_helper_format,
            "mentions_utilities_helper": mentions_utilities_helper,
            "mentions_process_method": mentions_process_method,
            "ground_truth_in_results": helper_method_found,
            "raw_results_count": len(raw_results),
            "full_response": result_data
        }
        
        # Save results to file
        results_filename = f"actor_critic_test_results_{test_results['timestamp']}.json"
        with open(results_filename, 'w') as f:
            json.dump(test_results, f, indent=2, default=str)
        
        print(f"\n📁 Detailed results saved to: {results_filename}")
        
        return test_results
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        await client.close_session()

if __name__ == "__main__":
    print("🚀 Starting Actor-Critic validation test for T060 hallucination scenario")
    result = asyncio.run(test_actor_critic_validation())
    
    if result:
        print(f"\n✅ Test completed successfully")
    else:
        print(f"\n❌ Test failed")