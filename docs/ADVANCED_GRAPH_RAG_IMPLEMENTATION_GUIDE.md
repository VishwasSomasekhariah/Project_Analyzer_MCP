# Advanced Graph RAG Implementation Guide

## CRITICAL CONTEXT: WHY THIS DOCUMENT EXISTS
This document serves as a persistent implementation guide for transforming the current basic RAG system into a sophisticated Graph RAG that properly utilizes rich Neo4j graph data. 

**PROBLEM IDENTIFIED**: Current `query_cpg_only` tool generates shallow queries and verbose synthesis instead of direct answers. User query "How many comment lines in WorkerA.cs?" returns architectural analysis instead of parsing the available `body` property to count comments.

**SOLUTION**: Entity-driven subgraph retrieval with intelligent reranking and targeted synthesis.

---

## CURRENT SYSTEM STATE

### Files Modified/Analyzed:
- `/opt/genpod/src/project_analyzer_tool/tools.py` - Contains `query_cpg_only` (lines 535-670)
- `/opt/genpod/src/core/llm_service.py` - Contains query generation and synthesis
- `/opt/genpod/src/schemas/project_knowledgebase_graph_schema.yaml` - Rich graph schema
- `/opt/genpod/neo4j_config.json` - Neo4j connection config

### Current Limitations:
1. **Shallow Queries**: Only retrieve basic properties (name, type_kind) not rich content (body, symbols_location)
2. **No Entity Extraction**: Doesn't identify key entities from user queries  
3. **Generic Synthesis**: Same verbose template regardless of query intent
4. **Missing Subgraph Strategy**: Single-hop queries instead of multi-hop entity-driven retrieval

### Available Rich Data (Currently Unused):
```cypher
# Example: WorkerA.cs Type node has full code body
(:Type {
  name: "WorkerA", 
  body: "{ private readonly INotifier _notifier; public WorkerA(INotifier notifier) { _notifier = notifier; } public void Process() { ... } }",
  symbols_location: "{\"symbols\": [...]}",
  start_point: "[3, 4]",
  end_point: "[18, 5]"
})
```

---

## IMPLEMENTATION PHASES

### PHASE 1: Core Infrastructure (PRIORITY: HIGH)

#### 1.1 Entity Extraction Service
**File to Create**: `/opt/genpod/src/core/entity_extraction_service.py`

```python
class EntityExtractionService:
    """Extract entities from user queries using schema-aware analysis"""
    
    def __init__(self, llm_service, schema_path):
        self.llm_service = llm_service
        self.schema = self._load_schema(schema_path)
    
    async def extract_entities(self, user_query: str) -> dict:
        """
        Extract key entities and classify intent
        
        Input: "How many comment lines are in WorkerA.cs?"
        Output: {
            "files": ["WorkerA.cs"],
            "types": ["WorkerA"], 
            "functions": [],
            "concepts": ["comment lines"],
            "intent": "count_analysis",
            "target_properties": ["body", "symbols_location"]
        }
        """
```

**LLM Prompt Template**:
```
Extract entities from this code analysis query: "{user_query}"

Available schema: {schema}

Return JSON with:
- files: List of file names mentioned
- types: List of class/type names  
- functions: List of method names
- concepts: List of analysis concepts (comments, loops, calls, etc.)
- intent: One of [count_analysis, structural_analysis, relationship_analysis, find_pattern]
- target_properties: Which node properties needed [body, symbols_location, parameters, etc.]
```

#### 1.2 Subgraph Planning Engine  
**File to Create**: `/opt/genpod/src/core/subgraph_planner.py`

