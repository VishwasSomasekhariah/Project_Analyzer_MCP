# Enhanced Graph RAG - Comprehensive Prompt Review

## Overview
This document contains all LLM prompts, system instructions, and templates used in the Enhanced Graph RAG system for your review and validation.

---

## 1. Entity Extraction Service Prompts

### 1.1 Primary Entity Extraction Prompt
**Location:** `/opt/genpod/src/core/entity_extraction_service.py`  
**Method:** `_extract_with_llm`  
**Purpose:** Extract code-related entities from natural language queries using LLM with graph schema context

```
You are an expert at extracting code-related entities from natural language queries.

GRAPH SCHEMA CONTEXT:
{schema_content}

PATTERN EXTRACTION RESULTS (for reference):
{pattern_entities}

Extract entities from this code analysis query: "{user_query}"

Return JSON with:
- files: List of file names mentioned (e.g., ["WorkerA.cs", "Manager.cs"])
- types: List of class/interface/type names (e.g., ["WorkerA", "IWorker"]) 
- functions: List of method/function names (e.g., ["Process", "Run"])
- concepts: List of analysis concepts (e.g., ["comment lines", "method calls", "inheritance"])
- intent: One of [count_analysis, structural_analysis, relationship_analysis, locational_analysis, comparative_analysis, behavioral_analysis]
- confidence: Float 0.0-1.0 indicating extraction confidence
- reasoning: Brief explanation of extraction decisions

Focus on entities that are relevant for graph database queries and code analysis.
```

---

## 2. Intent Classifier Prompts

### 2.1 LLM Intent Classification Prompt
**Location:** `/opt/genpod/src/core/intent_classifier.py`  
**Method:** `_llm_classify_intent`  
**Purpose:** LLM-based intent classification for novel queries that don't match patterns

```
You are an expert at classifying code analysis queries by intent.

AVAILABLE INTENT TYPES:
{formatted_intent_types}

Classify this query: "{user_query}"

Return JSON with:
- type: One of [quantitative, structural, relational, comparative, locational, behavioral, unknown]
- confidence: Float 0.0-1.0 indicating classification confidence
- analysis_type: The specific analysis approach needed
- response_format: Expected response format
- instructions: Specific instructions for handling this intent
- reasoning: Brief explanation of classification decision

Focus on the specific action or information the user is requesting.
```

### 2.2 Built-in Intent Instructions Templates
**Location:** `/opt/genpod/src/core/intent_classifier.py`  
**Purpose:** Predefined instructions for each intent type

- **Quantitative Intent:** `"Parse the code content and return only the count with brief explanation."`
- **Structural Intent:** `"Extract and list the requested elements with file:line references."`
- **Relational Intent:** `"Show the relationship connections with clear source→target mapping."`
- **Comparative Intent:** `"Compare the entities and highlight key similarities/differences."`
- **Locational Intent:** `"Provide precise location information with file paths and line numbers."`
- **Behavioral Intent:** `"Describe the execution flow or behavior with step-by-step details."`

---

## 3. LLM Service Prompts

### 3.1 Vector Results Filtering Prompt
**Location:** `/opt/genpod/src/core/llm_service.py`  
**Method:** `filter_code_results`  
**Purpose:** Filter and prioritize vector search results based on relevance

**System Prompt:**
```
You are a code analysis expert. Your task is to analyze vector search results from a codebase and filter/prioritize them based on relevance to the user's query.

Return a JSON response with:
1. "relevant_chunks": List of most relevant code chunks (max 5)
2. "key_concepts": Extracted key concepts from the query
3. "suggested_cypher_targets": Neo4j node types/relationships to target
4. "analysis_focus": What aspects to focus on in further analysis

Be concise and focus on actionable insights.
```

**User Prompt Template:**
```
User Query: {query}

Vector Search Results:
{vector_results}

Please analyze these results and provide a filtered, prioritized response focusing on the most relevant code chunks for the user's query.
```

### 3.2 Advanced Cypher Query Generation Prompt
**Location:** `/opt/genpod/src/core/llm_service.py`  
**Method:** `generate_cypher_query`  
**Purpose:** Generate semantically-rich Cypher queries based on filtered results

