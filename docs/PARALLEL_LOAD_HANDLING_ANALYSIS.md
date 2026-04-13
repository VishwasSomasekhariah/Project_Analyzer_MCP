# Parallel Load Handling Analysis

## The Two Timeout Issues

### Issue 1: Single Query Timeout ✅ FIXED
**Cause:** One query takes > 10 seconds
**Fix:** Increased client timeout to 60s
**Status:** ✅ Complete

### Issue 2: Parallel Request Blocking ⚠️ NEEDS VERIFICATION
**Cause:** Multiple parallel queries compete for resources
**Symptoms:**
- Some queries timeout while waiting for others
- "Error in post_writer" when server is under heavy load
- Unpredictable timeouts (works sometimes, fails other times)

---

## How Parallel Load Currently Works

### Architecture

```
Multi-Agent Orchestrator
  ├─ SubQuery 1 ──> asyncio.gather ──> CoT Agent 1 ──┐
  ├─ SubQuery 2 ──> asyncio.gather ──> CoT Agent 2 ──┤
  ├─ SubQuery 3 ──> asyncio.gather ──> CoT Agent 3 ──┤
  └─ SubQuery 4 ──> asyncio.gather ──> CoT Agent 4 ──┘
                                                       │
                                                       ▼
                                             MCPSessionPool
                                                       │
                                    ┌──────────────────┼──────────────────┐
                                    ▼                  ▼                  ▼
                               Session 1          Session 2          Session 3
                                    │                  │                  │
                                    └──────────────────┴──────────────────┘
                                                       ▼
                                              Neo4j MCP Server
                                              (Port 8100)
```

### Current Implementation

**File:** `src/core/graph_rag/adapters/session_pool.py`

```python
class MCPSessionPool:
    """Each acquire_session() creates a NEW SSE connection"""

    async def acquire_session(self, session_id: Optional[str] = None):
        # Each call creates a UNIQUE session
        session_id = f"session_{len(self._active_sessions) + 1}_{id(asyncio.current_task())}"

        # New SSE connection for this session
        connector = HttpConnector(...)
        session = MCPSession(connector)
        await session.initialize()  # Opens new SSE stream
```

**Key Points:**
1. ✅ Each parallel agent gets its **own SSE session**
2. ✅ Sessions are **not shared** between parallel tasks
3. ✅ Each session has its own **POST endpoint**
4. ⚠️ All sessions hit the **same Neo4j MCP server**

---

## Potential Bottlenecks

### 1. Neo4j MCP Server Concurrency

**Question:** Can the server handle multiple simultaneous connections?

Let's check:

```bash
# Check how many connections the server can handle
ps aux | grep neo4j_mcp_server
netstat -an | grep 8100 | wc -l
```

**FastMCP/Starlette Default:**
- Uses `uvicorn` which is async
- Should handle multiple connections concurrently
- But: **Underlying Neo4j driver may serialize**

### 2. Neo4j Database Connection Pool

**File:** `neo4j-mcp-server/neo4j_mcp_server/tools/neo4j_memory/tools.py`

```python
self.driver = AsyncGraphDatabase.driver(
    ...,
    max_connection_pool_size=50,  # ← This is good!
    connection_timeout=30
)
```

✅ **Good news:** Connection pool is set to 50 connections

### 3. SSE Write Stream Blocking

**The Real Issue:**

Each MCP session has a **single SSE write stream** that is sequential:

```python
# From MCP SDK
async def post_writer(endpoint_url: str):
    async for session_message in write_stream_reader:
        # ← This is SEQUENTIAL per session
        response = await client.post(endpoint_url, json=...)
        response.raise_for_status()
```

