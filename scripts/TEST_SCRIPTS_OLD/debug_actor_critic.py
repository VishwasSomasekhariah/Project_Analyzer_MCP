#!/usr/bin/env python3
"""Debug script to test Actor-Critic validation with logging."""

import asyncio
import json
import subprocess
import sys

async def test_with_verbose_logging():
    """Test vector_only_query with verbose logging to see Actor-Critic stages."""
    
    print("🐛 Debug: Testing Actor-Critic validation with verbose logging")
    print("=" * 60)
    
    # T060 test query - the one that was hallucinating
    test_query = "Which class method formats the notification message that gets printed to console in each worker?"
    expected = "Utilities.Helper.FormatMessage"
    
    print(f"📝 Query: {test_query}")
    print(f"🎯 Expected: {expected}")
    print()
    
    # Run CLI directly with logging
    cmd = [
        "codebase-vector-rag",
        "--query", test_query,
        "--collection", "helloworldapp-benchmarking",
        "--max-results", "10",
        "--output-format", "json",
        "--verbose"  # Enable verbose logging
    ]
    
    print(f"🔧 Running command: {' '.join(cmd)}")
    print()
    
    try:
        # Run with captured output and real-time stderr for logs
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        stdout, stderr = process.communicate()
        
        print("📋 STDERR (Logs):")
        print("-" * 40)
        print(stderr)
        print("-" * 40)
        
        print("\n📋 STDOUT (Result):")
        print("-" * 40)
        
        try:
            result = json.loads(stdout)
            print(f"Status: {result.get('status', 'unknown')}")
            print(f"AI Response: {result.get('response', 'No response')}")
            print(f"Raw results count: {len(result.get('results', []))}")
            
            # Check if FormatMessage is mentioned
            ai_response = result.get('response', '')
            mentions_format = 'FormatMessage' in ai_response
            mentions_helper = 'Helper' in ai_response
            mentions_utilities = 'Utilities' in ai_response
            
            print(f"\n✅ Mentions FormatMessage: {mentions_format}")
            print(f"✅ Mentions Helper: {mentions_helper}") 
            print(f"✅ Mentions Utilities: {mentions_utilities}")
            
            if mentions_format and mentions_helper:
                print("🎉 SUCCESS: Correctly identifies FormatMessage!")
            else:
                print("❌ STILL HALLUCINATING: Missing correct method")
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing failed: {e}")
            print("Raw output:")
            print(stdout)
        
        print("-" * 40)
        
    except Exception as e:
        print(f"❌ Command failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_with_verbose_logging())