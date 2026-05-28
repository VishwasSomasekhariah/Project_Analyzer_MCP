#!/usr/bin/env python3
"I do"
"""
Test query_cpg_rag integration using MCP Client pattern
Based on properly_fixed_comparative_analysis.py pattern
"""

import asyncio
import json
import logging
import time
from datetime import datetime

from mcp_use import MCPClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_query_cpg_rag_mcp_integration():
    """Test the query_cpg_rag function using MCPClient pattern"""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    print("🔍 Testing query_cpg_rag MCP integration...")
    print(f"📁 Config: {config_file}")
    
    try:
        # Use MCPClient pattern from properly_fixed_comparative_analysis.py
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")
        
        # Direct Query 2 - Same as hybrid test for comparison
        test_query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"

        # Other test queries:
        # test_query = "What is the overall architecture and design patterns used in this project?"  # Architectural
        # test_query = "Analyze the class hierarchy and inheritance structure in the HelloWorldApp."
        # test_query = "What is the last comment line in WorkerA.cs?"
        # test_query = "Which worker method has the longest message parameter passed to Helper.FormatMessage?"
        # test_query = "Which methods use string interpolation ($\"...\")?"
        # test_query = "How many methods call Console.WriteLine directly?"
        # test_query = "What variable name stores the formatted message in WorkerA?"  # Direct Query 1
        # test_query = "What variable name stores the formatted message in WorkerZ?"  # Negative Test
        

        print(f"📝 Query: {test_query}")
        print("-" * 80)
        
        start_time = time.time()
        
        # Call the query_cpg_rag tool through MCP with explicit parallel config
        result = await session.call_tool(
            "query_cpg_rag",
            {
                "user_query": test_query,
                "project_name": "HelloWorldApp",
                "max_agent_iterations": 100,  # Max decomposition iterations
                "parallel_agents": True,  # Enable parallel sub-query execution
                # Note: max_parallel_workers not used - 4-agent team runs all sub-queries in parallel without worker limits
                "use_4_agent_team": True,  # Use 4-agent team workflow
                "four_agent_max_iterations": 3  # Max iterations per sub-query
            }
        )
        
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract result content
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        print(f"⏱️  Response time: {response_time_ms}ms")
        print("-" * 80)
        
        # Try to parse as JSON
        try:
            result_data = json.loads(content_text)
            
            print(f"✅ Status: {result_data.get('status')}")
            print(f"🛠️  Tool: {result_data.get('tool_name')}")
            print(f"🤖 Workflow: {result_data.get('workflow_type')}")
            print(f"🔄 Iterations: {result_data.get('iterations_used', 'N/A')}")
            
            if result_data.get('status') == 'success':
                response = result_data.get('response', '')
                discovered_data = result_data.get('discovered_data', [])
                query_history = result_data.get('query_history', [])
                raw_query_results = result_data.get('raw_query_results', [])  # FIXED: Use raw_query_results for proper formatting
                final_results = result_data.get('final_results', [])
                synthesis_validation = result_data.get('synthesis_validation', {})
                
                print(f"📊 Response length: {len(response)} chars")
                print(f"🔍 Discovered data items: {len(discovered_data)}")
                print(f"📜 Query history items: {len(query_history)}")
                print(f"📋 Final results items: {len(final_results)}")
                print(f"🗃️  Raw query results items: {len(raw_query_results)}")
                
                # DEBUG: Show available top-level keys for troubleshooting
                print(f"🔑 Available result keys: {sorted(result_data.keys())}")
                
                # Show COMPLETE response (not just preview)
                if response:
                    print(f"\n📝 COMPLETE RESPONSE:")
                    print("=" * 80)
                    print(response)
                    print("=" * 80)
                
                # Show synthesis validation if available
                if synthesis_validation:
                    print(f"\n🔍 SYNTHESIS VALIDATION:")
                    print("-" * 60)
                    print(f"  Overall Score: {synthesis_validation.get('overall_score', 'N/A')}")
                    print(f"  Decision: {synthesis_validation.get('decision', 'N/A')}")
                    print(f"  Faithfulness: {synthesis_validation.get('faithfulness_score', 'N/A')}")
                    print(f"  Completeness: {synthesis_validation.get('completeness_score', 'N/A')}")
                    print(f"  Accuracy: {synthesis_validation.get('accuracy_score', 'N/A')}")
                    print(f"  Quality: {synthesis_validation.get('quality_score', 'N/A')}")
                    if synthesis_validation.get('validation_issues'):
                        print(f"  Issues: {synthesis_validation.get('validation_issues')}")
                    print("-" * 60)
                
                # Show ALL discovered data (not just first 3)
                if discovered_data and len(discovered_data) > 0:
                    print(f"\n🔍 ALL DISCOVERED DATA:")
                    print("-" * 80)
                    for i, item in enumerate(discovered_data):
                        print(f"  [{i+1:3d}] {item}")
                    print("-" * 80)
                
                # Show ALL query history (using fixed raw_query_results with proper field names)
                if raw_query_results and len(raw_query_results) > 0:
                    print(f"\n📜 ALL QUERY HISTORY (Primary + Diagnostic):")
                    print("-" * 80)
                    for i, query_item in enumerate(raw_query_results):
                        is_diagnostic = query_item.get('is_diagnostic', False)
                        query_type = "🔧 Diagnostic" if is_diagnostic else "📋 Primary"
                        print(f"  [{i+1:3d}] {query_type} Query: {query_item.get('query', 'N/A')[:100]}...")
                        print(f"       Results: {query_item.get('results_count', 'N/A')} items")
                        print(f"       Purpose: {query_item.get('purpose', 'N/A')}")
                        print(f"       Status: {query_item.get('execution_status', 'N/A')}")
                        if is_diagnostic:
                            print(f"       Parent Query: {query_item.get('parent_query_number', 'N/A')}")
                        print()
                    print("-" * 80)
                elif query_history and len(query_history) > 0:
                    # Fallback to old query_history format if raw_query_results not available
                    print(f"\n📜 ALL QUERY HISTORY (Legacy Format):")
                    print("-" * 80)
                    for i, query_item in enumerate(query_history):
                        print(f"  [{i+1:3d}] Query: {query_item.get('cypher_query', query_item.get('query', 'N/A'))[:100]}...")
                        print(f"       Results: {len(query_item.get('data', []))} items")
                        print(f"       Purpose: {query_item.get('approach_name', query_item.get('purpose', 'N/A'))}")
                        print(f"       Status: {query_item.get('status', 'N/A')}")
                        print()
                    print("-" * 80)
                
                # Show ALL final results
                if final_results and len(final_results) > 0:
                    print(f"\n📋 ALL FINAL RESULTS:")
                    print("-" * 80)
                    for i, result_item in enumerate(final_results):
                        print(f"  [{i+1:3d}] {result_item}")
                    print("-" * 80)
                
            else:
                print(f"❌ Error: {result_data.get('error')}")
                print(f"💬 Message: {result_data.get('message')}")
                # Show error details if available
                if result_data.get('discovered_data'):
                    print(f"🔍 Partial data found: {len(result_data.get('discovered_data', []))} items")
                if result_data.get('query_history'):
                    print(f"📜 Queries attempted: {len(result_data.get('query_history', []))}")
            
            # Save result for inspection
            output_file = f"/opt/genpod/query_cpg_rag_mcp_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump(result_data, f, indent=2)
            
            print(f"\n💾 Full result saved to: {output_file}")
            
            return result_data
            
        except json.JSONDecodeError:
            print(f"⚠️  Response is not JSON, showing raw content:")
            print("-" * 40)
            print(content_text)
            print("-" * 40)
            
            return {"status": "unparsed", "content": content_text}
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}

