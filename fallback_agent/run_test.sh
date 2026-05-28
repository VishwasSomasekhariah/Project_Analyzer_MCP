#!/bin/bash
# Test runner script for Claude Code OpenAI Adapter

set -e

echo "=================================================================="
echo "CLAUDE CODE OPENAI ADAPTER - TEST RUNNER"
echo "=================================================================="
echo ""

# Check if adapter is already running
if curl -s http://localhost:8889/ > /dev/null 2>&1; then
    echo "✅ Adapter server already running on port 8889"
    echo ""
    echo "Running tests..."
    echo ""
    uv run python3 test_adapter.py
else
    echo "🚀 Starting adapter server in background..."
    uv run python3 claude_code_openai_adapter.py > /tmp/adapter.log 2>&1 &
    ADAPTER_PID=$!

    echo "   Server PID: $ADAPTER_PID"
    echo "   Waiting for server to start..."

    # Wait for server to be ready (max 10 seconds)
    for i in {1..10}; do
        sleep 1
        if curl -s http://localhost:8889/ > /dev/null 2>&1; then
            echo "   ✅ Server ready!"
            break
        fi
        echo -n "."
    done
    echo ""

    # Check if server actually started
    if ! curl -s http://localhost:8889/ > /dev/null 2>&1; then
        echo "❌ Server failed to start. Check /tmp/adapter.log for errors"
        cat /tmp/adapter.log
        exit 1
    fi

    echo ""
    echo "Running tests..."
    echo ""

    # Run tests
    uv run python3 test_adapter.py
    TEST_EXIT_CODE=$?

    # Clean up
    echo ""
    echo "Stopping adapter server..."
    kill $ADAPTER_PID 2>/dev/null || true

    exit $TEST_EXIT_CODE
fi
