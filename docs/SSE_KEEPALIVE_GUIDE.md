# SSE Keep-Alive and Connection Management Guide

## Understanding Your Error: "Error in post_writer"

**Source:** MCP SDK (`/usr/local/lib/python3.12/site-packages/mcp/client/sse.py:135`)

### SSE Architecture in MCP

The MCP SSE client uses **two communication channels**:

```
Client ←─────── SSE Stream (GET) ───────── Server
       │        (long-lived, server→client)
       │
       └─────── POST Requests ─────────→ Server
                (for client messages)
```

1. **SSE Reader** (`sse_reader`): Long-lived GET connection
   - Receives events from server
   - Timeout: **5 minutes** (`sse_read_timeout=300s`)

2. **POST Writer** (`post_writer`): Short-lived POST requests
   - Sends client messages
   - Timeout: **5 seconds** (`timeout=5s`)
   - **This is where your error occurs!**

### Why the Error Happens

```python
# From mcp/client/sse.py:114-137
async def post_writer(endpoint_url: str):
    try:
        async for session_message in write_stream_reader:
            response = await client.post(
                endpoint_url,
                json=session_message.message.model_dump(...),
            )
            response.raise_for_status()  # ← Times out here!
    except Exception as exc:
        logger.error(f"Error in post_writer: {exc}")  # ← Your error
```

**The problem:**
- Client POSTs a message to the server
- Server takes > 5 seconds to respond (processing Neo4j query, etc.)
- HTTP POST timeout expires
- Connection drops: "Error in post_writer"

### Common Causes

1. **Slow Server Processing**
   - Complex Neo4j queries
   - Large vector searches
   - Heavy computation

2. **Network/Proxy Timeouts**
   - Load balancers (30-60s default)
   - Reverse proxies (60s default)
   - Cloud providers (varies)

3. **Server Not Responding**
   - Server crashed/busy
   - Endpoint not available

---

## Who's Responsible for Keep-Alive?

### Answer: **BOTH**, but primarily the **SERVER**

### Server Responsibilities ✅ PRIMARY

**1. Send Keep-Alive Events on SSE Stream**

The server MUST send periodic events to prevent the SSE connection from timing out:

```python
# Server side - Send keep-alive every 15-30 seconds
async def sse_handler(request):
    async def event_generator():
        while True:
            # Send keep-alive comment
            yield ": keep-alive\n\n"
            await asyncio.sleep(15)  # Every 15 seconds

            # Or send a heartbeat event
            yield "event: ping\ndata: {}\n\n"
            await asyncio.sleep(30)
```

**Why this is critical:**
- Prevents load balancer/proxy timeouts (typically 60s)
- Keeps TCP connection alive
- Prevents client disconnect

**2. Respond Quickly to POST Requests**

For long-running operations, use **async pattern**:

```python
# BAD: Synchronous processing (causes timeout)
@app.post("/messages")
async def handle_message(msg: Message):
    result = await long_running_query()  # Takes 30 seconds!
    return {"result": result}  # Client times out before this


# GOOD: Async processing with 202 Accepted
@app.post("/messages")
async def handle_message(msg: Message):
    # Immediately accept the request
    task_id = str(uuid.uuid4())

    # Start background processing
    asyncio.create_task(process_message_async(msg, task_id))

    # Return immediately
    return Response(status_code=202)  # Accepted

    # Then send result via SSE when ready:
    # event: message
    # data: {"id": "...", "result": {...}}
```

**3. Handle POST Timeout Gracefully**

Don't fail silently if POST takes too long:

```python
async def handle_message(msg: Message):
    try:
        # Set server-side timeout
        result = await asyncio.wait_for(
            process_query(msg),
            timeout=4.5  # Slightly less than client timeout
        )
        return {"result": result}
    except asyncio.TimeoutError:
        # Send 202 and process async
        asyncio.create_task(process_async(msg))
        return Response(status_code=202)
```

### Client Responsibilities

**1. Handle Reconnection**

```python
async def connect_with_retry(url: str, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with sse_client(url, timeout=10) as (read, write):
                yield read, write
                return
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
```

**2. Increase Timeout for Known Long Operations**

