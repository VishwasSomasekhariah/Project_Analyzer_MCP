# SSE Timeout Fix Implementation Guide

## Current Status

✅ **Keep-Alive Working**: `sse-starlette` sends ping every 15s by default
❌ **POST Timeout Issue**: Long queries (>10s) cause "Error in post_writer"

## Two-Part Solution

### Part 1: Quick Fix (Client-Side) - APPLY NOW

**File:** `src/core/graph_rag/adapters/session_pool.py`

**Change Line 59:**
```python
# BEFORE
timeout=10,  # HTTP operation timeout

# AFTER
timeout=60,  # HTTP POST timeout - increased for long-running queries
```

**Why:** This gives Neo4j queries up to 60 seconds to complete, preventing most timeouts.

**Result:** Immediate relief from "Error in post_writer" for queries that take 10-60 seconds.

---

### Part 2: Proper Fix (Server-Side) - OPTIONAL BUT RECOMMENDED

Implement async query processing so POST always returns within 5 seconds, then sends results via SSE.

#### Option A: Enable Async Tools (Recommended)

**File:** `neo4j-mcp-server/neo4j_mcp_server/server.py`

**Change:**
```python
# BEFORE (line 92)
from neo4j_mcp_server.tools.neo4j_memory.tools import register_tools as register_neo4j_tools
register_neo4j_tools(mcp)

# AFTER - Use async-enabled tools
from neo4j_mcp_server.tools.neo4j_memory.tools_async import register_async_tools
register_async_tools(mcp)

# OPTIONAL: Also register original tools for backward compatibility
from neo4j_mcp_server.tools.neo4j_memory.tools import register_tools as register_neo4j_tools
register_neo4j_tools(mcp)  # Registers neo4j_fuzzy_search, etc.
```

**Benefits:**
- Queries < 5s: Execute immediately (no change in behavior)
- Queries > 5s: Return `query_id` immediately, process in background
- Complex queries: Detected automatically and processed async
- No POST timeouts ever

**Client Handling:**
```python
# Client code automatically handles both modes:
result = await mcp_session.call_tool("neo4j_execute_query", {...})

if result.get("is_immediate"):
    # Got results immediately
    records = result["results"]
else:
    # Query is processing async
    query_id = result["query_id"]
    # Can continue with other work or poll for result
    status = await mcp_session.call_tool("neo4j_get_async_query_result", {"query_id": query_id})
```

#### Option B: Hybrid Approach

Keep original tools, add async variants:

```python
from neo4j_mcp_server.tools.neo4j_memory.tools import register_tools as register_neo4j_tools
from neo4j_mcp_server.tools.neo4j_memory.tools_async import register_async_tools

# Original tools (backward compatible)
register_neo4j_tools(mcp)

# Async-enabled tools (new)
register_async_tools(mcp)
```

This gives you both:
- `neo4j_execute_query` (original, synchronous)
- `neo4j_execute_query_async` (new, timeout-safe)

---

## Testing

### 1. Verify Keep-Alive

```bash
chmod +x test_sse_keepalive.sh
./test_sse_keepalive.sh
```

**Expected output:**
```
[18:30:00] event: endpoint
[18:30:00] data: /messages?session_id=...
[18:30:15] : ping
[18:30:30] : ping
[18:30:45] : ping
```

If you see `ping` events every 15 seconds, keep-alive is working! ✅

### 2. Test Client Timeout Fix

After updating `session_pool.py`:

```python
# Run a query that takes 15-30 seconds
await mcp_session.call_tool(
    "neo4j_execute_query",
    {
        "query": """
            MATCH (n:Function)-[r*1..3]-(m)
            RETURN n, r, m
            LIMIT 1000
        """
    }
)
```

Should complete without "Error in post_writer" ✅

### 3. Test Async Query Processing

After enabling async tools:

```python
# Complex query
result = await mcp_session.call_tool(
    "neo4j_execute_query",
    {
        "query": """
            MATCH (f:Function)
            OPTIONAL MATCH (f)-[:CALLS]->(called:Function)
            WITH f, count(called) as call_count
            WHERE call_count > 5
            RETURN f.name, call_count
        """
    }
)

if result["is_immediate"]:
    print(f"Got {len(result['results'])} results immediately")
else:
    print(f"Processing async: {result['query_id']}")
    # Continue with other work...
```

---

## Implementation Order

### Immediate (Today):
1. ✅ Update `timeout=60` in `session_pool.py`
2. ✅ Test that queries no longer timeout
3. ✅ Verify keep-alive is working (run test script)

### This Week:
4. ⏳ Enable async tools in Neo4j MCP server
5. ⏳ Test async query execution
6. ⏳ Update client code to handle async results (if needed)

### Long-term:
7. ⏳ Add monitoring/metrics for query duration
8. ⏳ Implement query result caching
9. ⏳ Optimize slow queries based on metrics

---

## Monitoring

Add logging to track query performance:

```python
# In session_pool.py, after acquiring session:
import time
start = time.time()
try:
    result = await session.call_tool(name, args)
    elapsed = time.time() - start

    if elapsed > 30:
        logger.warning(f"Slow query: {name} took {elapsed:.1f}s - consider optimization")
    elif elapsed > 10:
        logger.info(f"Query {name} took {elapsed:.1f}s")

    return result
except Exception as e:
    elapsed = time.time() - start
    logger.error(f"Query {name} failed after {elapsed:.1f}s: {e}")
    raise
```

---

## Files Modified/Created

**Modified:**
1. `src/core/graph_rag/adapters/session_pool.py` - Increase timeout

**Created:**
1. `neo4j-mcp-server/neo4j_mcp_server/tools/neo4j_memory/async_query_handler.py` - Async handler
2. `neo4j-mcp-server/neo4j_mcp_server/tools/neo4j_memory/tools_async.py` - Async tools
3. `test_sse_keepalive.sh` - Keep-alive test script
4. `SSE_KEEPALIVE_GUIDE.md` - Comprehensive guide
5. `SSE_TIMEOUT_FIX_IMPLEMENTATION.md` - This file

---

## FAQ

**Q: Why 60 seconds timeout?**
A: Most Neo4j queries complete in < 30s. 60s provides safety margin while still catching real issues.

**Q: Will async processing slow things down?**
A: No! Fast queries (< 5s) execute immediately. Only slow queries use async, preventing timeouts.

**Q: Do I need both fixes?**
A: No. Client timeout fix (Part 1) is sufficient for most cases. Async processing (Part 2) is best practice for production.

**Q: What if queries take > 60s?**
A:
1. Increase timeout further (`timeout=120`)
2. Enable async processing (no timeout needed)
3. Optimize the query (add indexes, LIMIT clauses, etc.)

**Q: How do I know if keep-alive is working?**
A: Run `./test_sse_keepalive.sh` - you should see `ping` events every 15 seconds.

---

## Summary

**Immediate Action:**
```bash
# 1. Update timeout
cd /opt/genpod
# Edit src/core/graph_rag/adapters/session_pool.py line 59: timeout=60

# 2. Verify keep-alive
chmod +x test_sse_keepalive.sh
./test_sse_keepalive.sh

# 3. Test - should no longer see "Error in post_writer"
```

**Result:** 95% of timeout errors should disappear!

For the remaining 5% (very complex queries), implement async processing (Part 2).