```python
class SubgraphPlanner:
    """Plan multi-seed point retrieval strategies"""
    
    async def plan_retrieval(self, entities: dict, user_query: str) -> dict:
        """
        Create retrieval plan with multiple seed points
        
        Returns: {
            "seed_queries": [
                {
                    "type": "file_seed",
                    "cypher": "MATCH (f:File) WHERE f.name = 'WorkerA.cs'",
                    "purpose": "Get target file node"
                },
                {
                    "type": "type_seed", 
                    "cypher": "MATCH (t:Type) WHERE t.name = 'WorkerA'",
                    "purpose": "Get target type with code body"
                }
            ],
            "expansion_queries": [
                {
                    "hops": 1,
                    "cypher": "MATCH (f:File)-[:CONTAINS]->(t:Type) WHERE f.name = 'WorkerA.cs' RETURN t.body, t.symbols_location, t.start_point, t.end_point",
                    "purpose": "Get rich content for analysis"
                }
            ],
            "strategy": "content_focused",
            "expected_analysis": "comment_counting"
        }
        """
```

#### 1.3 Enhanced Query Executor
**File to Create**: `/opt/genpod/src/core/graph_query_executor.py`

```python
class GraphQueryExecutor:
    """Execute planned subgraph queries with rich property retrieval"""
    
    async def execute_subgraph_retrieval(self, plan: dict, config_path: str) -> dict:
        """
        Execute all planned queries and collect rich graph data
        
        Returns: {
            "seed_results": [...],
            "expansion_results": [...], 
            "total_nodes": int,
            "rich_content_nodes": int,
            "execution_metadata": {...}
        }
        """
```

### PHASE 2: Intelligent Content Processing (PRIORITY: HIGH)

#### 2.1 Content Analyzer
**File to Create**: `/opt/genpod/src/core/code_content_analyzer.py`

```python
class CodeContentAnalyzer:
    """Parse and analyze retrieved code content"""
    
    def analyze_for_intent(self, content: str, intent: str, concept: str) -> dict:
        """
        Analyze code content based on query intent
        
        For intent="count_analysis" + concept="comment lines":
        - Parse code body for // and /* */ comments
        - Count actual comment lines
        - Return precise count
        
        For intent="structural_analysis":
        - Parse symbols_location for method definitions
        - Extract class structure
        - Return organized data
        """
```

#### 2.2 Content Reranker  
**File to Create**: `/opt/genpod/src/core/content_reranker.py`

