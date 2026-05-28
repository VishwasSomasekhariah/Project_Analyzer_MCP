#!/usr/bin/env python3
"""
Debug script to test Cypher generation directly
"""

import asyncio
import json
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from core.llm_service import LLMService

async def test_cypher_generation():
    """Test Cypher generation directly with the LLM service."""
    
    # Initialize LLM service
    llm_service = LLMService()
    
    # Sample user query
    user_query = "What is the overall architecture of this application? Identify the main architectural patterns used."
    
    # Sample filtered results (simulating what would come from vector search)
    filtered_results = [
        {
            "type": "File",
            "properties": {
                "name": "Manager.cs",
                "file_path": "/opt/HelloWorldApp/HelloWorldApp/Manager.cs",
                "content": "public class Manager : INotifier { public void Run() { Console.WriteLine(\"Manager starting work...\"); } }"
            }
        },
        {
            "type": "Function",
            "properties": {
                "name": "Run",
                "file_path": "/opt/HelloWorldApp/HelloWorldApp/Manager.cs",
                "start_line": 7,
                "body": "Console.WriteLine(\"Manager starting work...\");"
            }
        }
    ]
    
    print("=== Testing Cypher Generation ===")
    print(f"User Query: {user_query}")
    print(f"Filtered Results: {len(filtered_results)} items")
    print()
    
    try:
        # Generate Cypher queries
        result = await llm_service.generate_cypher_query(user_query, filtered_results)
        
        print("=== LLM Response ===")
        print(json.dumps(result, indent=2))
        print()
        
        # Check if queries were generated
        if "primary_query" in result:
            print("✅ Primary query generated:", result["primary_query"])
        else:
            print("❌ No primary query found")
            
        if "supporting_queries" in result:
            print("✅ Supporting queries generated:", len(result["supporting_queries"]))
            for i, query in enumerate(result["supporting_queries"]):
                print(f"  {i+1}. {query}")
        else:
            print("❌ No supporting queries found")
            
        if "query_explanation" in result:
            print("✅ Query explanation provided")
        else:
            print("❌ No query explanation found")
            
    except Exception as e:
        print(f"❌ Error during Cypher generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_cypher_generation())