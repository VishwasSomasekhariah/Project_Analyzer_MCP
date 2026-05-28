#!/usr/bin/env python3
"""
Minimal test to verify Claude adapter can connect via OpenAI-compatible API.
"""

from openai import OpenAI


def main():
    print("Testing Claude Code Adapter via OpenAI API...")
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
                {"role": "user", "content": "Say 'Hello!' and nothing else"}
            ],
            temperature=0.0
        )

        print(f"Response received:")
        print(f"  Model: {response.model}")
        print(f"  Content: {response.choices[0].message.content}")
        print(f"  Tokens: {response.usage.total_tokens}")
        print(f"  Finish reason: {response.choices[0].finish_reason}")

        print("-" * 70)
        print(f"✅ Test passed successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")
        print(f"Error type: {type(e).__name__}")

        # More detailed error info
        import traceback
        print("\nDetailed traceback:")
        traceback.print_exc()


if __name__ == "__main__":
    main()