```python
import math
from typing import Dict, List, Any, Set

class ContentReranker:
    """Rank retrieved nodes by relevance and content richness using weighted scoring"""
    
    # Scoring weights (must sum to 1.0)
    WEIGHTS = {
        "entity_match": 0.40,        # 40% - Most important for relevance
        "content_richness": 0.30,    # 30% - Critical for analysis quality
        "proximity": 0.20,           # 20% - Graph structure importance
        "intent_alignment": 0.10     # 10% - Query-specific boost
    }
    
    # Content richness scoring thresholds
    CONTENT_THRESHOLDS = {
        "rich_content_min_chars": 100,      # Minimum chars for "rich" content
        "symbols_location_weight": 0.7,     # Weight for having symbols_location
        "body_content_weight": 1.0          # Weight for having body content
    }
    
    async def rerank_subgraph_results(self, raw_results: list, entities: dict, intent: dict = None) -> dict:
        """
        Rank nodes using 4-factor weighted scoring system
        
        Args:
            raw_results: List of graph nodes from subgraph retrieval
            entities: Extracted entities from user query
            intent: Intent classification result (optional)
            
        Returns:
            {
                "ranked_nodes": [...],           # Top-ranked nodes
                "ranking_metadata": {...},       # Scoring details
                "total_nodes_processed": int,
                "top_k_selected": int
            }
        """
        if not raw_results:
            return {"ranked_nodes": [], "ranking_metadata": {}, "total_nodes_processed": 0, "top_k_selected": 0}
        
        # Extract seed entities for proximity calculation
        seed_entities = self._extract_seed_entities(entities)
        
        # Calculate scores for each node
        scored_nodes = []
        for node in raw_results:
            scores = self._calculate_node_scores(node, entities, seed_entities, intent)
            final_score = self._calculate_weighted_score(scores)
            
            scored_nodes.append({
                "node": node,
                "final_score": final_score,
                "component_scores": scores,
                "rank": 0  # Will be set after sorting
            })
        
        # Sort by final score (descending)
        scored_nodes.sort(key=lambda x: x["final_score"], reverse=True)
        
        # Assign ranks
        for i, scored_node in enumerate(scored_nodes):
            scored_node["rank"] = i + 1
        
        # Select top K nodes (adaptive based on score distribution)
        top_k = self._determine_optimal_k(scored_nodes)
        top_nodes = scored_nodes[:top_k]
        
        return {
            "ranked_nodes": [sn["node"] for sn in top_nodes],
            "ranking_metadata": {
                "total_candidates": len(raw_results),
                "top_k_selected": top_k,
                "score_distribution": self._calculate_score_distribution(scored_nodes),
                "ranking_factors": self.WEIGHTS,
                "top_scores": [{"rank": sn["rank"], "score": sn["final_score"], "components": sn["component_scores"]} for sn in top_nodes[:5]]
            },
            "total_nodes_processed": len(raw_results),
            "top_k_selected": top_k
        }
    
    def _calculate_node_scores(self, node: dict, entities: dict, seed_entities: Set[str], intent: dict = None) -> dict:
        """Calculate individual scoring components for a node"""
        
        return {
            "entity_match": self._score_entity_match(node, entities),
            "content_richness": self._score_content_richness(node),
            "proximity": self._score_relationship_proximity(node, seed_entities),
            "intent_alignment": self._score_intent_alignment(node, intent)
        }
    
    def _score_entity_match(self, node: dict, entities: dict) -> float:
        """
        Entity Match Score: 0.0 to 1.0
        
        Scoring Logic:
        - Exact name match: 1.0
        - Partial name match: 0.7
        - File path match: 0.8
        - Type/category match: 0.5
        - No match: 0.1 (baseline)
        """
        score = 0.1  # Baseline score
        
        node_name = node.get("name", "").lower()
        node_file_path = node.get("file_path", "").lower()
        
        # Check exact matches
        for entity_type, entity_list in entities.items():
            if not isinstance(entity_list, list):
                continue
                
            for entity in entity_list:
                entity_lower = entity.lower()
                
                # Exact name match (highest score)
                if node_name == entity_lower:
                    return 1.0
                
                # File path exact match
                if entity_lower in node_file_path or node_file_path.endswith(entity_lower):
                    score = max(score, 0.8)
                
                # Partial name match
                elif entity_lower in node_name or node_name in entity_lower:
                    score = max(score, 0.7)
                
                # Type/category match
                elif entity_type in ["types", "functions"] and node.get("type_kind") == entity_type[:-1]:
                    score = max(score, 0.5)
        
        return min(score, 1.0)
    
    def _score_content_richness(self, node: dict) -> float:
        """
        Content Richness Score: 0.0 to 1.0
        
        Scoring Logic:
        - Has body content (>100 chars): +0.6
        - Has symbols_location: +0.3  
        - Has structural properties: +0.1
        - Normalized by total possible: 1.0
        """
        score = 0.0
        
        # Body content scoring
        body = node.get("body", "")
        if isinstance(body, str) and len(body) > self.CONTENT_THRESHOLDS["rich_content_min_chars"]:
            score += self.CONTENT_THRESHOLDS["body_content_weight"] * 0.6
        
        # Symbols location scoring  
        symbols_location = node.get("symbols_location", "")
        if symbols_location and len(str(symbols_location)) > 10:  # Non-empty symbols data
            score += self.CONTENT_THRESHOLDS["symbols_location_weight"] * 0.3
        
        # Structural properties scoring
        structural_props = ["start_point", "end_point", "parameters", "return_type", "fields", "base_list"]
        has_structural = sum(1 for prop in structural_props if node.get(prop))
        if has_structural > 0:
            score += (has_structural / len(structural_props)) * 0.1
        
        return min(score, 1.0)
    
    def _score_relationship_proximity(self, node: dict, seed_entities: Set[str]) -> float:
        """
        Relationship Proximity Score: 0.0 to 1.0
        
        Scoring Logic:
        - Direct seed entity: 1.0
        - 1-hop from seed: 0.8
        - 2-hop from seed: 0.5
        - 3+ hops: 0.2
        - Unknown/unrelated: 0.1
        """
        node_name = node.get("name", "").lower()
        node_file = node.get("file_path", "").lower()
        
        # Check if this node IS a seed entity
        if node_name in seed_entities or any(seed in node_file for seed in seed_entities):
            return 1.0
        
        # Check relationship indicators (simplified heuristic)
        # In full implementation, this would use actual graph traversal data
        
        # File-based proximity (same file as seed entity)
        for seed in seed_entities:
            if seed in node_file:
                return 0.8  # Likely 1-hop (same file)
        
        # Name-based proximity (similar naming patterns)
        for seed in seed_entities:
            seed_base = seed.split('.')[0].lower()  # Remove .cs extension
            if seed_base in node_name or node_name in seed_base:
                return 0.5  # Likely 2-hop (related naming)
        
        # Default proximity for unrelated nodes
        return 0.1
    
    def _score_intent_alignment(self, node: dict, intent: dict = None) -> float:
        """
        Intent Alignment Score: 0.0 to 1.0
        
        Scoring Logic based on query intent:
        - Quantitative + has parseable content: 1.0
        - Structural + has symbols_location: 1.0  
        - Relational + has relationship data: 1.0
        - Misaligned intent: 0.3
        - No intent specified: 0.5 (neutral)
        """
        if not intent:
            return 0.5  # Neutral score
        
        intent_type = intent.get("type", "").lower()
        analysis_type = intent.get("analysis_type", "").lower()
        
        # Quantitative intent alignment
        if analysis_type == "parse_and_count":
            body = node.get("body", "")
            if isinstance(body, str) and len(body) > 50:  # Has parseable content
                return 1.0
            else:
                return 0.3
        
        # Structural intent alignment  
        elif analysis_type == "extract_elements":
            if node.get("symbols_location") or node.get("fields") or node.get("parameters"):
                return 1.0
            else:
                return 0.3
        
        # Relational intent alignment
        elif analysis_type == "traverse_relationships":
            if node.get("base_list") or node.get("type_kind") in ["class", "interface"]:
                return 1.0
            else:
                return 0.3
        
        # Other intents get neutral score
        return 0.5
    
    def _calculate_weighted_score(self, scores: dict) -> float:
        """Calculate final weighted score from component scores"""
        weighted_score = sum(scores[factor] * self.WEIGHTS[factor] for factor in self.WEIGHTS.keys())
        return round(weighted_score, 4)
    
    def _extract_seed_entities(self, entities: dict) -> Set[str]:
        """Extract seed entity names for proximity calculation"""
        seed_entities = set()
        
        for entity_type, entity_list in entities.items():
            if isinstance(entity_list, list):
                for entity in entity_list:
                    seed_entities.add(entity.lower())
        
        return seed_entities
    
    def _determine_optimal_k(self, scored_nodes: list) -> int:
        """
        Determine optimal number of top nodes to return based on score distribution
        
        Logic:
        - If top score > 0.8: Return top 3-5 high-quality nodes
        - If top score 0.5-0.8: Return top 5-8 medium-quality nodes  
        - If top score < 0.5: Return top 8-10 nodes (cast wider net)
        """
        if not scored_nodes:
            return 0
        
        top_score = scored_nodes[0]["final_score"]
        total_nodes = len(scored_nodes)
        
        if top_score >= 0.8:
            # High-confidence results: return fewer, higher-quality nodes
            return min(5, total_nodes)
        elif top_score >= 0.5:
            # Medium-confidence results: return moderate number
            return min(8, total_nodes)
        else:
            # Low-confidence results: cast wider net
            return min(10, total_nodes)
    
    def _calculate_score_distribution(self, scored_nodes: list) -> dict:
        """Calculate score distribution statistics for metadata"""
        if not scored_nodes:
            return {}
        
        scores = [sn["final_score"] for sn in scored_nodes]
        
        return {
            "mean": round(sum(scores) / len(scores), 4),
            "max": round(max(scores), 4),
            "min": round(min(scores), 4),
            "std_dev": round(math.sqrt(sum((s - sum(scores)/len(scores))**2 for s in scores) / len(scores)), 4),
            "top_10_percent_threshold": round(scores[max(0, len(scores)//10 - 1)], 4) if len(scores) >= 10 else round(scores[0], 4)
        }
```

