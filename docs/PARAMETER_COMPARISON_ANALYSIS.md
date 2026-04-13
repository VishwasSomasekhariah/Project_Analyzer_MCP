# RAG Parameter Comparison Analysis
## properly_fixed_comparative_analysis.py vs Latest Test Scripts

Last Updated: 2026-02-02

---

## 📊 PARAMETER COMPARISON TABLE

| Parameter | Vector RAG (Comparative) | Vector RAG (Test Scripts) | CPG RAG (Comparative) | CPG RAG (Test) | Hybrid RAG (Comparative) | Hybrid RAG (Test) |
|-----------|-------------------------|---------------------------|---------------------|---------------|-------------------------|-------------------|
| **Tool Name** | `query_vector_only` | - | `query_cpg_rag` | `query_cpg_rag` | `query_hybrid_rag` | `query_hybrid_rag` |
| **user_query** | ✅ Yes | - | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| **project_name** | ❌ No | - | ✅ "HelloWorldApp" | ✅ "HelloWorldApp" | ✅ "HelloWorldApp" | ✅ "HelloWorldApp" |
| **collection_name** | ✅ (qdrant_v2) | - | ❌ No | ❌ No | ✅ (qdrant_v2) | ✅ (qdrant_v2) |
| **max_results** | ✅ 5 | - | ✅ 100 | ❌ No | ✅ 5 | ❌ No |
| **config** | ✅ vector_config | - | ❌ No | ❌ No | ❌ No | ❌ No |
| **config_path** | ❌ No | - | ✅ neo4j_config | ❌ No | ✅ neo4j_config | ❌ No |
| **project_path** | ❌ No | - | ✅ /opt/HelloWorldApp | ❌ No | ✅ /opt/HelloWorldApp | ❌ No |
| **vector_db** | ✅ "qdrant" | - | ❌ No | ❌ No | ✅ "qdrant" | ❌ No |
| **output_format** | ✅ "json" | - | ❌ No | ❌ No | ❌ No | ❌ No |
| **enable_reasoning** | ✅ True | - | ❌ No | ❌ No | ✅ True | ❌ No |
| **max_branches** | ✅ 2 | - | ❌ No | ❌ No | ✅ 2 | ❌ No |
| **max_agent_iterations** | ❌ No | - | ✅ 10 | ✅ 100 | ✅ 10 | ✅ 100 |
| **batch_size** | ❌ No | - | ❌ No | ❌ No | ✅ 5 | ❌ No |
| **max_context_limit** | ❌ No | - | ❌ No | ❌ No | ✅ 100000 | ❌ No |
| **mappings_path** | ❌ No | - | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **queries_path** | ❌ No | - | ✅ Yes | ❌ No | ❌ No | ❌ No |
| **parallel_agents** | ❌ No | - | ❌ No | ✅ True | ❌ No | ✅ False |
| **max_parallel_workers** | ❌ No | - | ❌ No | ✅ 5 | ❌ No | ✅ 3 |
| **use_4_agent_team** | ❌ No | - | ❌ No | ✅ True | ❌ No | ✅ True |
| **four_agent_max_iterations** | ❌ No | - | ❌ No | ✅ 3 | ❌ No | ✅ 3 |
| **top_k** | ❌ No | - | ❌ No | ❌ No | ❌ No | ✅ 5 |
| **neo4j_config** | ❌ No | - | ❌ No | ❌ No | ✅ Yes | ❌ No |

---

## 🔍 DETAILED ANALYSIS

### 1. Vector RAG (`query_vector_only`)

#### **Comparative Analysis Script (Lines 414-426)**
```python
result = await session.call_tool(
    "query_vector_only",
    {
        "query": query,
        "collection_name": self.collection_name,  # "HelloWorldApp_qdrant_v2"
        "max_results": 5,
        "output_format": "json",
        "vector_db": self.vector_db,  # "qdrant"
        "config": self.vector_config,  # "/opt/genpod/qdrant_mcp_config.json"
        "enable_reasoning": True,
        "max_branches": 2
    }
)
```

#### **Key Features**
- ✅ Enables **ToT+CoT reasoning** with 2 branches
- ✅ Uses **JSON output format** for clean response parsing
- ✅ Configured for **Qdrant** vector database
- ✅ Limits results to **5 documents**

#### **Missing Parameters (compared to recent improvements)**
- No `project_name` parameter
- No `project_path` parameter

---

### 2. CPG RAG (`query_cpg_rag`)

#### **Comparative Analysis Script (Lines 511-523)**
```python
result = await session.call_tool(
    "query_cpg_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "config_path": self.neo4j_config,  # "/opt/genpod/neo4j_config.json"
        "project_path": self.project_path,  # "/opt/HelloWorldApp"
        "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
        "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
        "max_results": 100,
        "max_agent_iterations": 10
    }
)
```

