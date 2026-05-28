# Hybrid Workflow Claude SDK Fallback Implementation

**Date**: 2026-01-21
**Status**: IMPLEMENTED ✅ (Testing Required)
**Pattern**: Option B - Isolated in hybrid_workflow for independent testing

---

## Overview

Implemented Claude Agent SDK as a fallback mechanism for the Hybrid Workflow when OpenAI/Anthropic API is unavailable or rate-limited. This follows the same pattern used in codebase_rag for simplicity.

---

## Implementation Strategy

### Option B: Isolated Testing (Current)
- `ClaudeSDKFallback` copied to `src/core/hybrid_workflow/claude_sdk_fallback.py`
- `ResilientLLMService` created at `src/core/resilient_llm_service.py`
- Test independently first
- **Later**: Consolidate to Option A (shared `src/core/claude_sdk_fallback.py`)

---

## Files Created/Modified

### New Files (2):

1. **`src/core/hybrid_workflow/claude_sdk_fallback.py`** (~284 lines)
   - Copied from `/opt/codebase_rag/src/codebase_vector_rag/integrations/ai/claude_sdk_fallback.py`
   - Self-contained, no external dependencies
   - Updated docstring to reference hybrid workflow
   - Blocks 18 Claude built-in tools (Bash, Read, Write, etc.)
   - Supports JSON mode via `output_format`

2. **`src/core/resilient_llm_service.py`** (~370 lines)
   - Wraps existing `LLMService` (original untouched)
   - Imports `ClaudeSDKFallback` from `hybrid_workflow/`
   - Circuit breaker pattern (auto-disables primary after quota errors)
   - Converts `ClaudeSDKResponse` to `LLMResponse`

### Modified Files (1):

3. **`src/core/hybrid_workflow/tool.py`** (lines 13-14, 33-43)
   - Added import: `from ..resilient_llm_service import ResilientLLMService`
   - Updated `initialize_services()` to use `ResilientLLMService` by default
   - Easy rollback: comment/uncomment 1 line

---

## Configuration

### Default Configuration (Enabled by Default)
```python
config = {
    "use_claude_sdk_fallback": True,  # Enable fallback (default)
    "fallback_model": "claude-sonnet-4-5-20250929",  # Claude model
    "fallback_system_prompt": None,  # Optional system prompt
    "fallback_max_turns": 10,  # Max agentic turns
    "fallback_timeout": 300,  # Timeout in seconds
    "fallback_max_buffer_size": 10 * 1024 * 1024,  # 10MB
    "mcp_config_path": None  # Auto-detects from common locations
}
```

### Disable Fallback (Optional)
```python
config = {"use_claude_sdk_fallback": False}
llm_service = ResilientLLMService(config)
```

---

## LLM Calls in Hybrid Workflow

The hybrid workflow makes **3 direct LLM calls** (no tool calling):

### 1. Intent Analysis
- **Purpose**: Classify query intent and determine Vector/CPG weighting
- **Temperature**: 0.1 (low for consistency)
- **Max Tokens**: 16,000
- **Output**: JSON with intent, confidence, vector_weight, cpg_weight, reasoning

### 2. Synthesis
- **Purpose**: Combine Vector + CPG results with cross-validation
- **Temperature**: 0.7 (higher for creativity)
- **Max Tokens**: 16,000
- **Output**: JSON with answer, details, confidence, cross_validation, suggestions

### 3. Critic Validation
- **Purpose**: Validate synthesis for hallucination, faithfulness, accuracy
- **Temperature**: 0.1 (low for precision)
- **Max Tokens**: 16,000
- **Output**: JSON with decision, scores, validation_issues, reasoning

**Note**: Vector and CPG retrieval are external tools (already have Claude SDK fallback)

---

## Fallback Flow

```
┌─────────────────────────────────────────────────────────────┐
│ Hybrid Workflow Node (Intent/Synthesis/Critic)             │
│   ↓ calls llm_service.generate_response()                  │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ ResilientLLMService                                         │
│   ├─ Primary disabled? → Go to fallback                    │
│   └─ Try LLMService (OpenAI → Anthropic API)              │
└─────────────────────────────────────────────────────────────┘
                          ↓
            ┌─────────────┴─────────────┐
            │ Success?                   │
            ├─ Yes → Return response    │
            └─ No (429, quota, timeout) │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Catch Error & Trigger Fallback                             │
│   ├─ APIConnectionError, APITimeoutError, RateLimitError   │
│   ├─ 500-504 server errors                                 │
│   └─ 429 or "quota"/"rate"/"exceeded" in error            │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Circuit Breaker: Disable Primary                           │
│   (Auto-disables for quota/rate errors)                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ ClaudeSDKFallback.query_sync()                             │
│   ├─ Convert to Claude SDK format                          │
│   ├─ JSON mode via output_format                           │
│   ├─ Block built-in tools                                  │
│   └─ Return ClaudeSDKResponse                              │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Convert to LLMResponse                                      │
│   provider = "claude_sdk"                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Rollback Procedure

If issues arise, rollback is simple:

### Quick Rollback (1 line change):
**File**: `src/core/hybrid_workflow/tool.py` (line 40-41)

```python
# Comment this line:
# self._llm_service = ResilientLLMService(llm_config)

