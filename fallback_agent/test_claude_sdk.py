#!/usr/bin/env python3
"""
Test Claude Code via OpenAI-compatible adapter.

Tests basic inference functionality through the adapter.
Note: Tool tests require Claude SDK directly (not supported by adapter).
"""

from openai import OpenAI


def test_basic_query():
    """Test a simple query via the adapter."""
    print("=" * 70)
    print("Testing Claude via OpenAI Adapter")
    print("=" * 70)

    print("\nUsing OpenAI-compatible adapter (no API key needed!)")
    print("Adapter connects to Claude Code CLI\n")

    print("Sending query to Claude via adapter...")
    print("-" * 70)

    try:
        # Create OpenAI client pointing to adapter
        client = OpenAI(
            base_url="http://localhost:8889/v1",
            api_key="not-needed"  # Claude Code uses CLI auth
        )

        # Simple test query
        response = client.chat.completions.create(
            model="claude-haiku-4.5",
            messages=[
                {"role": "user", "content": "Say 'Hello from Claude via adapter!' and nothing else"}
            ],
            temperature=0.0
        )

        print(f"Response received:")
        print(f"  Model: {response.model}")
        print(f"  Content: {response.choices[0].message.content}")
        print(f"  Tokens: {response.usage.total_tokens}")
        print(f"  Finish reason: {response.choices[0].finish_reason}")

        print("-" * 70)
        print("✅ SUCCESS! Claude Code adapter is working!")
        return True

    except Exception as e:
        print(f"❌ ERROR: {e}")
        print("\nPossible issues:")
        print("1. Adapter server not running (python3 claude_code_openai_adapter.py)")
        print("2. Claude Code CLI not installed")
        print("3. Not logged in to Claude Code")

        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        return False


def main():
    """Run basic test."""
    print("\n🚀 Starting Claude Adapter Test\n")

    # Test basic query
    basic_ok = test_basic_query()

    if basic_ok:
        print("\n" + "=" * 70)
        print("🎉 Test completed!")
        print("=" * 70)
        print("\nNote: Tool/function calling tests require Claude SDK directly")
        print("The adapter is inference-only (no tools support)")
    else:
        print("\n⚠️  Test failed")


if __name__ == "__main__":
    main()