#### **Test Script (Lines 52-63)**
```python
result = await session.call_tool(
    "query_cpg_rag",
    {
        "user_query": test_query,
        "project_name": "HelloWorldApp",
        "max_agent_iterations": 100,  # ⚠️ 10x higher!
        "parallel_agents": True,  # ⚠️ NEW parameter
        "max_parallel_workers": 5,  # ⚠️ NEW parameter
        "use_4_agent_team": True,  # ⚠️ NEW parameter
        "four_agent_max_iterations": 3  # ⚠️ NEW parameter
    }
)
```

#### **Key Differences**
| Parameter | Comparative Script | Test Script | Recommendation |
|-----------|-------------------|-------------|----------------|
| `max_agent_iterations` | 10 | 100 | ⚠️ **Use 100** for complex queries |
| `config_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `project_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `mappings_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `queries_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `parallel_agents` | ❌ Missing | ✅ True | ✅ **ADD THIS** |
| `max_parallel_workers` | ❌ Missing | ✅ 5 | ✅ **ADD THIS** |
| `use_4_agent_team` | ❌ Missing | ✅ True | ✅ **ADD THIS** |
| `four_agent_max_iterations` | ❌ Missing | ✅ 3 | ✅ **ADD THIS** |

---

### 3. Hybrid RAG (`query_hybrid_rag`)

#### **Comparative Analysis Script (Lines 807-823)**
```python
result = await session.call_tool(
    "query_hybrid_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "collection_name": self.collection_name,  # "HelloWorldApp_qdrant_v2"
        "config_path": self.neo4j_config,  # "/opt/genpod/neo4j_config.json"
        "project_path": self.project_path,  # "/opt/HelloWorldApp"
        "vector_db": self.vector_db,  # "qdrant"
        "enable_reasoning": True,
        "max_branches": 2,
        "max_results": 5,
        "batch_size": 5,
        "max_context_limit": 100000,
        "max_agent_iterations": 10
    }
)
```

#### **Test Script (Lines 80-95)**
```python
result = await session.call_tool(
    "query_hybrid_rag",
    {
        "user_query": test['query'],
        "project_name": "HelloWorldApp",
        "collection_name": "HelloWorldApp_qdrant_v2",
        "top_k": 5,  # ⚠️ Different from max_results
        "max_agent_iterations": 100,  # ⚠️ 10x higher!
        "parallel_agents": False,  # ⚠️ NEW parameter
        "max_parallel_workers": 3,  # ⚠️ NEW parameter
        "use_4_agent_team": True,  # ⚠️ NEW parameter
        "four_agent_max_iterations": 3  # ⚠️ NEW parameter
    }
)
```

#### **Key Differences**
| Parameter | Comparative Script | Test Script | Recommendation |
|-----------|-------------------|-------------|----------------|
| `max_agent_iterations` | 10 | 100 | ⚠️ **Use 100** for complex queries |
| `max_results` | 5 | ❌ Missing | Keep as `max_results` |
| `top_k` | ❌ Missing | 5 | ⚠️ Check if equivalent to `max_results` |
| `config_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `project_path` | ✅ Provided | ❌ Missing | Keep in comparative |
| `vector_db` | ✅ "qdrant" | ❌ Missing | Keep in comparative |
| `enable_reasoning` | ✅ True | ❌ Missing | Keep in comparative |
| `max_branches` | ✅ 2 | ❌ Missing | Keep in comparative |
| `batch_size` | ✅ 5 | ❌ Missing | Keep in comparative |
| `max_context_limit` | ✅ 100000 | ❌ Missing | Keep in comparative |
| `parallel_agents` | ❌ Missing | ✅ False | ✅ **ADD THIS** |
| `max_parallel_workers` | ❌ Missing | ✅ 3 | ✅ **ADD THIS** |
| `use_4_agent_team` | ❌ Missing | ✅ True | ✅ **ADD THIS** |
| `four_agent_max_iterations` | ❌ Missing | ✅ 3 | ✅ **ADD THIS** |
| `neo4j_config` | ❌ Missing | ❌ Missing | ⚠️ Consider adding |

---

## ✅ RECOMMENDED PARAMETER UPDATES

### 1. **CPG RAG Updates**

```python
# Current (Line 511-523)
result = await session.call_tool(
    "query_cpg_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "config_path": self.neo4j_config,
        "project_path": self.project_path,
        "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
        "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
        "max_results": 100,
        "max_agent_iterations": 10  # ⚠️ Too low
    }
)