async def test_query_vector_only_mcp_integration():
    """Test the query_vector_only function using MCPClient pattern"""

    config_file = "/opt/genpod/file_watcher_mcp_config.json"

    print("🔍 Testing query_vector_only MCP integration...")
    print(f"📁 Config: {config_file}")

    try:
        # Use MCPClient pattern
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")

        # Test query
        test_query = "What is the overall architecture and design patterns used in this project?"
        # test_query = "How does dependency injection work in this codebase?"
        # test_query = "What are the main components of the HelloWorldApp?"
        # test_query = "Which classes implement worker patterns?"

        print(f"📝 Query: {test_query}")
        print("-" * 80)

        start_time = time.time()

        # Call the query_vector_only tool through MCP
        result = await session.call_tool(
            "query_vector_only",
            {
                "query": test_query,
                "collection_name": "HelloWorldApp_qdrant_v2",  # Adjust to your collection
                "max_results": 5,
                "output_format": "json",
                "vector_db": "qdrant",  # or "weaviate"
                "config": "/opt/genpod/qdrant_config.json",  # Path to vector DB config
                "enable_reasoning": True,
                "max_branches": 2
            }
        )

        response_time_ms = int((time.time() - start_time) * 1000)

        # Extract result content
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)

        print(f"⏱️  Response time: {response_time_ms}ms")
        print("-" * 80)

        # Try to parse as JSON
        try:
            result_data = json.loads(content_text)

            print(f"✅ Status: {result_data.get('status')}")
            print(f"🛠️  Tool: query_vector_only")
            print(f"📦 Collection: {result_data.get('collection_name', 'HelloWorldApp_qdrant_v2')}")
            print(f"🔑 Available keys: {sorted(result_data.keys())}")

            if result_data.get('status') == 'success':
                ai_response = result_data.get('ai_response', result_data.get('response', ''))
                raw_results = result_data.get('raw_results', [])
                metadata = result_data.get('metadata', {})
                reasoning_trace = result_data.get('reasoning_trace')

                print(f"\n📊 Results Summary:")
                print(f"  AI Response length: {len(ai_response)} chars")
                print(f"  Raw results: {len(raw_results)} items")

                # Show metadata if available
                if metadata:
                    print(f"\n📋 Metadata:")
                    print(f"  Total Results: {metadata.get('vector_total_results', metadata.get('total_results', 'N/A'))}")
                    print(f"  Processing Time: {metadata.get('vector_processing_time', metadata.get('processing_time', 'N/A'))}")
                    print(f"  Confidence Score: {metadata.get('vector_confidence_score', metadata.get('confidence_score', 'N/A'))}")
                    print(f"  Has Diagram: {metadata.get('has_diagram', False)}")
                    print(f"  Reasoning Used: {metadata.get('reasoning_used', False)}")
                    if metadata.get('reasoning_metrics'):
                        print(f"  Reasoning Metrics: {metadata.get('reasoning_metrics')}")

                # Show reasoning trace if available
                if reasoning_trace:
                    print(f"\n🧠 Reasoning Trace:")
                    print(f"  Steps: {len(reasoning_trace.get('steps', []))}")
                    print(f"  Total Time: {reasoning_trace.get('total_time', 'N/A')}")

                # Show complete AI response
                if ai_response:
                    print(f"\n📝 AI RESPONSE:")
                    print("=" * 80)
                    print(ai_response)
                    print("=" * 80)

                # Show raw results (first 3)
                if raw_results and len(raw_results) > 0:
                    print(f"\n🔍 RAW RESULTS (Top {min(3, len(raw_results))} of {len(raw_results)}):")
                    print("-" * 80)
                    for i, item in enumerate(raw_results[:3]):
                        print(f"\n  [{i+1}] Score: {item.get('score', 'N/A')}")
                        doc_text = item.get('document', item.get('text', ''))
                        print(f"      Document: {doc_text[:200]}...")
                        if item.get('metadata'):
                            print(f"      Metadata: {item.get('metadata')}")
                    print("-" * 80)

            else:
                print(f"❌ Error: {result_data.get('error')}")
                print(f"💬 Message: {result_data.get('message', 'No message')}")

            # Save result for inspection
            output_file = f"/opt/genpod/query_vector_rag_mcp_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump(result_data, f, indent=2)

            print(f"\n💾 Full result saved to: {output_file}")

            return result_data

        except json.JSONDecodeError:
            print(f"⚠️  Response is not JSON, showing raw content:")
            print("-" * 40)
            print(content_text)
            print("-" * 40)

            return {"status": "unparsed", "content": content_text}

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}

