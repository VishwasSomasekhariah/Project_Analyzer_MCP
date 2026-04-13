# Claude-Context: Zilliz's MCP Plugin for Semantic Code Search

## Overview

**Repository**: https://github.com/zilliztech/claude-context
**Author**: Zilliz (creators of Milvus/Zilliz Cloud)
**License**: MIT
**Purpose**: MCP (Model Context Protocol) plugin that enables AI coding assistants to perform semantic code search using Zilliz Cloud as the vector database backend.

This document provides a comprehensive technical analysis of the claude-context architecture, implementation patterns, and design decisions for building production-grade code search systems.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Code Splitting Strategy](#code-splitting-strategy)
3. [Embedding Providers](#embedding-providers)
4. [Vector Database Integration](#vector-database-integration)
5. [Hybrid Search Implementation](#hybrid-search-implementation)
6. [Incremental Indexing with Merkle DAG](#incremental-indexing-with-merkle-dag)
7. [MCP Tool Handlers](#mcp-tool-handlers)
8. [Chunk Overlap and Retrieval Limitations](#chunk-overlap-and-retrieval-limitations)
9. [Configuration and Environment](#configuration-and-environment)
10. [Comparison with Other Implementations](#comparison-with-other-implementations)
11. [Implementation Patterns for Your Own System](#implementation-patterns-for-your-own-system)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Client (Claude Desktop)                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    packages/mcp (MCP Server)                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ handlers.ts - Tool Handlers                              │    │
│  │   • index_codebase  → Start background indexing          │    │
│  │   • search_code     → Semantic/hybrid search             │    │
│  │   • clear_index     → Remove collection from cloud       │    │
│  │   • get_indexing_status → Progress tracking              │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ snapshot.ts - Codebase State Management                  │    │
│  │   • Track indexed/indexing/failed codebases              │    │
│  │   • Sync local state ↔ Zilliz Cloud collections          │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                  packages/core (Core Library)                    │
│                                                                  │
│  ┌────────────────────┐    ┌─────────────────────────────────┐  │
│  │    context.ts      │    │         splitter/               │  │
│  │  Main Orchestrator │    │  ├── ast-splitter.ts            │  │
│  │  • indexCodebase() │    │  │   (tree-sitter, 9 languages) │  │
│  │  • semanticSearch()│    │  └── langchain-splitter.ts      │  │
│  │  • reindexByChange │    │      (fallback for others)      │  │
│  └────────────────────┘    └─────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────┐    ┌─────────────────────────────────┐  │
│  │    embedding/      │    │         vectordb/               │  │
│  │ ├── openai         │    │  ├── milvus-vectordb.ts (gRPC)  │  │
│  │ ├── voyageai       │    │  └── milvus-restful.ts (REST)   │  │
│  │ ├── gemini         │    │                                 │  │
│  │ └── ollama         │    │  Supports: Dense + BM25 Hybrid  │  │
│  └────────────────────┘    └─────────────────────────────────┘  │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                       sync/                                │  │
│  │  ├── synchronizer.ts  - File change detection             │  │
│  │  └── merkle.ts        - MerkleDAG for efficient diffing   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Zilliz Cloud / Milvus                         │
│                                                                  │
│  • Dense vectors (OpenAI/VoyageAI embeddings)                   │
│  • Sparse vectors (BM25 function - auto-generated)              │
│  • Hybrid search with RRF (Reciprocal Rank Fusion)              │
│  • Managed cloud infrastructure                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Monorepo Structure

```
claude-context/
├── packages/
│   ├── core/                 # Core library (npm: @zilliz/claude-context-core)
│   │   └── src/
│   │       ├── context.ts    # Main orchestration class
│   │       ├── splitter/     # Code chunking strategies
│   │       ├── embedding/    # Multi-provider embeddings
│   │       ├── vectordb/     # Milvus/Zilliz integration
│   │       ├── sync/         # Incremental indexing
│   │       └── types.ts      # Shared types
│   │
│   ├── mcp/                  # MCP Server (npm: @zilliz/claude-context-mcp)
│   │   └── src/
│   │       ├── handlers.ts   # Tool implementations
│   │       ├── snapshot.ts   # State persistence
│   │       └── index.ts      # Server entry point
│   │
│   └── vscode/               # VS Code extension
│
└── examples/                 # Usage examples
```

---

## Code Splitting Strategy

### AST-Based Splitting with Tree-Sitter

Claude-context uses **tree-sitter** for AST-aware code splitting, ensuring chunks align with logical code boundaries (functions, classes, methods) rather than arbitrary line counts.

#### Supported Languages and Splittable Node Types

| Language | Node Types Extracted |
|----------|---------------------|
| JavaScript | `function_declaration`, `arrow_function`, `class_declaration`, `method_definition`, `export_statement` |
| TypeScript | Above + `interface_declaration`, `type_alias_declaration` |
| Python | `function_definition`, `class_definition`, `decorated_definition`, `async_function_definition` |
| Java | `method_declaration`, `class_declaration`, `interface_declaration`, `constructor_declaration` |
| Go | `function_declaration`, `method_declaration`, `type_declaration`, `var_declaration`, `const_declaration` |
| Rust | `function_item`, `impl_item`, `struct_item`, `enum_item`, `trait_item`, `mod_item` |
| C# | `method_declaration`, `class_declaration`, `interface_declaration`, `struct_declaration`, `enum_declaration` |
| C/C++ | `function_definition`, `class_specifier`, `namespace_definition`, `declaration` |
| Scala | `method_declaration`, `class_declaration`, `interface_declaration`, `constructor_declaration` |

#### Splitting Flow

```
Source File
     │
     ▼
┌─────────────────────────────────────────┐
│ 1. AST EXTRACTION (tree-sitter)         │
│    Parse file → Identify splittable     │
│    node types → Extract as chunks       │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│ 2. SIZE CHECK                           │
│    chunk.length <= chunkSize (2500)?    │
│    ├── YES → Keep as-is                 │
│    └── NO  → Split further (line-based) │
└─────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────┐
│ 3. ADD OVERLAP                          │
│    Prepend last 300 chars from          │
│    previous chunk to current chunk      │
└─────────────────────────────────────────┘
     │
     ▼
Final Chunks with Metadata
```

#### Implementation Details

```typescript
// Default configuration
const chunkSize = 2500;    // Max characters per chunk
const chunkOverlap = 300;  // Characters to overlap between chunks

// AST extraction traversal
const traverse = (currentNode: Parser.SyntaxNode) => {
    if (splittableTypes.includes(currentNode.type)) {
        const nodeText = code.slice(currentNode.startIndex, currentNode.endIndex);

        if (nodeText.trim().length > 0) {
            chunks.push({
                content: nodeText,
                metadata: {
                    startLine: currentNode.startPosition.row + 1,
                    endLine: currentNode.endPosition.row + 1,
                    language,
                    filePath,
                }
            });
        }
    }

    // Continue traversing children
    for (const child of currentNode.children) {
        traverse(child);
    }
};
```

#### Large Chunk Splitting

When an AST node exceeds `chunkSize`, it's split line-by-line:

```typescript
private splitLargeChunk(chunk: CodeChunk): CodeChunk[] {
    const lines = chunk.content.split('\n');
    const subChunks: CodeChunk[] = [];
    let currentChunk = '';
    let currentStartLine = chunk.metadata.startLine;

    for (let i = 0; i < lines.length; i++) {
        const lineWithNewline = lines[i] + '\n';

        if (currentChunk.length + lineWithNewline.length > this.chunkSize
            && currentChunk.length > 0) {
            // Emit current chunk, start new one
            subChunks.push({
                content: currentChunk.trim(),
                metadata: { startLine: currentStartLine, ... }
            });
            currentChunk = lineWithNewline;
            currentStartLine = chunk.metadata.startLine + i;
        } else {
            currentChunk += lineWithNewline;
        }
    }

    return subChunks;
}
```

#### Overlap Addition

```typescript
private addOverlap(chunks: CodeChunk[]): CodeChunk[] {
    const overlappedChunks: CodeChunk[] = [];

    for (let i = 0; i < chunks.length; i++) {
        let content = chunks[i].content;
        const metadata = { ...chunks[i].metadata };

        // Add overlap from previous chunk (except for first chunk)
        if (i > 0 && this.chunkOverlap > 0) {
            const prevChunk = chunks[i - 1];
            const overlapText = prevChunk.content.slice(-this.chunkOverlap);
            content = overlapText + '\n' + content;
            metadata.startLine = Math.max(1, metadata.startLine - this.getLineCount(overlapText));
        }

        overlappedChunks.push({ content, metadata });
    }

    return overlappedChunks;
}
```

#### Fallback Strategy

For unsupported languages, falls back to LangChain's recursive text splitter:

```typescript
async split(code: string, language: string, filePath?: string): Promise<CodeChunk[]> {
    const langConfig = this.getLanguageConfig(language);

    if (!langConfig) {
        console.log(`Language ${language} not supported by AST, using LangChain splitter`);
        return await this.langchainFallback.split(code, language, filePath);
    }

    // ... AST splitting logic
}
```

---

## Embedding Providers

### Supported Providers

| Provider | Default Model | Dimension | Max Tokens | Use Case |
|----------|--------------|-----------|------------|----------|
| **OpenAI** | `text-embedding-3-small` | 1536 | 8192 | General purpose, best quality/cost |
| **OpenAI** | `text-embedding-3-large` | 3072 | 8192 | Highest quality |
| **VoyageAI** | `voyage-code-3` | varies | varies | Code-optimized embeddings |
| **Gemini** | `gemini-embedding` | varies | varies | Google ecosystem |
| **Ollama** | Local models | varies | varies | Privacy, offline use |

### Base Embedding Interface

```typescript
export abstract class Embedding {
    protected abstract maxTokens: number;

    // Preprocess text (truncation, empty string handling)
    protected preprocessText(text: string): string {
        if (text === '') return ' ';

        const maxChars = this.maxTokens * 4;  // ~4 chars per token
        if (text.length > maxChars) {
            return text.substring(0, maxChars);
        }
        return text;
    }

    // Abstract methods
    abstract embed(text: string): Promise<EmbeddingVector>;
    abstract embedBatch(texts: string[]): Promise<EmbeddingVector[]>;
    abstract getDimension(): number;
    abstract getProvider(): string;
    abstract detectDimension(testText?: string): Promise<number>;
}
```

### OpenAI Implementation

```typescript
export class OpenAIEmbedding extends Embedding {
    private client: OpenAI;
    private dimension: number = 1536;
    protected maxTokens: number = 8192;

    async embed(text: string): Promise<EmbeddingVector> {
        const processedText = this.preprocessText(text);

        const response = await this.client.embeddings.create({
            model: this.config.model || 'text-embedding-3-small',
            input: processedText,
            encoding_format: 'float',
        });

        return {
            vector: response.data[0].embedding,
            dimension: response.data[0].embedding.length
        };
    }

    async embedBatch(texts: string[]): Promise<EmbeddingVector[]> {
        const processedTexts = this.preprocessTexts(texts);

        const response = await this.client.embeddings.create({
            model: this.config.model,
            input: processedTexts,
            encoding_format: 'float',
        });

        return response.data.map(item => ({
            vector: item.embedding,
            dimension: item.embedding.length
        }));
    }

    // Auto-detect dimension for custom models
    async detectDimension(testText: string = "test"): Promise<number> {
        const knownModels = {
            'text-embedding-3-small': 1536,
            'text-embedding-3-large': 3072,
            'text-embedding-ada-002': 1536
        };

        if (knownModels[this.config.model]) {
            return knownModels[this.config.model];
        }

        // For unknown models, make API call
        const response = await this.client.embeddings.create({
            model: this.config.model,
            input: testText,
        });
        return response.data[0].embedding.length;
    }
}
```

---

## Vector Database Integration

### Milvus/Zilliz Schema

#### Regular Collection (Semantic Search Only)

```typescript
const schema = [
    { name: 'id', data_type: DataType.VarChar, is_primary_key: true, max_length: 64 },
    { name: 'content', data_type: DataType.VarChar, max_length: 65535 },
    { name: 'vector', data_type: DataType.FloatVector, dim: dimension },
    { name: 'relativePath', data_type: DataType.VarChar, max_length: 512 },
    { name: 'startLine', data_type: DataType.Int32 },
    { name: 'endLine', data_type: DataType.Int32 },
    { name: 'fileExtension', data_type: DataType.VarChar, max_length: 32 },
    { name: 'metadata', data_type: DataType.VarChar, max_length: 65535 }
];

const index = {
    field_name: 'vector',
    index_type: 'AUTOINDEX',
    metric_type: 'COSINE'
};
```

#### Hybrid Collection (Semantic + BM25)

```typescript
const hybridSchema = [
    // ... same scalar fields as above ...

    // Dense vector field
    { name: 'vector', data_type: DataType.FloatVector, dim: dimension },

    // Sparse vector field with BM25 function
    {
        name: 'sparse_vector',
        data_type: DataType.SparseFloatVector,
        // BM25 function auto-generates sparse vectors from content
    }
];

// Two indexes for hybrid search
const indexes = [
    { field_name: 'vector', index_type: 'AUTOINDEX', metric_type: 'COSINE' },
    { field_name: 'sparse_vector', index_type: 'SPARSE_INVERTED_INDEX', metric_type: 'BM25' }
];
```

### Collection Naming Convention

```typescript
public getCollectionName(codebasePath: string): string {
    const isHybrid = this.getIsHybrid();
    const normalizedPath = path.resolve(codebasePath);
    const hash = crypto.createHash('md5').update(normalizedPath).digest('hex');

    const prefix = isHybrid ? 'hybrid_code_chunks' : 'code_chunks';
    return `${prefix}_${hash.substring(0, 8)}`;
}

// Examples:
// /Users/dev/myproject → hybrid_code_chunks_a1b2c3d4
// /home/user/app       → hybrid_code_chunks_e5f6g7h8
```

### Document Insertion

```typescript
// Generate unique chunk ID
private generateId(relativePath: string, startLine: number, endLine: number, content: string): string {
    const combinedString = `${relativePath}:${startLine}:${endLine}:${content}`;
    const hash = crypto.createHash('sha256').update(combinedString, 'utf-8').digest('hex');
    return `chunk_${hash.substring(0, 16)}`;
}

// Insert with hybrid support
private async processChunkBatch(chunks: CodeChunk[], codebasePath: string): Promise<void> {
    const embeddings = await this.embedding.embedBatch(chunks.map(c => c.content));

    const documents: VectorDocument[] = chunks.map((chunk, index) => ({
        id: this.generateId(relativePath, chunk.metadata.startLine, ...),
        content: chunk.content,           // Full text for BM25
        vector: embeddings[index].vector, // Dense embedding
        relativePath: path.relative(codebasePath, chunk.metadata.filePath),
        startLine: chunk.metadata.startLine,
        endLine: chunk.metadata.endLine,
        fileExtension: path.extname(chunk.metadata.filePath),
        metadata: JSON.stringify({
            codebasePath,
            language: chunk.metadata.language,
            chunkIndex: index
        })
    }));

    if (this.getIsHybrid()) {
        await this.vectorDatabase.insertHybrid(collectionName, documents);
    } else {
        await this.vectorDatabase.insert(collectionName, documents);
    }
}
```

---

## Hybrid Search Implementation

### What is Hybrid Search?

Hybrid search combines two complementary search paradigms:

```
┌─────────────────────────────────────────────────────────────────┐
│                        HYBRID SEARCH                             │
├─────────────────────────────┬───────────────────────────────────┤
│     DENSE (Semantic)        │       SPARSE (BM25/Lexical)       │
├─────────────────────────────┼───────────────────────────────────┤
│ Query → Embedding → ANN     │ Query → Tokenize → Inverted Index │
│                             │                                   │
│ Finds: Similar MEANING      │ Finds: Exact KEYWORDS             │
│                             │                                   │
│ "authenticate users"        │ "AuthService login"               │
│      matches                │      matches                      │
│ "verify credentials"        │ "AuthService", "login" literally  │
│                             │                                   │
│ Strength: Synonyms,         │ Strength: Identifiers, exact      │
│           paraphrases       │           function/class names    │
│                             │                                   │
│ Weakness: May miss exact    │ Weakness: No semantic             │
│           identifier names  │           understanding           │
└─────────────────────────────┴───────────────────────────────────┘
                              │
                              ▼
                    RRF FUSION (Combine Results)
```

### Search Implementation

```typescript
async semanticSearch(
    codebasePath: string,
    query: string,
    topK: number = 5,
    threshold: number = 0.5,
    filterExpr?: string
): Promise<SemanticSearchResult[]> {

    const isHybrid = this.getIsHybrid();
    const collectionName = this.getCollectionName(codebasePath);

    if (isHybrid) {
        // Generate query embedding for dense search
        const queryEmbedding = await this.embedding.embed(query);

        // Prepare hybrid search requests
        const searchRequests: HybridSearchRequest[] = [
            {
                data: queryEmbedding.vector,    // Dense: query vector
                anns_field: "vector",
                param: { "nprobe": 10 },        // Search 10 clusters
                limit: topK
            },
            {
                data: query,                     // Sparse: raw query text
                anns_field: "sparse_vector",
                param: { "drop_ratio_search": 0.2 },  // Drop low-weight terms
                limit: topK
            }
        ];

        // Execute hybrid search with RRF reranking
        const searchResults = await this.vectorDatabase.hybridSearch(
            collectionName,
            searchRequests,
            {
                rerank: {
                    strategy: 'rrf',
                    params: { k: 60 }    // RRF smoothing parameter
                },
                limit: topK,
                filterExpr
            }
        );

        return searchResults.map(result => ({
            content: result.document.content,
            relativePath: result.document.relativePath,
            startLine: result.document.startLine,
            endLine: result.document.endLine,
            language: result.document.metadata.language,
            score: result.score
        }));

    } else {
        // Regular semantic search (dense only)
        const queryEmbedding = await this.embedding.embed(query);

        const searchResults = await this.vectorDatabase.search(
            collectionName,
            queryEmbedding.vector,
            { topK, threshold, filterExpr }
        );

        return searchResults.map(/* ... */);
    }
}
```

### RRF (Reciprocal Rank Fusion) Explained

```
Query: "AuthService error handling"

Dense Search Results:          Sparse Search Results:
1. chunk_A (rank 1)           1. chunk_B (rank 1)  ← exact "AuthService" match
2. chunk_C (rank 2)           2. chunk_A (rank 2)
3. chunk_B (rank 3)           3. chunk_D (rank 3)

RRF Formula: score(doc) = Σ 1/(k + rank)
             where k = 60 (smoothing constant)

chunk_A: 1/(60+1) + 1/(60+2) = 0.0164 + 0.0161 = 0.0325  ← Winner
chunk_B: 1/(60+3) + 1/(60+1) = 0.0159 + 0.0164 = 0.0323
chunk_C: 1/(60+2) + 0        = 0.0161
chunk_D: 0        + 1/(60+3) = 0.0159

Final Ranking: [chunk_A, chunk_B, chunk_C, chunk_D]
```

**Why RRF Works Well**:
- Documents appearing in both result sets get boosted
- Exact keyword matches (sparse) complement semantic matches (dense)
- No need to normalize scores between different metrics

---

## Incremental Indexing with Merkle DAG

### The Problem

Re-indexing an entire codebase on every change is expensive:
- Re-read all files
- Re-generate all embeddings
- Re-insert all vectors

### The Solution: Merkle DAG

```
┌─────────────────────────────────────────────────────────────────┐
│                       MERKLE DAG                                 │
│                                                                  │
│                    ┌──────────────┐                             │
│                    │  Root Node   │                             │
│                    │ hash: abc123 │                             │
│                    └──────┬───────┘                             │
│           ┌───────────────┼───────────────┐                     │
│           ▼               ▼               ▼                     │
│    ┌────────────┐  ┌────────────┐  ┌────────────┐              │
│    │  file1.ts  │  │  file2.py  │  │  file3.go  │              │
│    │ hash: def  │  │ hash: ghi  │  │ hash: jkl  │              │
│    └────────────┘  └────────────┘  └────────────┘              │
│                                                                  │
│  If file2.py changes → new hash → root hash changes            │
│  Compare old vs new DAG → identify exactly which files changed │
└─────────────────────────────────────────────────────────────────┘
```

### Implementation

```typescript
export class MerkleDAG {
    nodes: Map<string, MerkleDAGNode>;
    rootIds: string[];

    private hash(data: string): string {
        return crypto.createHash('sha256').update(data).digest('hex');
    }

    public addNode(data: string, parentId?: string): string {
        const nodeId = this.hash(data);
        const node: MerkleDAGNode = {
            id: nodeId,
            hash: nodeId,
            data,
            parents: parentId ? [parentId] : [],
            children: []
        };

        if (parentId) {
            const parentNode = this.nodes.get(parentId);
            if (parentNode) {
                node.parents.push(parentId);
                parentNode.children.push(nodeId);
            }
        } else {
            this.rootIds.push(nodeId);
        }

        this.nodes.set(nodeId, node);
        return nodeId;
    }

    public static compare(dag1: MerkleDAG, dag2: MerkleDAG): {
        added: string[],
        removed: string[],
        modified: string[]
    } {
        const nodes1 = new Map(dag1.getAllNodes().map(n => [n.id, n]));
        const nodes2 = new Map(dag2.getAllNodes().map(n => [n.id, n]));

        const added = [...nodes2.keys()].filter(k => !nodes1.has(k));
        const removed = [...nodes1.keys()].filter(k => !nodes2.has(k));

        const modified: string[] = [];
        for (const [id, node1] of nodes1.entries()) {
            const node2 = nodes2.get(id);
            if (node2 && node1.data !== node2.data) {
                modified.push(id);
            }
        }

        return { added, removed, modified };
    }
}
```

### File Synchronizer

```typescript
export class FileSynchronizer {
    private fileHashes: Map<string, string>;
    private merkleDAG: MerkleDAG;
    private snapshotPath: string;  // ~/.context/merkle/{md5(path)}.json

    private async hashFile(filePath: string): Promise<string> {
        const content = await fs.readFile(filePath, 'utf-8');
        return crypto.createHash('sha256').update(content).digest('hex');
    }

    public async checkForChanges(): Promise<{
        added: string[],
        removed: string[],
        modified: string[]
    }> {
        // Generate current file hashes
        const newFileHashes = await this.generateFileHashes(this.rootDir);
        const newMerkleDAG = this.buildMerkleDAG(newFileHashes);

        // Compare DAGs
        const changes = MerkleDAG.compare(this.merkleDAG, newMerkleDAG);

        if (changes.added.length || changes.removed.length || changes.modified.length) {
            // Do file-level comparison for precise changes
            const fileChanges = this.compareStates(this.fileHashes, newFileHashes);

            // Update state and save snapshot
            this.fileHashes = newFileHashes;
            this.merkleDAG = newMerkleDAG;
            await this.saveSnapshot();

            return fileChanges;
        }

        return { added: [], removed: [], modified: [] };
    }
}
```

### Incremental Re-indexing

```typescript
async reindexByChange(codebasePath: string): Promise<{
    added: number,
    removed: number,
    modified: number
}> {
    const synchronizer = this.synchronizers.get(collectionName);
    const { added, removed, modified } = await synchronizer.checkForChanges();

    if (added.length + removed.length + modified.length === 0) {
        console.log('No file changes detected.');
        return { added: 0, removed: 0, modified: 0 };
    }

    // Handle removed files - delete their chunks
    for (const file of removed) {
        await this.deleteFileChunks(collectionName, file);
    }

    // Handle modified files - delete old chunks first
    for (const file of modified) {
        await this.deleteFileChunks(collectionName, file);
    }

    // Re-index added and modified files
    const filesToIndex = [...added, ...modified].map(f => path.join(codebasePath, f));
    await this.processFileList(filesToIndex, codebasePath);

    return { added: added.length, removed: removed.length, modified: modified.length };
}
```

---

## MCP Tool Handlers

### Available Tools

| Tool | Parameters | Description |
|------|------------|-------------|
| `index_codebase` | `path`, `force?`, `splitter?`, `customExtensions?`, `ignorePatterns?` | Start background indexing |
| `search_code` | `path`, `query`, `limit?`, `extensionFilter?` | Search indexed codebase |
| `clear_index` | `path` | Remove collection from cloud |
| `get_indexing_status` | `path` | Check indexing progress |

### Background Indexing Flow

```typescript
public async handleIndexCodebase(args: any) {
    const { path: codebasePath, force, splitter, customExtensions, ignorePatterns } = args;

    // 1. Sync with cloud first
    await this.syncIndexedCodebasesFromCloud();

    // 2. Validate path
    const absolutePath = ensureAbsolutePath(codebasePath);
    if (!fs.existsSync(absolutePath)) {
        return { isError: true, text: `Path does not exist` };
    }

    // 3. Check if already indexing
    if (this.snapshotManager.getIndexingCodebases().includes(absolutePath)) {
        return { isError: true, text: `Already being indexed` };
    }

    // 4. Pre-validate collection creation
    const canCreate = await this.context.getVectorDatabase().checkCollectionLimit();
    if (!canCreate) {
        return { isError: true, text: COLLECTION_LIMIT_MESSAGE };
    }

    // 5. Set status and start background indexing
    this.snapshotManager.setCodebaseIndexing(absolutePath, 0);
    this.startBackgroundIndexing(absolutePath, force, splitter);

    return { text: `Started background indexing for '${absolutePath}'` };
}

private async startBackgroundIndexing(codebasePath: string, force: boolean, splitter: string) {
    try {
        // Initialize file synchronizer
        const synchronizer = new FileSynchronizer(codebasePath, ignorePatterns);
        await synchronizer.initialize();

        // Start indexing with progress callback
        const stats = await this.context.indexCodebase(
            codebasePath,
            (progress) => {
                this.snapshotManager.setCodebaseIndexing(codebasePath, progress.percentage);

                // Periodic snapshot save (every 2 seconds)
                if (Date.now() - lastSaveTime >= 2000) {
                    this.snapshotManager.saveCodebaseSnapshot();
                }
            }
        );

        // Mark as indexed
        this.snapshotManager.setCodebaseIndexed(codebasePath, stats);

    } catch (error) {
        // Mark as failed
        this.snapshotManager.setCodebaseIndexFailed(codebasePath, error.message);
    }
}
```

### Search with Extension Filtering

```typescript
public async handleSearchCode(args: any) {
    const { path: codebasePath, query, limit = 10, extensionFilter } = args;

    // Build filter expression for Milvus
    let filterExpr: string | undefined;
    if (Array.isArray(extensionFilter) && extensionFilter.length > 0) {
        const quoted = extensionFilter.map(e => `'${e}'`).join(', ');
        filterExpr = `fileExtension in [${quoted}]`;
        // e.g., "fileExtension in ['.ts', '.tsx', '.js']"
    }

    const searchResults = await this.context.semanticSearch(
        absolutePath,
        query,
        Math.min(limit, 50),
        0.3,          // similarity threshold
        filterExpr
    );

    // Format results
    return searchResults.map((result, index) => ({
        rank: index + 1,
        location: `${result.relativePath}:${result.startLine}-${result.endLine}`,
        language: result.language,
        content: truncateContent(result.content, 5000)
    }));
}
```

---

## Chunk Overlap and Retrieval Limitations

### The Overlap Mechanism

```
Original 5000-char function (exceeds 2500 limit):
┌────────────────────────────────────────────────────────────────┐
│ Line 1 ──────────────────────────────────────────── Line 200   │
└────────────────────────────────────────────────────────────────┘

After splitting with 300-char overlap:
┌──────────────────────────┐
│ chunk_1 (lines 1-80)     │
└──────────────────────────┘
           ┌───────────────────────────┐
           │▓▓▓│ chunk_2 (lines 70-160) │  ← ▓▓▓ = last 300 chars of chunk_1
           └───────────────────────────┘
                       ┌───────────────────────────┐
                       │▓▓▓│ chunk_3 (lines 150-200)│  ← ▓▓▓ = last 300 chars of chunk_2
                       └───────────────────────────┘
```

### Critical Limitation: No Retrieval Guarantee

**The overlap helps with context continuity for the LLM, but does NOT guarantee retrieval of related chunks.**

```
Scenario: Function split across chunks

chunk_1:
┌─────────────────────────────────┐
│ async authenticate(user, pass) {│
│   const session = await db.get()│
│   if (!session) {               │
│     throw new AuthError(...)    │  ← Error DEFINITION
└─────────────────────────────────┘

chunk_2:
┌─────────────────────────────────┐
│   ...overlap...                 │
│   } catch (e) {                 │
│     logger.error(e)             │  ← Error HANDLING
│     return null                 │
└─────────────────────────────────┘

Query: "How does authenticate handle errors?"

Vector search scores each chunk INDEPENDENTLY:
  - chunk_2 (score: 0.85) ← mentions "error", "catch"
  - chunk_1 (score: 0.72) ← mentions "throw", "Error"

With top_k=1: Only chunk_2 returned!
User misses the error definition in chunk_1.
```

### Why This Happens

1. **Each chunk is embedded independently** - no relationship metadata
2. **No parent-child linking** in the vector database
3. **Similarity computed per-chunk** - no cross-chunk awareness

### Solutions (Not Implemented in claude-context)

| Solution | Description | Tradeoff |
|----------|-------------|----------|
| **Higher top_k + Reranking** | Retrieve 50, rerank to top 5 | More compute, latency |
| **Parent-Child Chunking** | Store parent (full function), embed children (sub-sections), return parent on child match | 2x storage |
| **Contextual Retrieval** | Prepend chunk summary to content before embedding | More tokens, better recall |
| **Higher Overlap** | 50% overlap instead of 12% | Redundant storage |
| **Multi-Vector (ColBERT)** | One vector per token, match at token level | Complex infrastructure |

---

## Configuration and Environment

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | - | OpenAI API key for embeddings |
| `OPENAI_BASE_URL` | - | Custom OpenAI-compatible endpoint |
| `ZILLIZ_CLOUD_URI` | - | Zilliz Cloud cluster URI |
| `ZILLIZ_CLOUD_TOKEN` | - | Zilliz Cloud API token |
| `HYBRID_MODE` | `true` | Enable hybrid search (dense + BM25) |
| `EMBEDDING_BATCH_SIZE` | `100` | Chunks per embedding API call |
| `CUSTOM_EXTENSIONS` | - | Comma-separated additional file extensions |
| `CUSTOM_IGNORE_PATTERNS` | - | Comma-separated additional ignore patterns |

### Default Supported Extensions

```typescript
const DEFAULT_SUPPORTED_EXTENSIONS = [
    // Programming languages
    '.ts', '.tsx', '.js', '.jsx', '.py', '.java', '.cpp', '.c', '.h', '.hpp',
    '.cs', '.go', '.rs', '.php', '.rb', '.swift', '.kt', '.scala', '.m', '.mm',
    // Text and markup
    '.md', '.markdown', '.ipynb',
];
```

### Default Ignore Patterns

```typescript
const DEFAULT_IGNORE_PATTERNS = [
    // Build output
    'node_modules/**', 'dist/**', 'build/**', 'out/**', 'target/**',
    // IDE/Editor
    '.vscode/**', '.idea/**', '*.swp',
    // Version control
    '.git/**', '.svn/**',
    // Cache
    '.cache/**', '__pycache__/**', '.pytest_cache/**',
    // Minified/bundled
    '*.min.js', '*.min.css', '*.bundle.js', '*.map',
];
```

---

## Comparison with Other Implementations

| Feature | claude-context | Context-Engine | Augment |
|---------|---------------|----------------|---------|
| **Chunking** | AST (tree-sitter, 9 langs) | Token/Line/Semantic | Unknown |
| **Embedding** | OpenAI/VoyageAI/Gemini/Ollama | BGE-base-en-v1.5 | Custom (claimed) |
| **Vector DB** | Zilliz Cloud (managed) | Qdrant (self-hosted) | Unknown |
| **Hybrid Search** | Dense + BM25 (RRF) | Dense + BM25 (mini vectors) | Yes |
| **Incremental Index** | Merkle DAG | Not implemented | Real-time streaming |
| **Overlap Strategy** | 300 chars prepended | None documented | Unknown |
| **MCP Support** | Native | No | Native |
| **Cloud-First** | Yes (Zilliz Cloud) | No (local Qdrant) | Yes |

---

## Implementation Patterns for Your Own System

### Pattern 1: AST-First Chunking

```python
# Pseudocode for implementing AST-aware chunking
import tree_sitter

def chunk_code(code: str, language: str, chunk_size: int = 2500) -> List[Chunk]:
    parser = get_parser(language)
    tree = parser.parse(code.encode())

    chunks = []
    for node in traverse_splittable_nodes(tree.root_node, language):
        node_text = code[node.start_byte:node.end_byte]

        if len(node_text) <= chunk_size:
            chunks.append(Chunk(content=node_text, start=node.start_point[0]))
        else:
            # Split large nodes line-by-line
            sub_chunks = split_by_lines(node_text, chunk_size)
            chunks.extend(sub_chunks)

    # Add overlap
    return add_overlap(chunks, overlap_size=300)
```

### Pattern 2: Hybrid Search with RRF

```python
def hybrid_search(query: str, collection: str, top_k: int = 10) -> List[Result]:
    # Dense search
    query_embedding = embed(query)
    dense_results = vector_db.search(
        collection=collection,
        vector=query_embedding,
        limit=top_k * 2  # Over-fetch for fusion
    )

    # Sparse search (BM25)
    sparse_results = vector_db.bm25_search(
        collection=collection,
        query=query,
        limit=top_k * 2
    )

    # RRF Fusion
    scores = defaultdict(float)
    k = 60  # Smoothing constant

    for rank, result in enumerate(dense_results):
        scores[result.id] += 1 / (k + rank + 1)

    for rank, result in enumerate(sparse_results):
        scores[result.id] += 1 / (k + rank + 1)

    # Sort by combined score
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [get_document(doc_id) for doc_id, _ in fused[:top_k]]
```

### Pattern 3: Merkle DAG for Incremental Sync

```python
class IncrementalIndexer:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.snapshot_path = self._get_snapshot_path()
        self.file_hashes = {}

    def check_changes(self) -> Dict[str, List[str]]:
        current_hashes = self._scan_files()

        added = [f for f in current_hashes if f not in self.file_hashes]
        removed = [f for f in self.file_hashes if f not in current_hashes]
        modified = [
            f for f in current_hashes
            if f in self.file_hashes and current_hashes[f] != self.file_hashes[f]
        ]

        self.file_hashes = current_hashes
        self._save_snapshot()

        return {"added": added, "removed": removed, "modified": modified}

    def _hash_file(self, path: str) -> str:
        content = open(path, 'rb').read()
        return hashlib.sha256(content).hexdigest()
```

---

## Summary

Claude-context is a **production-quality implementation** of semantic code search with several notable design decisions:

1. **AST-First Chunking**: Uses tree-sitter for semantically meaningful chunks aligned with code structure

2. **Hybrid Search by Default**: Combines dense embeddings (semantic) with BM25 (lexical) using RRF fusion

3. **Cloud-First Architecture**: Built around Zilliz Cloud - no self-hosted option, but managed infrastructure

4. **Merkle DAG Sync**: Efficient incremental indexing by tracking file hashes

5. **Multi-Provider Embeddings**: Supports OpenAI, VoyageAI, Gemini, and Ollama

6. **Background Indexing**: Non-blocking indexing with progress tracking, allows partial search during indexing

**Key Limitation**: Like most chunked RAG systems, there's no guarantee of retrieving all related chunks when information spans chunk boundaries. The 300-char overlap helps context continuity but doesn't solve the retrieval problem.

---

## References

- [claude-context GitHub Repository](https://github.com/zilliztech/claude-context)
- [Milvus Documentation](https://milvus.io/docs)
- [Tree-sitter Documentation](https://tree-sitter.github.io/tree-sitter/)
- [Reciprocal Rank Fusion Paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