# Uncomment this line:
self._llm_service = LLMService(llm_config)  # OLD: No fallback
```

**Time to Rollback**: ~30 seconds

### Full Rollback (Optional - remove files):
```bash
rm src/core/resilient_llm_service.py
rm src/core/hybrid_workflow/claude_sdk_fallback.py
git checkout src/core/hybrid_workflow/tool.py
```

---

## Testing Plan

### Test 1: Hybrid RAG with OpenAI Working
```bash
# Should use OpenAI/Anthropic (no fallback triggered)
python test_query_cpg_rag_mcp_integration.py hybrid
```

**Expected**: OpenAI/Anthropic used, no fallback logs

### Test 2: Hybrid RAG with OpenAI Down (Simulate)
```bash
# Temporarily remove OpenAI API key or wait for 429 error
python test_query_cpg_rag_mcp_integration.py hybrid
```

**Expected**:
- ⚠️ Primary LLM failed logs
- 🔄 CLAUDE SDK FALLBACK ACTIVATED logs
- ✅ Response generated via Claude SDK
- 💰 Cost tracking from Claude SDK

### Test 3: Verify JSON Mode
- Intent analysis, Synthesis, Critic should all produce valid JSON
- Check logs for `📋 JSON mode: True`
- Verify responses are properly parsed

### Test 4: Verify Tool Blocking
- Check logs for `🔧 TOOL CALL ATTEMPT: Bash` (blocked)
- Should see transparency logs with box formatting
- Verify 18 built-in tools are blocked

---

## Differences from Graph RAG

| Feature | Graph RAG | Hybrid Workflow |
|---------|-----------|-----------------|
| **Tool Calling** | Yes (Cypher, Schema, Entity Resolution) | No |
| **Complexity** | ~500+ lines (ResilientLLMClient) | ~370 lines (ResilientLLMService) |
| **Per-Agent Sessions** | Yes (parallel-safe) | No (single session) |
| **MCP Tool Integration** | Yes (Neo4j, Schema tools) | No (only built-in tool blocking) |
| **Pattern** | Wraps OpenAI client | Wraps LLMService |
| **Import Source** | graph_rag/core/llm_client.py | hybrid_workflow/claude_sdk_fallback.py |

---

## Next Steps

1. ✅ Implementation complete
2. ⏳ **Test with OpenAI working** (verify no fallback triggered)
3. ⏳ **Test with OpenAI quota exceeded** (verify fallback works)
4. ⏳ **Verify JSON mode** (all 3 LLM calls)
5. ⏳ **Check tool blocking logs** (transparency)
6. ⏳ **Monitor costs** (Claude SDK usage tracking)
7. 🔄 **Later**: Consolidate to Option A (shared claude_sdk_fallback.py)

---

## Known Considerations

### 1. JSON Mode Handling
- Claude SDK sometimes returns markdown wrappers even with `json_object` mode
- ClaudeSDKFallback already handles this with JSON extraction
- Should work transparently

### 2. Tool Blocking
- 18 Claude built-in tools blocked by default
- Code context is in the prompt, so Claude shouldn't need file access
- Transparency logs show all blocked tool attempts

### 3. Circuit Breaker
- Auto-disables primary after quota/rate errors
- All subsequent calls go directly to fallback
- Can be re-enabled with `enable_primary()`

### 4. No Vector/CPG Fallback Needed
- Vector retrieval already has Claude SDK fallback (from codebase_rag)
- CPG retrieval already has Claude SDK fallback (from graph_rag)
- Only need fallback for intent/synthesis/critic LLM calls

---

## Future Improvements (Option A)

Once tested and validated, consolidate to Option A:

1. Move `claude_sdk_fallback.py` to `src/core/claude_sdk_fallback.py`
2. Update imports in:
   - `src/core/resilient_llm_service.py`
   - `src/core/graph_rag/core/llm_client.py` (if applicable)
3. Remove `src/core/hybrid_workflow/claude_sdk_fallback.py`
4. Single source of truth for all workflows

---

## References

- codebase_rag implementation: `/opt/codebase_rag/CLAUDE_SDK_FALLBACK_CHANGELOG.md`
- graph_rag implementation: `/opt/genpod/src/core/graph_rag/core/llm_client.py`
- Hybrid workflow: `/opt/genpod/src/core/hybrid_workflow/`
- Test script: `/opt/genpod/test_query_cpg_rag_mcp_integration.py`

---

*End of Implementation Doc*
