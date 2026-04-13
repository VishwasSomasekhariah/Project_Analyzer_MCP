#!/bin/bash
# Test if Neo4j MCP server sends keep-alive (ping) events

echo "Testing SSE keep-alive from Neo4j MCP server..."
echo "Watching for ping events (should see one every ~15 seconds)"
echo "Press Ctrl+C to stop"
echo ""

# Connect to SSE endpoint and watch for events
timeout 60 curl -N -H "Accept: text/event-stream" http://localhost:8100/sse 2>&1 | while read line; do
    timestamp=$(date '+%H:%M:%S')
    echo "[$timestamp] $line"
done

echo ""
echo "Test complete!"