### PHASE 3: Generalized Intent-Based Synthesis (PRIORITY: MEDIUM)

#### 3.1 Intent Classification Framework
**File to Create**: `/opt/genpod/src/core/intent_classifier.py`

```python
class IntentClassifier:
    """Generalized intent recognition system"""
    
    INTENT_PATTERNS = {
        "quantitative": {
            "keywords": ["how many", "count", "total", "number of", "how much"],
            "response_format": "precise_count",
            "analysis_type": "parse_and_count",
            "instructions": "Parse the code content and return only the count with brief explanation."
        },
        "structural": {
            "keywords": ["what methods", "which functions", "show me", "list", "what does", "contains"],
            "response_format": "structured_list", 
            "analysis_type": "extract_elements",
            "instructions": "Extract and list the requested elements with file:line references."
        },
        "relational": {
            "keywords": ["calls", "depends on", "implements", "inherits", "uses", "references"],
            "response_format": "connection_map",
            "analysis_type": "traverse_relationships",
            "instructions": "Show the relationship connections with clear source→target mapping."
        },
        "comparative": {
            "keywords": ["difference", "compare", "similar", "unlike", "versus", "between"],
            "response_format": "comparison_table",
            "analysis_type": "multi_entity_analysis",
            "instructions": "Compare the entities and highlight key similarities/differences."
        },
        "locational": {
            "keywords": ["where is", "find", "locate", "in which file", "which class"],
            "response_format": "location_reference",
            "analysis_type": "entity_location",
            "instructions": "Provide precise location information with file paths and line numbers."
        },
        "behavioral": {
            "keywords": ["how does", "what happens", "when", "process", "workflow"],
            "response_format": "process_description",
            "analysis_type": "execution_flow",
            "instructions": "Describe the execution flow or behavior with step-by-step details."
        }
    }
    
    async def classify_intent(self, user_query: str) -> dict:
        """
        Classify user query intent using pattern matching + LLM backup
        
        Returns: {
            "type": "quantitative",
            "confidence": 0.95,
            "analysis_type": "parse_and_count", 
            "response_format": "precise_count",
            "instructions": "Parse the code content and return only the count..."
        }
        """
        # Primary: Pattern matching
        query_lower = user_query.lower()
        best_match = None
        max_score = 0
        
        for intent_type, config in self.INTENT_PATTERNS.items():
            score = sum(1 for keyword in config["keywords"] if keyword in query_lower)
            if score > max_score:
                max_score = score
                best_match = {"type": intent_type, **config, "confidence": score / len(config["keywords"])}
        
        # Fallback: LLM classification for novel patterns
        if not best_match or best_match["confidence"] < 0.3:
            best_match = await self._llm_classify_intent(user_query)
            
        return best_match
    
    async def _llm_classify_intent(self, user_query: str) -> dict:
        """LLM-based intent classification for novel queries"""
        # Implementation details for LLM fallback
        pass
```

