#!/usr/bin/env python3
"""
Debug RAG Pipeline - Step by Step Analysis
"""

import asyncio
import json
import sys
sys.path.append('src')

from src.core.entity_extraction_service import EntityExtractionService
from src.core.subgraph_planner import SubgraphPlanner
from src.core.graph_query_executor import GraphQueryExecutor
from src.core.content_reranker import ContentReranker
from src.core.llm_service import LLMService
from src.core.intent_classifier import IntentClassifier

async def debug_rag_pipeline():
    """Debug each step of the RAG pipeline"""
    print("🔧 Debugging RAG Pipeline Step by Step...")
    
    user_query = "How many comment lines are in WorkerA.cs?"
    config_path = "/opt/genpod/neo4j_config.json"
    
    try:
        # Step 1: Test LLM Service initialization
        print("\n1️⃣ Testing LLM Service Initialization...")
        try:
            llm_service = LLMService({"cache_ttl": 1800})
            print("✅ LLM Service initialized successfully")
        except Exception as e:
            print(f"❌ LLM Service initialization failed: {e}")
            return
        
        # Step 2: Test Entity Extraction
        print("\n2️⃣ Testing Entity Extraction...")
        try:
            entity_service = EntityExtractionService(llm_service)
            entities = await entity_service.extract_entities(user_query)
            print(f"✅ Entities extracted: {entities}")
        except Exception as e:
            print(f"❌ Entity extraction failed: {e}")
            return
        
        # Step 3: Test Intent Classification (standalone)
        print("\n3️⃣ Testing Intent Classification (standalone)...")
        try:
            intent_classifier = IntentClassifier(llm_service)
            intent_result = await intent_classifier.classify_intent(user_query)
            print(f"✅ Intent classified: {intent_result}")
        except Exception as e:
            print(f"❌ Intent classification failed: {e}")
        
        # Step 4: Test Subgraph Planning
        print("\n4️⃣ Testing Subgraph Planning...")
        try:
            planner = SubgraphPlanner()
            plan = await planner.plan_retrieval(entities, user_query)
            print(f"✅ Subgraph plan created with {len(plan.get('seed_queries', []))} seed queries")
            print(f"   Plan keys: {list(plan.keys())}")
        except Exception as e:
            print(f"❌ Subgraph planning failed: {e}")
            return
        
        # Step 5: Test Graph Query Execution
        print("\n5️⃣ Testing Graph Query Execution...")
        try:
            executor = GraphQueryExecutor()
            raw_results = await executor.execute_subgraph_retrieval(plan, config_path)
            print(f"✅ Graph queries executed")
            print(f"   Result keys: {list(raw_results.keys())}")
            print(f"   Total nodes: {raw_results.get('total_nodes', 0)}")
        except Exception as e:
            print(f"❌ Graph query execution failed: {e}")
            return
        
        # Step 6: Test Content Reranking
        print("\n6️⃣ Testing Content Reranking...")
        try:
            reranker = ContentReranker()
            ranked_context = await reranker.rerank_subgraph_results(
                raw_results.get("combined_results", []), 
                entities,
                entities  # Pass entities as intent context
            )
            print(f"✅ Content reranked")
            print(f"   Ranked context keys: {list(ranked_context.keys())}")
            print(f"   Top K selected: {ranked_context.get('top_k_selected', 0)}")
        except Exception as e:
            print(f"❌ Content reranking failed: {e}")
            return
        
        # Step 7: Test Synthesis (the critical step)
        print("\n7️⃣ Testing Synthesis...")
        try:
            final_answer = await llm_service.synthesize_targeted_response(
                ranked_context, user_query, entities
            )
            print(f"✅ Synthesis completed")
            print(f"   Answer keys: {list(final_answer.keys())}")
            print(f"   Answer: {final_answer.get('answer', 'NO_ANSWER')[:100]}...")
            print(f"   Intent detected in synthesis: {final_answer.get('intent_detected', {})}")
        except Exception as e:
            print(f"❌ Synthesis failed: {e}")
            print(f"   Error details: {str(e)}")
            
            # Try to get more details about the synthesis error
            try:
                import traceback
                traceback.print_exc()
            except:
                pass
        
        print(f"\n🎯 Pipeline Debug Complete")
        
    except Exception as e:
        print(f"❌ Overall pipeline failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_rag_pipeline())