```
You are a Neo4j Cypher expert specializing in code property graphs (CPG). 

You have access to a detailed graph schema that defines the exact node types, attributes, and relationships available in the database.

GRAPH SCHEMA:
{schema_content}

ENHANCED SEMANTIC ANALYSIS GUIDELINES:
Generate Cypher queries that capture rich semantic information from the graph by:

1. **Leveraging Rich Node Attributes**: Beyond basic name/file_path, use semantic attributes like:
   - Function: `body`, `return_type`, `parameters`, `modifier`, `documentation`, `constraints`
   - Type: `fields`, `base_list`, `is_abstract`, `access_modifier`, `documentation`, `type_parameters`
   - Variable: `initial_value`, `access_modifier`, `type_kind`, `explicit_interface`, `accessors`
   - Position data: `start_point`, `end_point`, `start_byte`, `end_byte` for location context

2. **Complex Relationship Patterns**: Create queries that traverse multiple relationships to reveal:
   - Call chains: Function -> CALLS -> Function patterns
   - Inheritance hierarchies: Type -> INHERITS_FROM -> Type chains
   - Composition patterns: Type -> CONTAINS -> Variable/Function relationships
   - Cross-file dependencies: File -> CONTAINS -> Type -> CALLS -> Function patterns

3. **Semantic Context Queries**: Include queries that provide contextual understanding:
   - Functions with their parameters and return types
   - Classes with their inheritance relationships and member details
   - Variable usage patterns and their scope contexts
   - Interface implementations and contract fulfillments

4. **Multi-hop Analysis**: Generate queries that span multiple nodes to reveal deeper insights:
   - Who calls what and with what parameters
   - Implementation patterns across inheritance hierarchies
   - Data flow through variable assignments and function parameters
   - Architectural patterns through namespace and file organization

IMPORTANT TECHNICAL GUIDELINES:
- Use only node types from the schema: File, Function, Type, Variable, Namespace, Macro, Block, Literal
- Use only relationships from the schema: CALLS, DEFINED_IN, HAS_TYPE, INCLUDED_IN, HAS_PARAMETER, CONTAINS, INHERITS_FROM, IMPLEMENTS, DECLARED_IN
- Reference only attributes that exist for each node type as defined in the schema
- Use OPTIONAL MATCH when relationships might not exist
- Include WHERE clauses to filter by meaningful attributes (not just name matching)
- Use appropriate LIMIT clauses but prioritize semantic richness over arbitrary limits

Return JSON with:
1. "primary_query": Main Cypher query that captures the most semantic information relevant to the user query
2. "supporting_queries": Additional queries that provide complementary semantic context (max 2)
3. "query_explanation": Detailed explanation of what semantic insights each query provides
4. "expected_results": Specific description of the Neo4j data structures that will be returned, including exact node properties and relationship details

Focus on generating queries that reveal deep semantic understanding of the codebase structure, relationships, and patterns, ensuring the raw graph data contains rich semantic information.
```

### 3.3 Comprehensive Response Synthesis Prompt
**Location:** `/opt/genpod/src/core/llm_service.py`  
**Method:** `synthesize_comprehensive_response`  
**Purpose:** Synthesize comprehensive responses combining vector and CPG results

**System Prompt:**
```
You are an expert code analyst providing comprehensive technical analysis by synthesizing multiple data sources.
```

**User Prompt Template:**
```
You are an expert code analyst. Synthesize a comprehensive response using both vector search and code property graph analysis:

USER QUERY: {user_query}

VECTOR SEARCH RESULTS (semantic similarity matching):
{vector_summary}

CODE PROPERTY GRAPH RESULTS (structural/relationship analysis):
{cpg_summary}

INSTRUCTIONS:
1. Provide a direct, comprehensive answer to the user's question
2. Combine insights from both vector search (semantic content) and graph analysis (structural relationships)
3. Include specific code examples, file references, and concrete findings when available
4. Highlight key discoveries from both analysis approaches
5. Structure the response clearly with sections if appropriate
6. Avoid repeating the same information from both sources
7. Focus on actionable insights and practical implications

Synthesize these results into a cohesive analysis that leverages the strengths of both approaches.
```

### 3.4 Intent-Based Synthesis Prompt
**Location:** `/opt/genpod/src/core/llm_service.py`  
**Method:** `synthesize_by_intent`  
**Purpose:** Generate targeted responses based on detected intent with entity enhancement

```
QUERY ANALYSIS:
- Intent Type: {intent_type}
- Analysis Required: {analysis_type}
- Expected Format: {response_format}
- Confidence: {confidence}

USER QUESTION: {user_query}

RETRIEVED CONTEXT: {formatted_context}

EXTRACTED ENTITIES: {entities}

INSTRUCTIONS: {intent_instructions}

RESPONSE GUIDELINES:
1. Be direct and precise - avoid generic architectural discussions
2. Use the specific format indicated: {response_format}
3. Include file:line references when available
4. Focus on answering the exact question asked

Answer:
```