#### 3.2 Dynamic Synthesis Engine  
**File to Modify**: `/opt/genpod/src/core/llm_service.py`

Add generalized synthesis method:

```python
async def synthesize_by_intent(self, user_query: str, context: dict, entities: dict) -> dict:
    """
    Generalized synthesis based on detected intent patterns
    """
    # Classify intent
    intent_classifier = IntentClassifier()
    intent = await intent_classifier.classify_intent(user_query)
    
    # Dynamic prompt construction
    base_prompt = f"""
QUERY ANALYSIS:
- Intent Type: {intent['type']}
- Analysis Required: {intent['analysis_type']}
- Expected Format: {intent['response_format']}
- Confidence: {intent['confidence']:.2f}

USER QUESTION: {user_query}

RETRIEVED CONTEXT: {self._format_context_for_intent(context, intent)}

EXTRACTED ENTITIES: {entities}

INSTRUCTIONS: {intent['instructions']}

RESPONSE GUIDELINES:
1. Be direct and precise - avoid generic architectural discussions
2. Use the specific format indicated: {intent['response_format']}
3. Include file:line references when available
4. Focus on answering the exact question asked

Answer:"""
    
    response = await self.generate_response(base_prompt)
    
    return {
        "answer": response.content,
        "intent_detected": intent,
        "context_used": context,
        "metadata": {
            "analysis_type": intent['analysis_type'],
            "response_format": intent['response_format'],
            "confidence": intent['confidence']
        }
    }

def _format_context_for_intent(self, context: dict, intent: dict) -> str:
    """Format retrieved context based on intent type"""
    if intent['analysis_type'] == 'parse_and_count':
        # Prioritize code bodies for counting
        return self._extract_code_bodies(context)
    elif intent['analysis_type'] == 'extract_elements':
        # Prioritize symbols_location data
        return self._extract_structural_data(context)
    elif intent['analysis_type'] == 'traverse_relationships':
        # Prioritize relationship data
        return self._extract_relationship_data(context)
    else:
        return str(context)
```