**If sessions are shared (they shouldn't be):**
- Request 1 POSTs → waits for response
- Request 2 tries to POST → **blocks on write stream**
- Request 2 times out after 60s → "Error in post_writer"

**If sessions are NOT shared (current code):**
- Request 1 → Session 1 → POST → Neo4j
- Request 2 → Session 2 → POST → Neo4j
- Both proceed in parallel ✅

---

## Verification Needed

### Test: Parallel Load Under Timeout

Let's verify if multiple parallel queries cause blocking:

```python
import asyncio
import time

async def parallel_load_test():
    """Test if parallel queries block each other"""
    from src.core.graph_rag.adapters.session_pool import MCPSessionPool
    import json

    with open("neo4j_config.json") as f:
        config = json.load(f)

    pool = MCPSessionPool(config)

    async def run_query(query_id: int):
        start = time.time()
        try:
            # Each gets its own session
            session_id, session = await pool.acquire_session()

            # Simulate medium-complexity query
            result = await session.call_tool(
                "neo4j_execute_query",
                {
                    "query": f"""
                        MATCH (n)
                        WITH n LIMIT 100
                        OPTIONAL MATCH (n)-[r]-(m)
                        RETURN n, count(r) as rels
                        LIMIT 50
                    """
                }
            )

            elapsed = time.time() - start
            print(f"Query {query_id}: {elapsed:.2f}s ✅")

            await pool.release_session(session_id)
            return elapsed

        except Exception as e:
            elapsed = time.time() - start
            print(f"Query {query_id}: {elapsed:.2f}s ❌ {e}")
            if "post_writer" in str(e):
                print(f"  🚨 BLOCKING DETECTED!")
            return None

    # Launch 10 queries in parallel
    print("Launching 10 parallel queries...")
    tasks = [run_query(i) for i in range(10)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Analyze results
    successes = [r for r in results if r is not None]
    failures = [r for r in results if r is None]

    print(f"\nResults:")
    print(f"  Successes: {len(successes)}")
    print(f"  Failures: {len(failures)}")

    if successes:
        avg_time = sum(successes) / len(successes)
        max_time = max(successes)
        print(f"  Avg time: {avg_time:.2f}s")
        print(f"  Max time: {max_time:.2f}s")

    # Expected behavior:
    # - If sessions are isolated: All succeed, similar times
    # - If blocking occurs: Some timeout, varying times
```

---

## Solutions (If Blocking Occurs)

### Solution 1: Request Queuing (Server-Side)

Implement a queue on the Neo4j MCP server:

```python
# In neo4j-mcp-server/server.py

from asyncio import Queue, Semaphore

class Neo4jRequestQueue:
    """Queue requests to prevent overwhelming Neo4j"""

    def __init__(self, max_concurrent: int = 10):
        self._semaphore = Semaphore(max_concurrent)

    async def execute(self, query_func):
        async with self._semaphore:
            return await query_func()

# Global queue
request_queue = Neo4jRequestQueue(max_concurrent=10)

@mcp.tool()
async def neo4j_execute_query(query: str, ...):
    # Queue the request
    async def query_func():
        return await neo4j_graph.execute_query(query, params)

    return await request_queue.execute(query_func)
```

**Benefits:**
- Limits concurrent Neo4j queries
- Prevents overwhelming the database
- Fair queuing (FIFO)

### Solution 2: Client-Side Semaphore

Add concurrency control to the session pool:

```python
class MCPSessionPool:
    def __init__(self, ..., max_concurrent_requests: int = 20):
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def call_tool_with_semaphore(self, session, tool_name, args):
        async with self._request_semaphore:
            return await session.call_tool(tool_name, args)
```

### Solution 3: Connection Pool Reuse

Instead of creating new sessions, reuse a pool:

```python
class MCPSessionPool:
    def __init__(self, ..., pool_size: int = 10):
        self._pool: Queue[MCPSession] = Queue()
        # Pre-create pool_size sessions

    async def acquire_session(self):
        # Get from pool (waits if all busy)
        session = await self._pool.get()
        return session

    async def release_session(self, session):
        # Return to pool
        await self._pool.put(session)
```

**Note:** This is complex with SSE sessions due to state management.

---

## Recommended Actions

### 1. Run Parallel Load Test (5 minutes)

```bash
# Create test file
cat > test_parallel_load.py << 'EOF'
[paste parallel_load_test code above]
EOF

# Run test
python test_parallel_load.py

# Expected output:
# - If isolated: All queries succeed in ~0.5-2s
# - If blocking: Some fail with timeout after 60s
```

### 2. Monitor Active Connections (During Load)

```bash
# Terminal 1: Run parallel load test
python test_parallel_load.py

# Terminal 2: Monitor connections
watch -n 1 'netstat -an | grep 8100 | wc -l'

# Expected:
# - Should see 10-20 connections during test
# - If you see only 1-2: Sessions are being serialized
```

### 3. Check Neo4j MCP Server Logs

```bash
# Look for concurrency issues
tail -f logs/server.log | grep -E "session_id|POST|query"

# If you see sequential processing:
# [21:00:00] Session A starts
# [21:00:05] Session A finishes
# [21:00:05] Session B starts  ← Should overlap!
```

---

## Current Assessment

Based on code review:

✅ **Likely OK:**
- Each parallel agent gets its own session
- Sessions have separate SSE connections
- Neo4j pool size is adequate (50 connections)
- Server (uvicorn) supports concurrent connections

⚠️ **Potential Issues:**
- If many parallel queries (10+) all hit at once
- If Neo4j queries themselves are slow (table lock)
- If server has hidden serialization

**Probability:** **Low** - The architecture looks sound

**But:** Worth testing under realistic load to confirm

---

## Next Steps

1. **Run the parallel load test** to verify no blocking
2. **Monitor during real workflow** with 5+ parallel subqueries
3. **If blocking detected:** Implement server-side queue (Solution 1)
4. **If no blocking:** Current setup is fine, timeout fix was sufficient

Would you like me to:
- [ ] Create the parallel load test script?
- [ ] Add monitoring to your workflow?
- [ ] Implement request queuing preemptively?