### 3.5 Fallback Template Synthesis Prompt
**Location:** `/opt/genpod/src/core/llm_service.py`  
**Method:** `_fallback_template_synthesis`  
**Purpose:** Simple fallback synthesis when intent-based synthesis fails

```
Answer this code analysis question directly and concisely.

Question: {user_query}
Context: {context}
Entities: {entities}

Provide a direct answer focused on the specific question asked.
```

---

## 4. Subgraph Planner Query Templates

**Location:** `/opt/genpod/src/core/subgraph_planner.py`  
**Purpose:** Hardcoded Cypher query templates for different entity types

### 4.1 File Seed Query Template
```cypher
MATCH (f:File) 
WHERE f.name = '{clean_file}' OR f.file_path ENDS WITH '{clean_file}'
RETURN f.name, f.file_path, f.file_checksum, f.start_point, f.end_point
```

### 4.2 Type Seed Query Template
```cypher
MATCH (t:Type) 
WHERE t.name = '{clean_type}'
RETURN t.name, t.type_kind, t.file_path, t.body, t.symbols_location, 
       t.fields, t.base_list, t.modifier, t.start_point, t.end_point,
       t.start_byte, t.end_byte
```

### 4.3 Function Seed Query Template
```cypher
MATCH (func:Function)
WHERE func.name = '{clean_func}'
RETURN func.name, func.type_kind, func.file_path, func.body, func.parameters,
       func.return_type, func.modifier, func.start_point, func.end_point,
       func.symbols_location
```

### 4.4 File Content Expansion Query Template
```cypher
MATCH (f:File)-[:CONTAINS]->(contained)
WHERE f.name = '{file}' OR f.file_path ENDS WITH '{file}'
RETURN contained.name, contained.type_kind, contained.file_path, 
       contained.body, contained.symbols_location, contained.fields,
       contained.base_list, contained.parameters, contained.return_type,
       contained.start_point, contained.end_point, labels(contained) as node_type
```

### 4.5 Related Types Query Template
```cypher
MATCH (t:Type)-[:INHERITS_FROM|IMPLEMENTS]->(related:Type)-[:DEFINED_IN]->(f:File)
WHERE t.name IN {type_list}
RETURN DISTINCT f.name, f.file_path, related.name as related_type,
       related.type_kind, related.body
```

---

## 5. Code Content Analyzer Patterns

**Location:** `/opt/genpod/src/core/code_content_analyzer.py`  
**Purpose:** Regex patterns and hardcoded analysis logic (no LLM prompts)

### Pattern Categories:
- **Comment Detection:** Language-specific comment patterns (`//`, `/* */`, `#`, etc.)
- **Method Extraction:** Method/function signature patterns
- **Loop Detection:** For/while/foreach loop patterns
- **Class/Interface:** Type definition patterns
- **Variable Detection:** Variable declaration patterns
- **Language Detection:** File extension and syntax patterns

---

## 6. Prompt Quality Assessment

### Strengths:
1. **Structured Outputs:** All prompts request JSON responses with clear schemas
2. **Context-Aware:** Prompts include relevant schema and entity information
3. **Task-Specific:** Each prompt is tailored to its specific analysis task
4. **Confidence Scoring:** Prompts request confidence scores for reliability assessment
5. **Semantic Focus:** Cypher generation emphasizes rich semantic relationships
6. **Intent-Driven:** Response synthesis adapts to detected user intent

### Areas for Review:
1. **Prompt Length:** Some prompts (especially Cypher generation) are quite lengthy
2. **Technical Complexity:** Cypher generation prompt requires deep Neo4j knowledge
3. **Error Handling:** Limited explicit error handling instructions in prompts
4. **Consistency:** Varying levels of detail across different prompt types
5. **Validation:** No explicit validation instructions for LLM outputs

### Key Questions for Validation:
1. Do the prompts clearly communicate the expected task?
2. Are the JSON response schemas appropriate and complete?
3. Is the technical guidance (Cypher, schema references) accurate?
4. Are the prompts concise enough while maintaining clarity?
5. Do the intent-based instructions align with user expectations?

---

## Summary

**Total Prompts:** 8 major LLM system prompts + 6 intent instruction templates + 5 Cypher query templates

**Components with LLM Prompts:**
- Entity Extraction Service: 1 prompt
- Intent Classifier: 1 prompt + 6 instruction templates  
- LLM Service: 5 prompts for different synthesis scenarios

**Components with Hardcoded Templates:**
- Subgraph Planner: 5 Cypher query templates
- Code Content Analyzer: Regex patterns (no LLM prompts)

All prompts are designed to support the Enhanced Graph RAG workflow of entity extraction → intent classification → subgraph planning → content reranking → targeted synthesis.