#### 3.3 Evolution Path Implementation
**Evolution Strategy**: Template-based generalization with fallback

```python
# Phase 3A: Pattern-based classification (immediate)
# Phase 3B: LLM-enhanced classification (if patterns fail)  
# Phase 3C: Fully generalized LLM-driven intent recognition (future)

async def synthesize_targeted_response(self, context: dict, user_query: str, entities: dict) -> dict:
    """
    Main synthesis method with evolution path
    """
    try:
        # Try generalized approach first
        return await self.synthesize_by_intent(user_query, context, entities)
    except Exception as e:
        # Fallback to basic template matching for reliability
        return await self._fallback_template_synthesis(context, user_query, entities)
```

### PHASE 4: Integration (PRIORITY: HIGH)

#### 4.1 Enhanced query_cpg_only Tool
**File to Modify**: `/opt/genpod/src/project_analyzer_tool/tools.py`

Replace existing `query_cpg_only` function (lines 535-670) with:

```python
@mcp.tool()
async def query_cpg_only(
    cypher_query: str = None,
    user_query: str = None,  # NEW: Semantic query support
    config_path: str = "/opt/genpod/neo4j_config.json",
    max_results: int = 100,
    enable_advanced_rag: bool = True  # NEW: Advanced RAG flag
) -> dict:
    """
    Enhanced CPG querying with entity-driven subgraph retrieval
    """
    if enable_advanced_rag and user_query:
        # NEW WORKFLOW:
        entity_service = EntityExtractionService(llm_service, schema_path)
        entities = await entity_service.extract_entities(user_query)
        
        planner = SubgraphPlanner(schema_path)
        plan = await planner.plan_retrieval(entities, user_query)
        
        executor = GraphQueryExecutor()
        raw_results = await executor.execute_subgraph_retrieval(plan, config_path)
        
        reranker = ContentReranker()
        ranked_context = await reranker.rerank_subgraph_results(raw_results, entities)
        
        # Use targeted synthesis instead of generic comprehensive response
        final_answer = await llm_service.synthesize_targeted_response(
            ranked_context, user_query, entities
        )
        
        return final_answer
    
    # FALLBACK: Use existing direct cypher query approach
    else:
        # ... existing implementation
```

