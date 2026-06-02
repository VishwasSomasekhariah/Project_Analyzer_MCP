"""
Hybrid Retrieval Service for Comprehensive Code Analysis

Combines vector search (semantic similarity) with Enhanced Graph RAG (structural analysis)
for comprehensive code understanding.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from src.core.paths import NEO4J_CONFIG, GENPOD_SEMANTIC_RAG_BIN

logger = logging.getLogger(__name__)

@dataclass 
class RetrievalResult:
    """Container for retrieval results with metadata"""
    content: Any
    source: str  # "vector" or "graph"
    relevance_score: float
    metadata: Dict[str, Any]
    file_path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None

class HybridRetrievalService:
    """
    Hybrid retrieval combining vector search and Enhanced Graph RAG.
    
    Workflow:
    1. Extract entities and classify intent (using Enhanced RAG components)
    2. Execute parallel retrieval: Vector Search + Graph RAG 
    3. Cross-modal fusion with deduplication
    4. Hybrid reranking using multiple signals
    5. Multi-modal synthesis
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.vector_weight = self.config.get("vector_weight", 0.4)
        self.graph_weight = self.config.get("graph_weight", 0.6)
        self.fusion_threshold = self.config.get("fusion_threshold", 0.3)
        
    async def comprehensive_retrieve(
        self,
        user_query: str,
        vector_params: Dict[str, Any],
        graph_params: Dict[str, Any],
        max_results: int = 20
    ) -> Dict[str, Any]:
        """
        Execute comprehensive hybrid retrieval.
        
        Args:
            user_query: Natural language query
            vector_params: Parameters for vector search
            graph_params: Parameters for graph RAG
            max_results: Maximum combined results
            
        Returns:
            Comprehensive analysis with hybrid results
        """
        start_time = time.time()
        
        # Step 1: Entity extraction and intent classification (reuse Enhanced RAG)
        entities, intent_info = await self._extract_entities_and_intent(user_query)
        
        # Step 2: Parallel retrieval execution
        vector_task = self._execute_vector_retrieval(user_query, entities, vector_params)
        graph_task = self._execute_graph_retrieval(user_query, entities, intent_info, graph_params)
        
        vector_results, graph_results = await asyncio.gather(
            vector_task, graph_task, return_exceptions=True
        )
        
        # Handle exceptions
        if isinstance(vector_results, Exception):
            logger.error(f"Vector retrieval failed: {vector_results}")
            vector_results = {"results": [], "status": "error", "error": str(vector_results)}
            
        if isinstance(graph_results, Exception):
            logger.error(f"Graph retrieval failed: {graph_results}")
            graph_results = {"results": [], "status": "error", "error": str(graph_results)}
        
        # Step 3: Cross-modal fusion and deduplication
        logger.info(f"🔍 FUSION DEBUG - Before fusion:")
        logger.info(f"  Vector results count: {len(vector_results.get('results', []))}")
        logger.info(f"  Graph results count: {len(graph_results.get('results', []))}")
        
        fused_results = await self._fuse_and_deduplicate(
            vector_results, graph_results, entities, intent_info
        )
        
        logger.info(f"🔍 FUSION DEBUG - After deduplication:")
        logger.info(f"  Fused results count: {len(fused_results)}")
        for i, result in enumerate(fused_results[:3]):  # Show first 3
            logger.info(f"    Result {i+1}: source={result.source}, content_preview={str(result.content)[:100]}...")
        
        # Step 4: Hybrid reranking
        logger.info(f"🔍 FUSION DEBUG - Before reranking: {len(fused_results)} results")
        ranked_results = await self._hybrid_rerank(
            fused_results, user_query, entities, intent_info, max_results
        )
        
        logger.info(f"🔍 FUSION DEBUG - After reranking:")
        logger.info(f"  Ranked results count: {len(ranked_results)}")
        logger.info(f"  Max results param: {max_results}")
        for i, result in enumerate(ranked_results):
            logger.info(f"    Ranked {i+1}: source={result.source}, score={result.relevance_score}, content_preview={str(result.content)[:50]}...")
        
        # Step 5: Multi-modal synthesis using LLM service
        try:
            from src.core.llm_service import LLMService
            
            llm_service = LLMService({
                "cache_ttl": 1800
            })
            
            # Prepare context from hybrid results for synthesis
            context = {
                "top_k_selected": len(ranked_results),
                "results": [self._result_to_dict(result) for result in ranked_results]
            }
            
            # Synthesize comprehensive response using LLM
            synthesis = await llm_service.synthesize_targeted_response(
                context, user_query, entities
            )
            
            # Add hybrid-specific metadata to existing metadata
            if "metadata" not in synthesis:
                synthesis["metadata"] = {}
            synthesis["metadata"]["hybrid_analysis"] = {
                "vector_sources": len([r for r in ranked_results if r.source == "vector"]),
                "graph_sources": len([r for r in ranked_results if r.source == "graph"]),
                "total_results": len(ranked_results)
            }
            
        except Exception as synthesis_error:
            logger.warning(f"Synthesis failed: {synthesis_error}, using fallback")
            # Fallback to simple synthesis
            synthesis = {
                "answer": f"Based on the hybrid analysis of {len(ranked_results)} results from vector and graph sources, here are the key findings related to your query: {user_query}",
                "metadata": {
                    "total_results": len(ranked_results),
                    "synthesis_method": "fallback_simple",
                    "synthesis_error": str(synthesis_error)
                }
            }
        
        execution_time = time.time() - start_time
        
        return {
            "status": "success",
            "analysis_type": "hybrid_retrieval",
            "user_query": user_query,
            "entities_extracted": entities,
            "intent_detected": intent_info,
            "retrieval_results": {
                "vector": {
                    "status": vector_results.get("status", "unknown"),
                    "count": len(vector_results.get("results", [])),
                    "metadata": vector_results.get("metadata", {})
                },
                "graph": {
                    "status": graph_results.get("status", "unknown"), 
                    "count": len(graph_results.get("results", [])),
                    "metadata": graph_results.get("metadata", {})
                },
                "fused_count": len(fused_results),
                "final_count": len(ranked_results)
            },
            "hybrid_results": [self._result_to_dict(result) for result in ranked_results],
            "synthesis": synthesis.get("answer", ""),
            "synthesis_metadata": synthesis.get("metadata", {}),
            
            # RAW RESULTS FOR BENCHMARKING (crucial for reference-based metrics)
            "vector_raw_results": vector_results.get("raw_results", []),
            "cpg_raw_results": graph_results.get("raw_results", []),
            
            "performance": {
                "total_execution_time": round(execution_time, 3),
                "vector_weight_used": self.vector_weight,
                "graph_weight_used": self.graph_weight
            }
        }
    
    async def _extract_entities_and_intent(self, user_query: str) -> Tuple[Dict, Dict]:
        """Extract entities using Enhanced RAG components (same as working Enhanced RAG)"""
        try:
            from src.core.entity_extraction_service import EntityExtractionService
            from src.core.llm_service import LLMService
            
            llm_service = LLMService({
                "cache_ttl": 1800  # Same as working Enhanced RAG
            })
            
            # Create graph executor for entity extraction
            from src.core.graph_query_executor import GraphQueryExecutor
            executor = GraphQueryExecutor()
            
            # Extract entities with graph access (same as working Enhanced RAG)
            entity_service = EntityExtractionService(llm_service, graph_executor=executor)
            entities = await entity_service.extract_entities(user_query)
            
            # Use entities as intent context (same approach as working Enhanced RAG)
            intent_info = {"type": "structural", "confidence": 0.8}  # Default intent info
            
            return entities, intent_info
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return {}, {"type": "unknown", "confidence": 0.0}
    
    async def _execute_vector_retrieval(
        self, 
        user_query: str, 
        entities: Dict, 
        vector_params: Dict
    ) -> Dict[str, Any]:
        """Execute vector search with entity-enhanced queries"""
        try:
            # Create enhanced query with entity context
            enhanced_query = self._enhance_query_for_vector(user_query, entities)
            
            # Implement vector search using genpod-semantic-rag CLI (same as query_vector_only)
            logger.info(f"🔍 HYBRID VECTOR DEBUG - Executing vector search with query: {enhanced_query}")
            
            import subprocess
            import os
            import json
            
            # Build CLI command (same as query_vector_only)
            cli_command = [
                GENPOD_SEMANTIC_RAG_BIN, "query", enhanced_query,
                "--collection-name", vector_params.get("collection_name", ""),
                "--max-results", str(vector_params.get("max_results", 10)),
                "--output-format", "json"
            ]
            
            # Add config if provided
            config = vector_params.get("config")
            if config and os.path.exists(config):
                cli_command.extend(["--config", config])
            
            logger.info(f"🔍 HYBRID VECTOR DEBUG - CLI command: {' '.join(cli_command)}")
            
            # Execute command (same as query_vector_only)
            cli_result = subprocess.run(
                cli_command,
                text=True,
                capture_output=True,
                check=False,
                cwd=os.getcwd()
            )
            
            logger.info(f"🔍 HYBRID VECTOR DEBUG - CLI result code: {cli_result.returncode}")
            logger.info(f"🔍 HYBRID VECTOR DEBUG - CLI stdout: {cli_result.stdout[:200]}...")
            
            if cli_result.returncode == 0:
                try:
                    parsed_results = json.loads(cli_result.stdout)
                    result = {
                        "status": "success",
                        "raw_results": parsed_results.get("results", []),
                        "ai_response": parsed_results.get("ai_response", ""),
                        "metadata": parsed_results.get("metadata", {})
                    }
                    logger.info(f"🔍 HYBRID VECTOR DEBUG - Parsed {len(result['raw_results'])} vector results")
                except json.JSONDecodeError as e:
                    logger.error(f"🔍 HYBRID VECTOR DEBUG - JSON decode error: {e}")
                    result = {
                        "status": "error",
                        "raw_results": [],
                        "error": f"JSON decode error: {e}"
                    }
            else:
                logger.error(f"🔍 HYBRID VECTOR DEBUG - CLI failed: {cli_result.stderr}")
                result = {
                    "status": "error",
                    "raw_results": [],
                    "error": cli_result.stderr
                }
            
            # Normalize vector results format
            normalized_results = []
            if result.get("status") == "success":
                raw_results = result.get("raw_results", [])
                for i, item in enumerate(raw_results):
                    normalized_results.append(RetrievalResult(
                        content=item,
                        source="vector",
                        relevance_score=1.0 - (i * 0.1),  # Decreasing relevance
                        metadata={
                            "vector_rank": i,
                            "search_query": enhanced_query,
                            "original_query": user_query
                        }
                    ))
            
            return {
                "status": result.get("status", "error"),
                "results": normalized_results,
                "raw_results": result.get("raw_results", []),  # Preserve original raw results
                "metadata": {
                    "enhanced_query": enhanced_query,
                    "original_results_count": len(result.get("raw_results", [])),
                    "search_metadata": result.get("metadata", {})
                },
                "error": result.get("error")
            }
            
        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return {"status": "error", "results": [], "error": str(e)}
    
    async def _execute_graph_retrieval(
        self, 
        user_query: str, 
        entities: Dict, 
        intent_info: Dict,
        graph_params: Dict
    ) -> Dict[str, Any]:
        """Execute Enhanced Graph RAG retrieval - reimplemented for hybrid service"""
        try:
            logger.info(f"🔍 HYBRID DEBUG - Starting Enhanced RAG workflow for query: {user_query}")
            
            # Import Enhanced RAG components directly (no tool dependencies)
            from src.core.entity_extraction_service import EntityExtractionService
            from src.core.subgraph_planner import SubgraphPlanner
            from src.core.graph_query_executor import GraphQueryExecutor
            from src.core.content_reranker import ContentReranker
            from src.core.llm_service import LLMService
            
            # Initialize LLM service (same as working Enhanced RAG)
            llm_service = LLMService({
                "cache_ttl": 1800  # Use same default as working Enhanced RAG
            })
            
            # Step 1: Use provided entities or extract new ones
            if not entities or len(entities) == 0:
                logger.info("🔍 HYBRID DEBUG - No entities provided, extracting new ones")
                # Use same executor as above
                entity_service = EntityExtractionService(llm_service, graph_executor=executor)
                entities = await entity_service.extract_entities(user_query)
            logger.info(f"🔍 HYBRID DEBUG - Using entities: {entities}")
            
            # Step 2: Plan subgraph retrieval strategy
            planner = SubgraphPlanner()
            plan = await planner.plan_retrieval(entities, user_query)
            logger.info(f"🔍 HYBRID DEBUG - Retrieval plan: {plan}")
            
            # Step 3: Execute planned subgraph queries
            executor = GraphQueryExecutor()
            config_path = graph_params.get("config_path", NEO4J_CONFIG)
            logger.info(f"🔍 HYBRID DEBUG - About to execute subgraph retrieval with config: {config_path}")
            raw_results = await executor.execute_subgraph_retrieval(plan, config_path)
            logger.info(f"🔍 HYBRID DEBUG - Raw results received: {raw_results}")
            
            # Step 4: Rerank results by relevance
            reranker = ContentReranker()
            max_results = graph_params.get("max_results", 50)
            ranked_context = await reranker.rerank_subgraph_results(
                raw_results.get("combined_results", [])[:max_results], 
                entities,
                entities  # Pass entities as intent context (same as working Enhanced RAG)
            )
            logger.info(f"🔍 HYBRID DEBUG - Ranked context: {ranked_context}")
            
            # Return results in format expected by hybrid fusion
            result = {
                "status": "success",
                "raw_results": raw_results.get("combined_results", []),
                "ranked_results": ranked_context.get("ranked_nodes", []),
                "entities_extracted": entities,
                "retrieval_plan": plan,
                "metadata": {
                    "total_nodes": raw_results.get("total_nodes", 0),
                    "execution_time": raw_results.get("query_performance", {}).get("total_execution_time", 0)
                }
            }
            
            # Normalize graph results format
            normalized_results = []
            if result.get("status") == "success":
                raw_results = result.get("raw_results", [])
                ranking_metadata = result.get("metadata", {}).get("ranking_metadata", {})
                
                for i, item in enumerate(raw_results):
                    # Extract relevance score from ranking metadata if available
                    relevance_score = 0.8  # Default
                    if "scores" in ranking_metadata and i < len(ranking_metadata["scores"]):
                        relevance_score = ranking_metadata["scores"][i]
                    
                    normalized_results.append(RetrievalResult(
                        content=item,
                        source="graph",
                        relevance_score=relevance_score,
                        metadata={
                            "graph_rank": i,
                            "entities_used": entities,
                            "intent_type": intent_info.get("type"),
                            "file_path": item.get("file_path") if isinstance(item, dict) else None,
                            "node_type": item.get("node_type") if isinstance(item, dict) else None
                        },
                        file_path=item.get("file_path") if isinstance(item, dict) else None,
                        start_line=item.get("start_point", {}).get("row") if isinstance(item, dict) else None
                    ))
            
            return {
                "status": result.get("status", "error"),
                "results": normalized_results,
                "raw_results": result.get("raw_results", []),  # Preserve original raw results
                "metadata": {
                    "workflow": result.get("workflow"),
                    "entities_extracted": result.get("entities_extracted"),
                    "retrieval_plan": result.get("retrieval_plan"),
                    "ranking_metadata": ranking_metadata
                },
                "error": result.get("error")
            }
            
        except Exception as e:
            logger.error(f"Graph retrieval failed: {e}")
            return {"status": "error", "results": [], "error": str(e)}
    
    def _enhance_query_for_vector(self, user_query: str, entities: Dict) -> str:
        """Enhance query with entity information for better vector search"""
        enhancements = []
        
        # Add file context
        if entities.get("files"):
            files_str = " ".join(entities["files"])
            enhancements.append(f"files: {files_str}")
        
        # Add type context
        if entities.get("types"):
            types_str = " ".join(entities["types"])
            enhancements.append(f"classes: {types_str}")
        
        # Add function context
        if entities.get("functions"):
            funcs_str = " ".join(entities["functions"])
            enhancements.append(f"methods: {funcs_str}")
        
        # Add concept context
        if entities.get("concepts"):
            concepts_str = " ".join(entities["concepts"])
            enhancements.append(f"concepts: {concepts_str}")
        
        if enhancements:
            enhanced_query = f"{user_query} ({', '.join(enhancements)})"
            return enhanced_query
        
        return user_query
    
    async def _fuse_and_deduplicate(
        self,
        vector_results: Dict,
        graph_results: Dict, 
        entities: Dict,
        intent_info: Dict
    ) -> List[RetrievalResult]:
        """Fuse results from both sources and remove duplicates"""
        
        all_results = []
        seen_content = set()
        
        logger.info(f"🔍 DEDUP DEBUG - Starting deduplication:")
        
        # Combine results from both sources
        source_names = ["vector", "graph"]
        source_data = [vector_results.get("results", []), graph_results.get("results", [])]
        
        for source_name, source_results in zip(source_names, source_data):
            logger.info(f"  Processing {source_name} results: {len(source_results)} items")
            
            for i, result in enumerate(source_results):
                # Create content signature for deduplication
                content_sig = self._create_content_signature(result)
                
                logger.info(f"    {source_name}[{i}]: signature={content_sig}, source={getattr(result, 'source', 'unknown')}")
                
                if content_sig not in seen_content:
                    seen_content.add(content_sig)
                    all_results.append(result)
                    logger.info(f"      ✅ ADDED: New unique result (total: {len(all_results)})")
                else:
                    # Merge metadata from duplicate
                    existing_result = next(r for r in all_results if self._create_content_signature(r) == content_sig)
                    existing_result.metadata[f"{result.source}_duplicate"] = True
                    # Boost score for multi-source confirmation
                    existing_result.relevance_score = min(1.0, existing_result.relevance_score + 0.1)
                    logger.info(f"      ❌ DUPLICATE: Merged with existing result")
        
        logger.info(f"🔍 DEDUP DEBUG - Final results: {len(all_results)} unique items")
        return all_results
    
    def _create_content_signature(self, result: RetrievalResult) -> str:
        """Create a signature for content deduplication"""
        if isinstance(result.content, dict):
            # Handle different content patterns (vector vs graph results)
            content = result.content
            
            # For vector results (text-based)
            if result.source == "vector":
                file_path = content.get("metadata", {}).get("file_path", "")
                text_content = content.get("content", "")
                return f"vector::{file_path}::{abs(hash(text_content[:500]))}"
            
            # For graph results (structured Neo4j data)
            else:
                # Extract file path from different field patterns
                file_path = (content.get("file_path", "") or 
                           content.get("f.file_path", "") or 
                           content.get("contained.file_path", ""))
                
                # Extract name from different field patterns  
                name = (content.get("name", "") or
                       content.get("f.name", "") or
                       content.get("contained.name", "") or
                       content.get("t.name", ""))
                
                # Determine node type
                node_type = "file" if "f.name" in content else "class" if "contained.name" in content else "unknown"
                
                # Extract body for uniqueness
                body = (content.get("body", "") or
                       content.get("f.body", "") or
                       content.get("contained.body", "") or
                       content.get("t.body", ""))
                
                return f"graph::{file_path}::{node_type}::{name}::{abs(hash(str(body)[:200]))}"
                
        elif isinstance(result.content, str):
            return f"text::{abs(hash(result.content[:200]))}"
        else:
            return f"other::{abs(hash(str(result.content)))}"
    
    async def _hybrid_rerank(
        self,
        fused_results: List[RetrievalResult],
        user_query: str,
        entities: Dict,
        intent_info: Dict,
        max_results: int
    ) -> List[RetrievalResult]:
        """Apply hybrid reranking using multiple signals"""
        
        # Multi-factor scoring
        for result in fused_results:
            score_components = {}
            
            # 1. Source relevance score (40%)
            score_components["relevance"] = result.relevance_score * 0.4
            
            # 2. Entity alignment score (25%)
            entity_score = self._calculate_entity_alignment(result, entities)
            score_components["entity_alignment"] = entity_score * 0.25
            
            # 3. Intent alignment score (20%)
            intent_score = self._calculate_intent_alignment(result, intent_info)
            score_components["intent_alignment"] = intent_score * 0.20
            
            # 4. Multi-source bonus (10%)
            multi_source_bonus = 0.1 if result.metadata.get("vector_duplicate") or result.metadata.get("graph_duplicate") else 0.0
            score_components["multi_source"] = multi_source_bonus * 0.10
            
            # 5. Content richness (5%)
            richness_score = self._calculate_content_richness(result)
            score_components["content_richness"] = richness_score * 0.05
            
            # Final hybrid score
            result.metadata["score_components"] = score_components
            result.relevance_score = sum(score_components.values())
        
        # Sort by hybrid score and return top results
        sorted_results = sorted(fused_results, key=lambda x: x.relevance_score, reverse=True)
        return sorted_results[:max_results]
    
    def _calculate_entity_alignment(self, result: RetrievalResult, entities: Dict) -> float:
        """Calculate how well result aligns with extracted entities"""
        if not entities:
            return 0.5  # Neutral score
        
        content_str = str(result.content).lower()
        alignment_score = 0.0
        total_entities = 0
        
        # Check file alignment
        for file_name in entities.get("files", []):
            total_entities += 1
            if file_name.lower() in content_str:
                alignment_score += 1.0
        
        # Check type alignment  
        for type_name in entities.get("types", []):
            total_entities += 1
            if type_name.lower() in content_str:
                alignment_score += 1.0
        
        # Check function alignment
        for func_name in entities.get("functions", []):
            total_entities += 1
            if func_name.lower() in content_str:
                alignment_score += 1.0
        
        # Check concept alignment
        for concept in entities.get("concepts", []):
            total_entities += 1
            if concept.lower() in content_str:
                alignment_score += 0.5  # Concepts get partial credit
        
        return alignment_score / total_entities if total_entities > 0 else 0.5
    
    def _calculate_intent_alignment(self, result: RetrievalResult, intent_info: Dict) -> float:
        """Calculate how well result aligns with detected intent"""
        intent_type = intent_info.get("type", "unknown")
        
        # Intent-specific scoring
        if intent_type == "quantitative":
            # Favor results with numeric content or counting capability
            content_str = str(result.content).lower()
            return 1.0 if any(word in content_str for word in ["count", "number", "total", "many"]) else 0.3
        
        elif intent_type == "structural":
            # Favor results with structure information (classes, methods, etc.)
            return 1.0 if result.source == "graph" else 0.4
        
        elif intent_type == "relational":
            # Favor results showing relationships
            return 1.0 if result.source == "graph" else 0.3
        
        elif intent_type in ["locational", "comparative", "behavioral"]:
            # These intents benefit from both sources
            return 0.8 if result.source == "graph" else 0.6
        
        return 0.5  # Neutral for unknown intents
    
    def _calculate_content_richness(self, result: RetrievalResult) -> float:
        """Calculate content richness score"""
        if isinstance(result.content, dict):
            # Rich structured content gets higher score
            field_count = len(result.content.keys())
            has_body = bool(result.content.get("body"))
            has_location = bool(result.content.get("file_path"))
            
            richness = (field_count / 10.0) + (0.3 if has_body else 0) + (0.2 if has_location else 0)
            return min(1.0, richness)
        else:
            # Text content scored by length
            content_length = len(str(result.content))
            return min(1.0, content_length / 1000.0)
    
    async def _multi_modal_synthesis(
        self,
        ranked_results: List[RetrievalResult],
        user_query: str,
        entities: Dict,
        intent_info: Dict,
        vector_results: Dict,
        graph_results: Dict
    ) -> Dict[str, Any]:
        """Synthesize final answer using both vector and graph insights"""
        try:
            from src.core.llm_service import LLMService
            
            llm_service = LLMService({
                "cache_ttl": 1800  # Same as working Enhanced RAG
            })
            
            # Prepare context from hybrid results
            context = self._prepare_hybrid_context(ranked_results, vector_results, graph_results)
            
            # Use enhanced synthesis with hybrid context
            synthesis_result = await llm_service.synthesize_targeted_response(
                context, user_query, entities
            )
            
            # Add hybrid-specific metadata
            synthesis_result["metadata"]["hybrid_analysis"] = {
                "vector_sources": len([r for r in ranked_results if r.source == "vector"]),
                "graph_sources": len([r for r in ranked_results if r.source == "graph"]),
                "top_source_distribution": self._analyze_source_distribution(ranked_results[:5]),
                "fusion_quality": self._calculate_fusion_quality(ranked_results)
            }
            
            return synthesis_result
            
        except Exception as e:
            logger.error(f"Multi-modal synthesis failed: {e}")
            return {
                "answer": f"Analysis completed with {len(ranked_results)} results, but synthesis failed: {e}",
                "metadata": {"synthesis_error": str(e)}
            }
    
    def _prepare_hybrid_context(
        self, 
        ranked_results: List[RetrievalResult],
        vector_results: Dict,
        graph_results: Dict
    ) -> Dict[str, Any]:
        """Prepare context for synthesis from hybrid results"""
        
        vector_content = []
        graph_content = []
        
        for result in ranked_results:
            content_dict = {
                "content": result.content,
                "score": result.relevance_score,
                "metadata": result.metadata
            }
            
            if result.source == "vector":
                vector_content.append(content_dict)
            else:
                graph_content.append(content_dict)
        
        return {
            "ranked_nodes": ranked_results,  # For compatibility with existing synthesis
            "ranking_metadata": {
                "total_nodes_processed": len(ranked_results),
                "top_k_selected": len(ranked_results),
                "hybrid_sources": {
                    "vector_count": len(vector_content),
                    "graph_count": len(graph_content)
                }
            },
            "hybrid_context": {
                "vector_results": vector_content,
                "graph_results": graph_content,
                "fusion_metadata": {
                    "vector_status": vector_results.get("status"),
                    "graph_status": graph_results.get("status"),
                    "combined_approach": True
                }
            }
        }
    
    def _analyze_source_distribution(self, top_results: List[RetrievalResult]) -> Dict[str, Any]:
        """Analyze distribution of sources in top results"""
        vector_count = sum(1 for r in top_results if r.source == "vector")
        graph_count = sum(1 for r in top_results if r.source == "graph")
        
        return {
            "vector": vector_count,
            "graph": graph_count,
            "vector_percentage": (vector_count / len(top_results)) * 100 if top_results else 0,
            "graph_percentage": (graph_count / len(top_results)) * 100 if top_results else 0,
            "balanced": abs(vector_count - graph_count) <= 1
        }
    
    def _calculate_fusion_quality(self, ranked_results: List[RetrievalResult]) -> Dict[str, Any]:
        """Calculate quality metrics for fusion process"""
        if not ranked_results:
            return {"quality": "no_results"}
        
        # Diversity score
        sources = [r.source for r in ranked_results]
        diversity = len(set(sources)) / len(sources)
        
        # Score distribution
        scores = [r.relevance_score for r in ranked_results]
        avg_score = sum(scores) / len(scores)
        score_variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
        
        return {
            "diversity_score": diversity,
            "average_relevance": avg_score,
            "score_variance": score_variance,
            "quality_rating": "excellent" if (diversity > 0.4 and avg_score > 0.6) else "good" if diversity > 0.2 else "fair"
        }
    
    def _result_to_dict(self, result: RetrievalResult) -> Dict[str, Any]:
        """Convert RetrievalResult dataclass to dictionary for JSON serialization"""
        return {
            "content": result.content,
            "source": result.source,
            "relevance_score": result.relevance_score,
            "metadata": result.metadata,
            "file_path": result.file_path,
            "start_line": result.start_line,
            "end_line": result.end_line
        }