async def test_query_hybrid_rag_mcp_integration():
    """Test the new query_hybrid_rag function using MCPClient pattern"""
    
    config_file = "/opt/genpod/file_watcher_mcp_config.json"
    
    print("🔍 Testing query_hybrid_rag MCP integration...")
    print(f"📁 Config: {config_file}")
    
    try:
        # Use MCPClient pattern
        client = MCPClient.from_config_file(config_file)
        session = await client.create_session("mcp-analysis-server")
        
        # Test queries for different intent types:
        # test_query = "What classes and interfaces are defined in this project and how do they relate?"  # Architectural
        # test_query = "What variable name stores the formatted message in WorkerA?"  # Direct lookup
        test_query = "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?"  # Specific query
        # test_query = "What is the overall architecture and design patterns used in this project?"  # Architectural
        # test_query = "Analyze the class hierarchy and inheritance structure in the HelloWorldApp."  # Structural
        # test_query = "What is the last comment line in WorkerA.cs?"  # Direct lookup
        # test_query = "What variable name stores the formatted message in WorkerZ?"  # Direct lookup (negative test)
        # test_query = "How many classes are defined in this project?"  # Quantitative
        # test_query = "What design patterns are used for dependency injection?"  # Semantic

        print(f"📝 Query: {test_query}")
        print("-" * 80)
        
        start_time = time.time()
        
        # Call the new query_hybrid_rag tool through MCP
        result = await session.call_tool(
            "query_hybrid_rag",
            {
                "user_query": test_query,
                "project_name": "HelloWorldApp",
                "collection_name": "HelloWorldApp_qdrant_v2",
                "max_agent_iterations": 10  # Shorter for testing
            }
        )
        
        response_time_ms = int((time.time() - start_time) * 1000)
        
        # Extract result content
        result_content = result.content[0] if isinstance(result.content, list) else result.content
        content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
        
        print(f"⏱️  Response time: {response_time_ms}ms")
        print("-" * 80)
        
        # Try to parse as JSON
        try:
            result_data = json.loads(content_text)
            
            print(f"✅ Status: {result_data.get('status')}")
            print(f"🛠️  Tool: {result_data.get('tool_name')}")
            print(f"🤖 Workflow: {result_data.get('workflow_type')}")
            print(f"📊 Project: {result_data.get('project_name')}")
            print(f"📦 Collection: {result_data.get('collection_name')}")
            
            if result_data.get('status') == 'success':
                print(f"🔑 Response Keys: {list(result_data.keys())}")
                
                # Extract hybrid-specific fields
                response = result_data.get('response', '')
                details = result_data.get('details', '')
                raw_results = result_data.get('raw_results', [])
                vector_raw_results = result_data.get('vector_raw_results', [])
                cpg_raw_results = result_data.get('cpg_raw_results', [])
                intent_analysis = result_data.get('intent_analysis', {})
                synthesis_strategy = result_data.get('synthesis_strategy', '')
                synthesis_confidence = result_data.get('synthesis_confidence', 0.0)
                cross_validation = result_data.get('cross_validation', {})
                critic_validation = result_data.get('critic_validation', {})
                total_execution_time = result_data.get('total_execution_time', 0.0)
                vector_execution_time = result_data.get('vector_execution_time', 0.0)
                cpg_execution_time = result_data.get('cpg_execution_time', 0.0)
                
                print(f"📝 Main response length: {len(response)} chars")
                print(f"📋 Details length: {len(details)} chars")
                print(f"🔍 Combined raw results: {len(raw_results)} items")
                print(f"📊 Vector raw results: {len(vector_raw_results)} items")
                print(f"🕸️  CPG raw results: {len(cpg_raw_results)} items")
                
                # Intent Analysis
                if intent_analysis:
                    print(f"\n🧠 Intent Analysis:")
                    print(f"  Intent: {intent_analysis.get('intent', 'Unknown')}")
                    print(f"  Confidence: {intent_analysis.get('confidence', 0.0):.2f}")
                    print(f"  Vector Weight: {intent_analysis.get('vector_weight', 0.0):.2f}")
                    print(f"  CPG Weight: {intent_analysis.get('cpg_weight', 0.0):.2f}")
                    print(f"  Reasoning: {intent_analysis.get('reasoning', 'N/A')[:100]}...")
                
                # Synthesis Information
                print(f"\n⚙️ Synthesis:")
                print(f"  Strategy: {synthesis_strategy}")
                print(f"  Confidence: {synthesis_confidence:.2f}")
                
                # Cross-validation Results
                if cross_validation:
                    print(f"\n🔄 Cross-Validation:")
                    print(f"  Vector validates CPG: {'✅' if cross_validation.get('vector_validates_cpg') else '❌'}")
                    print(f"  CPG validates Vector: {'✅' if cross_validation.get('cpg_validates_vector') else '❌'}")
                    print(f"  Confidence Score: {cross_validation.get('confidence_score', 0.0):.2f}")
                    conflicts = cross_validation.get('conflicts_found', [])
                    consensus = cross_validation.get('consensus_points', [])
                    print(f"  Conflicts: {len(conflicts)} found")
                    print(f"  Consensus Points: {len(consensus)} found")
                
                # Critic Validation
                if critic_validation:
                    print(f"\n🔍 Critic Validation:")
                    print(f"  Decision: {critic_validation.get('decision', 'N/A')}")
                    print(f"  Overall Score: {critic_validation.get('overall_score', 0.0):.2f}")
                    print(f"  Hallucination Score: {critic_validation.get('hallucination_score', 0.0):.2f}")
                    print(f"  Faithfulness Score: {critic_validation.get('faithfulness_score', 0.0):.2f}")
                    print(f"  Accuracy Score: {critic_validation.get('accuracy_score', 0.0):.2f}")
                    issues = critic_validation.get('validation_issues', [])
                    if issues:
                        print(f"  Issues Found: {len(issues)} ({', '.join(issues[:3])}{'...' if len(issues) > 3 else ''})")
                
                # Performance Metrics
                print(f"\n⏱️ Performance:")
                print(f"  Total Time: {total_execution_time:.2f}s")
                print(f"  Vector Time: {vector_execution_time:.2f}s")
                print(f"  CPG Time: {cpg_execution_time:.2f}s")
                
                # Show main response
                if response:
                    print(f"\n📝 Main Response:")
                    print("=" * 80)
                    print(response)
                    print("=" * 80)
                
                # Show details if different from response
                if details and details != response:
                    print(f"\n📋 Additional Details:")
                    print("-" * 60)
                    print(details[:1000] + "..." if len(details) > 1000 else details)
                    print("-" * 60)
                
            else:
                print(f"❌ Error: {result_data.get('error')}")
                print(f"💬 Message: {result_data.get('message')}")
                if result_data.get('fallback_suggestions'):
                    print(f"💡 Suggestions: {result_data.get('fallback_suggestions')}")
            
            # Save result for inspection
            output_file = f"/opt/genpod/query_hybrid_rag_mcp_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(output_file, 'w') as f:
                json.dump(result_data, f, indent=2)
            
            print(f"\n💾 Full result saved to: {output_file}")
            
            return result_data
            
        except json.JSONDecodeError:
            print(f"⚠️  Response is not JSON, showing raw content:")
            print("-" * 40)
            print(content_text)
            print("-" * 40)
            
            return {"status": "unparsed", "content": content_text}
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}

