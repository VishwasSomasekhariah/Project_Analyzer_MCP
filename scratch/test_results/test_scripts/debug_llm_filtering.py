#!/usr/bin/env python3
"""
Debug script to test LLM filtering functionality in isolation.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.llm_service import LLMService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Sample vector search results (cleaned up version)
SAMPLE_VECTOR_RESULTS = """
AI Analysis: Notify in Manager.cs, Process in WorkerC.cs, and Process in WorkerB.cs are functions that handle errors or exceptions in the codebase.

Code Results (10 matches):

1. System
File: /opt/HelloWorldApp/HelloWorldApp/Manager.cs | Type: import | Lang: csharp | Lines 1-1
   1 using System;

2. System
File: /opt/HelloWorldApp/HelloWorldApp/Program.cs | Type: import | Lang: csharp | Lines 1-1
   1 using System;

3. System
File: /opt/HelloWorldApp/HelloWorldApp/Manager.cs | Type: import | Lang: csharp | Lines 2-2
   2 using System.Collections.Generic;

4. Manager.Notify Function
File: /opt/HelloWorldApp/HelloWorldApp/Manager.cs | Type: method | Lang: csharp | Lines 25-35
   25    public void Notify(string message)
   26    {
   27        try 
   28        {
   29            Console.WriteLine($"Manager notification: {message}");
   30            foreach (var worker in workers)
   31            {
   32                worker.Process();
   33            }
   34        }
   35        catch (Exception ex) { Console.WriteLine($"Error in Notify: {ex.Message}"); }
   36    }

5. WorkerB.Process Function  
File: /opt/HelloWorldApp/HelloWorldApp/WorkerB.cs | Type: method | Lang: csharp | Lines 15-25
   15    public void Process()
   16    {
   17        try
   18        {
   19            string msg = Utilities.Helper.FormatMessage("WorkerB", "Processing task B");
   20            Console.WriteLine(msg);
   21            _notifier.Notify("WorkerB has finished processing.");
   22        }
   23        catch (Exception ex)
   24        {
   25            Console.WriteLine($"WorkerB error: {ex.Message}");
   26        }
   27    }

6. WorkerC.Process Function
File: /opt/HelloWorldApp/HelloWorldApp/WorkerC.cs | Type: method | Lang: csharp | Lines 18-30
   18    public void Process()
   19    {
   20        try
   21        {
   22            string msg = Utilities.Helper.FormatMessage("WorkerC", "Processing critical task");
   23            Console.WriteLine(msg);
   24            if (SomeCondition()) throw new InvalidOperationException("Critical error");
   25            _notifier.Notify("WorkerC completed successfully.");
   26        }
   27        catch (Exception ex)
   28        {
   29            Console.WriteLine($"WorkerC critical error: {ex.Message}");
   30        }
   31    }
"""

async def test_llm_filtering():
    """Test the LLM filtering with cleaned up input."""
    logger.info("Testing LLM filtering functionality")
    
    llm_service = LLMService()
    
    user_query = "Find all functions that handle errors or exceptions in the codebase"
    
    logger.info("Testing with cleaned vector results...")
    result = await llm_service.filter_code_results(SAMPLE_VECTOR_RESULTS, user_query)
    
    logger.info("=== LLM Filtering Result ===")
    logger.info(json.dumps(result, indent=2))
    
    if "key_concepts" in result:
        logger.info(f"✓ Key concepts: {result['key_concepts']}")
    else:
        logger.warning("❌ No key_concepts found")
        
    if "suggested_cypher_targets" in result:
        logger.info(f"✓ Suggested Cypher targets: {result['suggested_cypher_targets']}")
    else:
        logger.warning("❌ No suggested_cypher_targets found")
        
    # Also test with the original messy format
    logger.info("\n" + "="*50)
    logger.info("Testing with original messy vector results...")
    
    # Read the actual messy results from the test output
    try:
        with open("/opt/genpod/error_feedback_test_results.json", "r") as f:
            test_data = json.load(f)
            original_results = test_data["results"]["steps"]["1_vector_search"]["raw_output"]
            
        result2 = await llm_service.filter_code_results(original_results, user_query)
        
        logger.info("=== LLM Filtering Result (Original Format) ===")
        logger.info(json.dumps(result2, indent=2))
        
        if "key_concepts" in result2:
            logger.info(f"✓ Key concepts: {result2['key_concepts']}")
        else:
            logger.warning("❌ No key_concepts found")
            
    except Exception as e:
        logger.error(f"Could not test original format: {e}")

if __name__ == "__main__":
    asyncio.run(test_llm_filtering())