# RECOMMENDED
result = await session.call_tool(
    "query_cpg_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "config_path": self.neo4j_config,
        "project_path": self.project_path,
        "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
        "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
        "max_results": 100,
        "max_agent_iterations": 100,  # ✅ Increased for complex queries
        "parallel_agents": True,  # ✅ Enable parallel execution
        "max_parallel_workers": 5,  # ✅ Allow 5 parallel sub-queries
        "use_4_agent_team": True,  # ✅ Use 4-agent team workflow
        "four_agent_max_iterations": 3  # ✅ Max iterations per agent
    }
)
```

### 2. **Hybrid RAG Updates**

```python
# Current (Line 807-823)
result = await session.call_tool(
    "query_hybrid_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "collection_name": self.collection_name,
        "config_path": self.neo4j_config,
        "project_path": self.project_path,
        "vector_db": self.vector_db,
        "enable_reasoning": True,
        "max_branches": 2,
        "max_results": 5,
        "batch_size": 5,
        "max_context_limit": 100000,
        "max_agent_iterations": 10  # ⚠️ Too low
    }
)

# RECOMMENDED
result = await session.call_tool(
    "query_hybrid_rag",
    {
        "user_query": query,
        "project_name": "HelloWorldApp",
        "collection_name": self.collection_name,
        "config_path": self.neo4j_config,
        "project_path": self.project_path,
        "vector_db": self.vector_db,
        "enable_reasoning": True,
        "max_branches": 2,
        "max_results": 5,
        "batch_size": 5,
        "max_context_limit": 100000,
        "max_agent_iterations": 100,  # ✅ Increased for complex queries
        "parallel_agents": True,  # ✅ Enable parallel execution (or False for sequential)
        "max_parallel_workers": 3,  # ✅ Allow 3 parallel sub-queries
        "use_4_agent_team": True,  # ✅ Use 4-agent team workflow
        "four_agent_max_iterations": 3  # ✅ Max iterations per agent
    }
)
```

### 3. **Vector RAG** (No changes needed)
```python
# Already optimal (Line 414-426)
result = await session.call_tool(
    "query_vector_only",
    {
        "query": query,
        "collection_name": self.collection_name,
        "max_results": 5,
        "output_format": "json",
        "vector_db": self.vector_db,
        "config": self.vector_config,
        "enable_reasoning": True,
        "max_branches": 2
    }
)
```

---

## 🎯 CRITICAL PARAMETER ADDITIONS

### Required for All CPG/Hybrid Calls:
1. ✅ **`max_agent_iterations: 100`** (increased from 10)
2. ✅ **`parallel_agents: True`** (enable parallel sub-query execution)
3. ✅ **`max_parallel_workers: 3-5`** (control parallelism)
4. ✅ **`use_4_agent_team: True`** (enable sophisticated 4-agent workflow)
5. ✅ **`four_agent_max_iterations: 3`** (limit iterations per agent)

---

## 📝 PARAMETER NOTES

### `max_agent_iterations` (CPG & Hybrid)
- **Comparative Script**: 10 iterations
- **Test Scripts**: 100 iterations
- **Issue**: Complex queries need more decomposition iterations
- **Fix**: Use 100 for comprehensive analysis

### `parallel_agents` (CPG & Hybrid)
- **Missing in Comparative Script**
- **Test Scripts**: True for CPG, False for Hybrid
- **Recommendation**:
  - CPG: `True` for faster execution
  - Hybrid: `False` or `True` depending on complexity

### `use_4_agent_team` (CPG & Hybrid)
- **Missing in Comparative Script**
- **Test Scripts**: Always `True`
- **Purpose**: Enables sophisticated multi-agent workflow
- **Recommendation**: Always set to `True`

### `top_k` vs `max_results`
- **Hybrid test script** uses `top_k: 5`
- **Comparative script** uses `max_results: 5`
- **Action**: Verify if these are equivalent parameters

---

## 🚨 IMMEDIATE ACTION ITEMS

1. ✅ **Update `max_agent_iterations`** from 10 → 100 in both CPG and Hybrid
2. ✅ **Add `parallel_agents`** parameter to both CPG and Hybrid
3. ✅ **Add `max_parallel_workers`** parameter (5 for CPG, 3 for Hybrid)
4. ✅ **Add `use_4_agent_team: True`** to both CPG and Hybrid
5. ✅ **Add `four_agent_max_iterations: 3`** to both CPG and Hybrid
6. ⚠️ **Verify** if `top_k` should replace `max_results` in Hybrid
7. ⚠️ **Consider** adding more parameters from test scripts if needed

---

## 📊 EXPECTED IMPROVEMENTS

After implementing these changes:
- 🚀 **Faster CPG execution** with parallel sub-queries
- 🎯 **Better query decomposition** with 100 iterations
- 🤖 **More sophisticated analysis** with 4-agent team
- ✅ **Higher quality results** from multi-perspective reasoning

---

## 🔗 REFERENCE FILES

- **Comparative Analysis Script**: `/opt/genpod/properly_fixed_comparative_analysis.py`
- **Hybrid Test Script**: `/opt/genpod/test_hybrid_simple.py`
- **CPG Test Script**: `/opt/genpod/test_query_cpg_rag_mcp_integration.py`
- **Latest Hybrid Output**: `/opt/genpod/query_hybrid_rag_mcp_test_20260130_050941.json`