async def main():
    """Main test function with options for different tools"""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "vector":
        print("🚀 Starting query_vector_only MCP integration test")
        print("=" * 80)
        result = await test_query_vector_only_mcp_integration()

        print("\n" + "=" * 80)
        if result.get("status") == "success":
            print("✅ Vector RAG integration test PASSED!")
            print("🎉 query_vector_only works properly with Vector DB + Claude SDK fallback via MCP")
        elif result.get("status") == "unparsed":
            print("⚠️  Integration test returned non-JSON response")
            print("🔍 Check the raw content above for issues")
            return False
        else:
            print("❌ Vector RAG integration test FAILED!")
            print(f"💥 Error: {result.get('error')}")
            return False

    elif len(sys.argv) > 1 and sys.argv[1] == "hybrid":
        print("🚀 Starting query_hybrid_rag MCP integration test")
        print("=" * 80)
        result = await test_query_hybrid_rag_mcp_integration()
        
        print("\n" + "=" * 80)
        if result.get("status") == "success":
            print("✅ Hybrid RAG integration test PASSED!")
            print("🎉 query_hybrid_rag works properly with Vector + CPG + synthesis + validation workflow via MCP")
        elif result.get("status") == "unparsed":
            print("⚠️  Integration test returned non-JSON response")
            print("🔍 Check the raw content above for issues")
            return False
        else:
            print("❌ Hybrid RAG integration test FAILED!")
            print(f"💥 Error: {result.get('error')}")
            return False
            
    elif len(sys.argv) > 1 and sys.argv[1] == "both":
        print("🚀 Running both CPG RAG and Hybrid RAG tests")
        print("=" * 80)
        print("TESTING CPG RAG (CPG-only)")
        print("=" * 80)
        result1 = await test_query_cpg_rag_mcp_integration()
        
        print("\n" + "=" * 80)
        print("TESTING HYBRID RAG (Vector + CPG + Synthesis + Validation)")
        print("=" * 80)
        result2 = await test_query_hybrid_rag_mcp_integration()
        
        print("\n" + "=" * 80)
        print("COMPARISON RESULTS:")
        print("=" * 80)
        print(f"CPG RAG: {'✅ PASSED' if result1.get('status') == 'success' else '❌ FAILED'}")
        print(f"Hybrid RAG: {'✅ PASSED' if result2.get('status') == 'success' else '❌ FAILED'}")
        
        return result1.get("status") == "success" and result2.get("status") == "success"
        
    else:
        print("🚀 Starting query_cpg_rag MCP integration test (default)")
        print("=" * 80)
        result = await test_query_cpg_rag_mcp_integration()
        
        print("\n" + "=" * 80)
        if result.get("status") == "success":
            print("✅ CPG RAG integration test PASSED!")
            print("🎉 query_cpg_rag works properly with LangGraph workflow via MCP")
        elif result.get("status") == "unparsed":
            print("⚠️  Integration test returned non-JSON response")
            print("🔍 Check the saved output file for details")
            return False
        else:
            print("❌ CPG RAG integration test FAILED!")
            print(f"💥 Error: {result.get('error')}")
            return False
    
    return True

if __name__ == "__main__":
    print("Available test options:")
    print("  python test_query_cpg_rag_mcp_integration.py                # Test CPG RAG only (default)")
    print("  python test_query_cpg_rag_mcp_integration.py vector         # Test Vector RAG only")
    print("  python test_query_cpg_rag_mcp_integration.py hybrid         # Test Hybrid RAG (Vector + CPG + Synthesis)")
    print("  python test_query_cpg_rag_mcp_integration.py both           # Test both CPG and Hybrid RAG tools")
    print()
    
    success = asyncio.run(main())
    if not success:
        exit(1)