#!/usr/bin/env python3
"""
Test dynamic tool loading with the enhanced adapter.

This demonstrates:
1. Starting the adapter with tool support
2. Registering tools dynamically via API
3. Using tools in chat completions
4. Listing and deleting tools
"""

import requests
import json
from openai import OpenAI


def test_dynamic_tools():
    """Test the dynamic tool loading functionality."""
    base_url = "http://localhost:8889"

    print("=" * 70)
    print("TESTING DYNAMIC TOOL LOADING")
    print("=" * 70)

    # Step 1: Check server is running
    print("\n1. Checking server status...")
    try:
        response = requests.get(f"{base_url}/")
        print(f"✅ Server running: {response.json()['message']}")
    except Exception as e:
        print(f"❌ Server not running: {e}")
        print("\nStart the server first:")
        print("  python3 claude_code_openai_adapter_with_tools.py")
        return

    # Step 2: Register a simple tool
    print("\n2. Registering 'get_weather' tool...")
    tool_definition = {
        "name": "get_weather",
        "description": "Get weather information for a city",
        "input_schema": {"city": "str"},
        "code": """async def get_weather(args):
    city = args.get('city', 'Unknown')
    # Simulate weather data
    weather_data = {
        'San Francisco': 'Sunny, 72°F',
        'New York': 'Cloudy, 65°F',
        'London': 'Rainy, 58°F'
    }
    weather = weather_data.get(city, 'Weather data not available')
    return {
        'content': [{
            'type': 'text',
            'text': f'Weather in {city}: {weather}'
        }]
    }
"""
    }

    try:
        response = requests.post(
            f"{base_url}/v1/tools",
            json=tool_definition,
            headers={"Content-Type": "application/json"}
        )
        result = response.json()
        print(f"✅ Tool registered: {result['message']}")
    except Exception as e:
        print(f"❌ Failed to register tool: {e}")
        return

    # Step 3: Register another tool
    print("\n3. Registering 'calculate' tool...")
    calculator_tool = {
        "name": "calculate",
        "description": "Perform basic math calculations",
        "input_schema": {"expression": "str"},
        "code": """async def calculate(args):
    try:
        expression = args.get('expression', '0')
        result = eval(expression, {"__builtins__": {}}, {})
        return {
            'content': [{
                'type': 'text',
                'text': f'Result: {result}'
            }]
        }
    except Exception as e:
        return {
            'content': [{
                'type': 'text',
                'text': f'Error: {str(e)}'
            }],
            'isError': True
        }
"""
    }

    try:
        response = requests.post(
            f"{base_url}/v1/tools",
            json=calculator_tool,
            headers={"Content-Type": "application/json"}
        )
        result = response.json()
        print(f"✅ Tool registered: {result['message']}")
    except Exception as e:
        print(f"❌ Failed to register tool: {e}")

    # Step 4: List all tools
    print("\n4. Listing all registered tools...")
    try:
        response = requests.get(f"{base_url}/v1/tools")
        tools = response.json()
        print(f"✅ Found {len(tools['data'])} tools:")
        for tool in tools['data']:
            print(f"   • {tool['name']}: {tool['description']}")
    except Exception as e:
        print(f"❌ Failed to list tools: {e}")

    # Step 5: Use tools in a chat completion
    print("\n5. Testing chat completion WITH tools...")
    print("-" * 70)

    client = OpenAI(
        base_url=f"{base_url}/v1",
        api_key="not-needed"
    )

    try:
        # Test 1: Weather query
        print("\n📤 Query 1: 'What's the weather in San Francisco?'")
        response = client.chat.completions.create(
            model="claude-sonnet-4.5",
            messages=[
                {"role": "user", "content": "What's the weather in San Francisco? Use the get_weather tool."}
            ],
            tools=["get_weather"],  # Specify which tools to use
            temperature=0.0
        )
        print(f"💬 Response: {response.choices[0].message.content}")

        # Test 2: Calculator
        print("\n📤 Query 2: 'Calculate 245586 * 0.000003'")
        response = client.chat.completions.create(
            model="claude-sonnet-4.5",
            messages=[
                {"role": "user", "content": "Calculate 245586 * 0.000003 using the calculate tool"}
            ],
            tools=["calculate"],
            temperature=0.0
        )
        print(f"💬 Response: {response.choices[0].message.content}")

        # Test 3: Multiple tools
        print("\n📤 Query 3: Both tools available")
        response = client.chat.completions.create(
            model="claude-sonnet-4.5",
            messages=[
                {"role": "user", "content": "What's the weather in London and calculate 100 + 50"}
            ],
            tools=["get_weather", "calculate"],  # Both tools available
            temperature=0.0
        )
        print(f"💬 Response: {response.choices[0].message.content}")

    except Exception as e:
        print(f"❌ Chat completion failed: {e}")
        import traceback
        traceback.print_exc()

    # Step 6: Test WITHOUT tools (inference only)
    print("\n6. Testing chat completion WITHOUT tools...")
    print("-" * 70)

    try:
        response = client.chat.completions.create(
            model="claude-haiku-4.5",
            messages=[
                {"role": "user", "content": "What is 2 + 2? Just tell me the answer."}
            ],
            # No tools parameter = inference only
            temperature=0.0
        )
        print(f"📤 Query: 'What is 2 + 2?'")
        print(f"💬 Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Failed: {e}")

    # Step 7: Delete a tool
    print("\n7. Testing tool deletion...")
    try:
        response = requests.delete(f"{base_url}/v1/tools/get_weather")
        result = response.json()
        print(f"✅ {result['message']}")

        # Verify it's gone
        response = requests.get(f"{base_url}/v1/tools")
        tools = response.json()
        print(f"✅ Remaining tools: {[t['name'] for t in tools['data']]}")
    except Exception as e:
        print(f"❌ Failed to delete tool: {e}")

    print("\n" + "=" * 70)
    print("✅ DYNAMIC TOOL LOADING TEST COMPLETED!")
    print("=" * 70)
    print("\nKey features demonstrated:")
    print("  ✅ Register tools via API (no server restart)")
    print("  ✅ Use tools in chat completions")
    print("  ✅ List registered tools")
    print("  ✅ Delete tools dynamically")
    print("  ✅ Inference-only mode (no tools)")
    print("=" * 70)


if __name__ == "__main__":
    test_dynamic_tools()