#### 4.2 New Semantic Analysis Tool
**File to Modify**: `/opt/genpod/src/project_analyzer_tool/tools.py`

Add new tool:

```python
@mcp.tool()
async def semantic_code_analysis(
    user_query: str,
    config_path: str = "/opt/genpod/neo4j_config.json"
) -> dict:
    """
    Advanced semantic code analysis using entity-driven Graph RAG
    
    Examples:
    - "How many comment lines are in WorkerA.cs?"
    - "What methods does Manager class call?"
    - "Show all classes implementing IWorker"
    - "Find foreach loops in the codebase"
    """
    return await query_cpg_only(
        user_query=user_query,
        config_path=config_path,
        enable_advanced_rag=True
    )
```

---

## IMPLEMENTATION CHECKLIST

### Phase 1 - Core Infrastructure
- [x] Create `/opt/genpod/src/core/entity_extraction_service.py`
- [x] Create `/opt/genpod/src/core/subgraph_planner.py` 
- [x] Create `/opt/genpod/src/core/graph_query_executor.py`
- [ ] Test entity extraction with sample queries
- [ ] Test subgraph planning logic
- [ ] Test query execution with rich property retrieval

### Phase 2 - Content Processing  
- [x] Create `/opt/genpod/src/core/code_content_analyzer.py`
- [x] Create `/opt/genpod/src/core/content_reranker.py`
- [ ] Test content analysis for comment counting
- [ ] Test reranking algorithm
- [ ] Validate rich content retrieval

### Phase 3 - Generalized Intent-Based Synthesis
- [ ] Create `/opt/genpod/src/core/intent_classifier.py`
- [ ] Implement pattern-based intent classification with 6 intent types
- [ ] Add `synthesize_by_intent()` to `/opt/genpod/src/core/llm_service.py`
- [ ] Implement context formatting methods (`_extract_code_bodies`, `_extract_structural_data`, `_extract_relationship_data`)
- [ ] Add evolution path with fallback synthesis method
- [ ] Test intent classification accuracy with sample queries
- [ ] Test dynamic response generation
- [ ] Validate response format consistency

### Phase 4 - Integration
- [ ] Modify `query_cpg_only` in `/opt/genpod/src/project_analyzer_tool/tools.py`
- [ ] Add `semantic_code_analysis` tool
- [ ] Integration testing with real queries
- [ ] Performance optimization

---

## SUCCESS VALIDATION

### Test Cases:
1. **"How many comment lines are in WorkerA.cs?"**
   - Before: Verbose architectural analysis
   - After: "0 comment lines found in WorkerA.cs"

2. **"What methods does WorkerA implement?"**
   - Before: Generic type relationship discussion  
   - After: "WorkerA implements: Process() method from IWorker interface"

3. **"Show me all foreach loops in Manager.cs"**
   - Before: Shallow query missing code content
   - After: Parse body property and identify actual foreach statements

### Performance Metrics:
- Query depth: From 1-hop to multi-hop subgraph retrieval
- Content richness: From basic properties to full code bodies
- Answer precision: From verbose to direct targeted responses
- Entity recognition: From none to schema-aware entity extraction

---

## RECOVERY INSTRUCTIONS

If context is lost during implementation:

1. **Read this document first** to understand the current state
2. **Check current file state** using Read tool on modified files
3. **Review todo list** to see what's been completed
4. **Continue from the appropriate phase** based on file existence
5. **Test incrementally** - don't implement everything at once

The goal is transforming basic RAG to advanced Graph RAG that rivals Mem0/Graphiti for codebase analysis.