```python
# Increase timeout for specific operations
async with sse_client(
    url,
    timeout=30,  # Increase from default 5s
    sse_read_timeout=300  # Keep SSE timeout at 5min
) as (read, write):
    # Your code here
```

**3. Handle Partial Failures**

```python
try:
    result = await mcp_client.call_tool(name, args)
except Exception as e:
    if "post_writer" in str(e):
        # Connection lost, try to reconnect
        await reconnect()
    raise
```

---

## Solutions for Your Codebase

### Option 1: Increase Client Timeout (Quick Fix)

Find where you create SSE clients and increase timeout:

```python
# In your MCP client code
async with sse_client(
    url,
    timeout=30,  # Increase to 30 seconds
    sse_read_timeout=300
) as (read, write):
    # Your code
```

### Option 2: Fix Server to Send Keep-Alives (Proper Fix)

Update your MCP servers to send periodic keep-alive:

```python
# In neo4j-mcp-server/server.py or code-analysis-mcp-server/server.py

from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse

@app.get("/sse")
async def sse_endpoint():
    async def event_generator():
        # Send initial endpoint
        yield {"event": "endpoint", "data": "/messages"}

        # Keep-alive loop
        while True:
            yield ": keep-alive\n"  # Comment format
            await asyncio.sleep(15)  # Every 15 seconds

    return EventSourceResponse(event_generator())
```

### Option 3: Server Async Processing (Best Practice)

Make your server respond immediately and process async:

```python
# Example for Neo4j query tool
from fastapi import BackgroundTasks

pending_responses = {}  # Store results keyed by request ID

@app.post("/messages")
async def handle_message(message: dict, background_tasks: BackgroundTasks):
    request_id = message.get("id")

    # For long-running queries, process in background
    if is_long_running_query(message):
        background_tasks.add_task(process_query_async, request_id, message)
        return Response(status_code=202)  # Accepted

    # For quick queries, process synchronously
    result = await process_query(message)
    return {"jsonrpc": "2.0", "id": request_id, "result": result}

async def process_query_async(request_id: str, message: dict):
    """Process query and send result via SSE."""
    result = await execute_neo4j_query(message)
    pending_responses[request_id] = result
    # SSE event loop will pick this up and send to client
```

---

## Debugging Your Specific Errors

Your logs show two error patterns:

### Error 1: Empty Exception
```
ERROR - Error in post_writer:
```
**Cause:** Connection closed without error message (server died/restarted)
**Fix:** Add server-side keep-alive

### Error 2: Connection Failed
```
ERROR - Error in post_writer: All connection attempts failed
```
**Cause:** Server not responding/available
**Fix:** Check server health, add retry logic

### Error 3: Incomplete Chunked Read
```
ERROR - Error in sse_reader: peer closed connection without sending complete message body
```
**Cause:** Server closed SSE stream mid-message
**Fix:** Ensure server sends complete HTTP chunks

---

## Recommended Implementation Order

1. **Immediate (Stop errors):**
   - Increase client timeout to 30s
   - Add retry logic on connection failures

2. **Short-term (Improve reliability):**
   - Add server-side keep-alive (15s interval)
   - Monitor server processing times

3. **Long-term (Best practice):**
   - Implement async processing (202 Accepted pattern)
   - Add health checks and monitoring
   - Implement proper error recovery

---

## Testing Keep-Alive

Test if keep-alive is working:

```bash
# Watch SSE stream (should see events every 15-30s)
curl -N -H "Accept: text/event-stream" http://localhost:8000/sse

# Expected output:
# event: endpoint
# data: /messages
#
# : keep-alive
# : keep-alive
# ...
```

---

## Summary

**Root Cause:** Server takes too long to respond to POST requests

**Primary Responsibility:** Server must:
1. Send SSE keep-alive events every 15-30s
2. Respond to POST within 5s (or use async pattern)
3. Handle long operations asynchronously

**Client Should:**
1. Increase timeout for known long operations
2. Handle reconnection gracefully
3. Retry failed requests

**Quick Fix:** Increase `timeout` parameter in `sse_client()` calls
**Proper Fix:** Add server-side keep-alive and async processing
