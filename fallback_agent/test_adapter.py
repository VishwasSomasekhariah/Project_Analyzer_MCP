#!/usr/bin/env python3
"""
Test Claude Code OpenAI Adapter

This script tests that the adapter works correctly by:
1. Making OpenAI-compatible API calls to the adapter
2. Verifying responses are returned correctly
3. Testing both non-streaming and streaming modes
"""

import asyncio
import sys
from openai import OpenAI
import time


def test_adapter_simple():
    """Test basic non-streaming request."""
    print("=" * 70)
    print("TEST 1: Basic Non-Streaming Request")
    print("=" * 70)

    try:
        # Create OpenAI client pointing to adapter
        client = OpenAI(
            base_url="http://localhost:8889/v1",
            api_key="not-needed"  # Claude Code uses CLI auth
        )

        print("\n📤 Sending request: 'What is 25 * 47?'")
        start = time.time()

        response = client.chat.completions.create(
            model="claude-haiku-4.5",
            messages=[
                {"role": "user", "content": "What is 25 * 47? Just give the number."}
            ],
            temperature=0.0
        )

        elapsed = time.time() - start

        print(f"\n✅ Response received in {elapsed:.2f}s:")
        print(f"   Model: {response.model}")
        print(f"   Content: {response.choices[0].message.content}")
        print(f"   Tokens: {response.usage.total_tokens}")
        print(f"   Finish reason: {response.choices[0].finish_reason}")

        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_adapter_with_system_prompt():
    """Test with system prompt (like RAG workflows use)."""
    print("\n" + "=" * 70)
    print("TEST 2: With System Prompt (RAG-style)")
    print("=" * 70)

    try:
        client = OpenAI(
            base_url="http://localhost:8889/v1",
            api_key="not-needed"
        )

        print("\n📤 Sending request with system prompt...")
        start = time.time()

        response = client.chat.completions.create(
            model="claude-sonnet-4.5",
            messages=[
                {
                    "role": "system",
                    "content": "You are a code analysis expert. Be concise."
                },
                {
                    "role": "user",
                    "content": "What does the CreateWorkers method return in C#?"
                }
            ],
            temperature=0.7,
            max_tokens=200
        )

        elapsed = time.time() - start

        print(f"\n✅ Response received in {elapsed:.2f}s:")
        print(f"   Model: {response.model}")
        print(f"   Content: {response.choices[0].message.content}")

        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_adapter_streaming():
    """Test streaming response."""
    print("\n" + "=" * 70)
    print("TEST 3: Streaming Response")
    print("=" * 70)

    try:
        client = OpenAI(
            base_url="http://localhost:8889/v1",
            api_key="not-needed"
        )

        print("\n📤 Sending streaming request...")
        print("📥 Streaming response:\n")

        stream = client.chat.completions.create(
            model="claude-haiku-4.5",
            messages=[
                {"role": "user", "content": "Count from 1 to 5."}
            ],
            stream=True
        )

        full_response = ""
        for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                print(content, end="", flush=True)
                full_response += content

        print(f"\n\n✅ Streaming completed")
        print(f"   Full response: {full_response}")

        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_list_models():
    """Test /v1/models endpoint."""
    print("\n" + "=" * 70)
    print("TEST 4: List Models Endpoint")
    print("=" * 70)

    try:
        client = OpenAI(
            base_url="http://localhost:8889/v1",
            api_key="not-needed"
        )

        print("\n📤 Fetching available models...")

        models = client.models.list()

        print(f"\n✅ Found {len(models.data)} models:")
        for model in models.data:
            print(f"   • {model.id} (owned by: {model.owned_by})")

        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return False


def test_rag_workflow_config():
    """Test that the config format works with SystemConfig."""
    print("\n" + "=" * 70)
    print("TEST 5: RAG Workflow Configuration")
    print("=" * 70)

    try:
        # Add project root to path
        sys.path.insert(0, "/opt/genpod")

        from src.core.graph_rag.core.config import SystemConfig, LLMConfig

        # Test LLMConfig
        print("\n📤 Creating LLMConfig with adapter URL...")

        llm_config = LLMConfig(
            model="claude-sonnet-4.5",
            base_url="http://localhost:8889/v1",
            api_key="not-needed",
            temperature=0.0
        )

        print(f"   ✅ LLMConfig created:")
        print(f"      Model: {llm_config.model}")
        print(f"      Base URL: {llm_config.base_url}")

        # Create OpenAI client
        print("\n📤 Creating OpenAI client from LLMConfig...")
        client = llm_config.create_client()

        print(f"   ✅ Client created: {type(client).__name__}")

        # Test a simple call
        print("\n📤 Testing client with simple query...")
        response = client.chat.completions.create(
            **llm_config.to_openai_kwargs(),
            messages=[{"role": "user", "content": "Say 'Configuration works!'"}]
        )

        print(f"   ✅ Response: {response.choices[0].message.content}")

        return True

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_server_running():
    """Check if adapter server is running."""
    import requests

    try:
        response = requests.get("http://localhost:8889/", timeout=2)
        return response.status_code == 200
    except:
        return False


def main():
    print("\n" + "=" * 70)
    print("CLAUDE CODE OPENAI ADAPTER - TEST SUITE")
    print("=" * 70)

    # Check if server is running
    print("\n🔍 Checking if adapter server is running...")
    if not check_server_running():
        print("\n❌ Adapter server not running!")
        print("\n📝 Start the server first:")
        print("   python3 claude_code_openai_adapter.py")
        print("\n   Then run this test again.")
        return

    print("✅ Adapter server is running\n")

    # Run tests
    results = []

    results.append(("Basic Request", test_adapter_simple()))
    results.append(("System Prompt", test_adapter_with_system_prompt()))
    results.append(("Streaming", test_adapter_streaming()))
    results.append(("List Models", test_list_models()))
    results.append(("RAG Config", test_rag_workflow_config()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print(f"\nResults: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Claude Code adapter is working correctly.")
        print("\n📝 Next steps:")
        print("   1. Update your RAG workflow config to use:")
        print('      base_url="http://localhost:8889/v1"')
        print("   2. Run your workflow - it will now use Claude Code!")
    else:
        print("\n⚠️  Some tests failed. Check the errors above.")

    print("=" * 70)


if __name__ == "__main__":
    main()
