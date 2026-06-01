"""
Hybrid Workflow Nodes

LangGraph nodes for the Hybrid RAG workflow combining Vector and CPG retrievers
with sophisticated synthesis and validation using chain-of-thought reasoning.
"""
import json
import logging
import asyncio
import subprocess
import os
import tempfile
from typing import Dict, Any, List, Tuple, Type, TypeVar, Optional
from pydantic import ValidationError, BaseModel

from .models import (
    HybridState, IntentAnalysis, QueryIntent, RetrieverResult,
    RetrievalStatus, SynthesisResult, SynthesisStrategy, RetrieverCombination,
    CriticValidation, CrossValidationResult, BatchProcessingResult,
    ChainOfThoughtResult, ChainOfThoughtStep, IntentAnalysisRawResponse,
    SynthesisRawResponse, CriticValidationRawResponse, SynthesisImprovementRawResponse,
    EvidenceClaim, RetrieverSummary, ClaimExtractionRawResponse, ReconciliationRawResponse,
)
from src.core.paths import NEO4J_CONFIG, SCHEMA_PATH

logger = logging.getLogger(__name__)

# Type variable for Pydantic models
T = TypeVar('T', bound=BaseModel)

# Minimum confidence_score from pageindex CLI to consider the answer sufficient.
# Below this threshold the workflow falls back to vector + CPG.
_PAGEINDEX_SUFFICIENCY_MIN_CONFIDENCE: float = 0.4
_PAGEINDEX_SUFFICIENCY_MIN_ANSWER_CHARS: int = 50

# Feature flag — Issue #1: treat PageIndex as a full synthesis participant.
# When True, all active retrievers go through map-reduce synthesis (extract
# claims per retriever → reconcile → synthesise from compressed claims).
# Set to False to revert to the legacy single-source fallback behaviour.
_USE_MULTI_SOURCE_SYNTHESIS: bool = True


# ---------------------------------------------------------------------------
# Routing function (module-level — consumed by LangGraph conditional edge)
# ---------------------------------------------------------------------------

# route_after_pageindex is retained for backward compatibility but is no longer
# used by the V2 graph.  The new graph always flows:
#   pageindex_retrieval → enhance_query → [vector/cpg based on combination] → …
def route_after_pageindex(state: HybridState) -> str:
    if state.use_fallback:
        return "enhance_query"
    return "enhance_query"


class HybridWorkflowNodes:
    """
    Hybrid Workflow Nodes implementing LangGraph workflow pattern.
    
    Combines Vector and CPG retrievers with sophisticated synthesis,
    cross-validation, and critic-based quality assurance.
    """
    
    def __init__(self):
        self.cpg_workflow = None  # Will be initialized when needed
    
    async def _robust_llm_call_with_pydantic_validation(
        self,
        llm_service: Any,
        prompt: str,
        pydantic_model: Type[T],
        max_retries: int = 3,
        **llm_kwargs
    ) -> Tuple[Optional[T], Optional[str]]:
        """
        Make robust LLM call with Pydantic validation and retry logic.
        
        Args:
            llm_service: LLM service instance
            prompt: The prompt to send to the LLM
            pydantic_model: Pydantic model class for validation
            max_retries: Maximum number of retries (default: 3)
            **llm_kwargs: Additional arguments for generate_response
            
        Returns:
            Tuple of (validated_model_instance, error_message)
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"🤖 LLM call attempt {attempt + 1}/{max_retries + 1}")
                
                # Make LLM call
                result = await llm_service.generate_response(
                    prompt,
                    json_mode=True,
                    use_cache=False,
                    **llm_kwargs
                )
                
                if not result or result.error:
                    last_error = f"LLM generation failed: {result.error if result else 'No result'}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} failed: {last_error}")
                    continue
                
                # Parse JSON
                try:
                    json_data = json.loads(result.content)
                except json.JSONDecodeError as e:
                    last_error = f"JSON parsing failed: {e}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} JSON error: {last_error}")
                    
                    # Add feedback to prompt for next retry
                    if attempt < max_retries:
                        prompt = self._add_json_feedback_to_prompt(prompt, result.content, str(e))
                    continue
                
                # Validate with Pydantic
                try:
                    validated_model = pydantic_model(**json_data)
                    logger.info(f"✅ LLM call succeeded on attempt {attempt + 1}")
                    return validated_model, None
                    
                except ValidationError as e:
                    last_error = f"Pydantic validation failed: {e}"
                    logger.warning(f"⚠️ Attempt {attempt + 1} validation error: {last_error}")
                    
                    # Add feedback to prompt for next retry
                    if attempt < max_retries:
                        prompt = self._add_validation_feedback_to_prompt(prompt, json_data, str(e))
                    continue
                
            except Exception as e:
                last_error = f"Unexpected error: {e}"
                logger.warning(f"⚠️ Attempt {attempt + 1} unexpected error: {last_error}")
                continue
        
        logger.error(f"❌ LLM call failed after {max_retries + 1} attempts. Last error: {last_error}")
        return None, last_error
    
    def _add_json_feedback_to_prompt(self, original_prompt: str, failed_content: str, error: str) -> str:
        """Add JSON parsing feedback to prompt for retry"""
        feedback = f"""
        
IMPORTANT: Your previous response had JSON parsing errors:
Error: {error}
Previous response: {failed_content}
Please ensure your response is valid JSON format. Double-check:
- All strings are properly quoted
- No trailing commas  
- Proper bracket/brace nesting
- Use double quotes, not single quotes
"""
        return original_prompt + feedback
    
    def _add_validation_feedback_to_prompt(self, original_prompt: str, failed_data: dict, error: str) -> str:
        """Add Pydantic validation feedback to prompt for retry"""
        feedback = f"""
        
IMPORTANT: Your previous response had validation errors:
Validation Error: {error}
Previous data: {json.dumps(failed_data, indent=2)}
Please fix these validation issues:
- Ensure all required fields are present
- Check field types match the expected schema  
- Verify enum values are from the allowed set
- Make sure numerical values are within valid ranges
"""
        return original_prompt + feedback
    
    
    async def intent_analysis(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Analyze user query intent for routing and weighting decisions.
        
        Uses chain-of-thought reasoning to understand query intent and determine
        optimal weighting between Vector and CPG retrievers.
        """
        logger.info("🧠 Node: intent_analysis")
        
        try:
            llm_service = state.llm_service
            user_query = state.user_query
            
            # Chain-of-thought intent analysis prompt
            intent_prompt = f"""You are an expert query intent analyzer for hybrid code analysis systems.
Analyze this user query and determine the optimal retrieval strategy.

**CHAIN OF THOUGHT ANALYSIS**:

**User Query**: {user_query}

**Step 1: Query Type Classification**
Classify the query type and explain your reasoning:
- ARCHITECTURAL: High-level design, patterns, relationships (favor Vector: 0.7/0.3)
- DIRECT_LOOKUP: Specific functions, variables, exact matches (favor CPG: 0.3/0.7)  
- STRUCTURAL: Code structure, classes, inheritance (balanced: 0.5/0.5)
- RELATIONAL: Dependencies, calls, connections (favor CPG: 0.4/0.6)
- SEMANTIC: Conceptual understanding, similarity (favor Vector: 0.8/0.2)
- QUANTITATIVE: Counting, metrics, statistics (favor CPG: 0.2/0.8)

**Step 2: Entity Detection**
Identify key entities in the query:
- Files: Specific filenames mentioned
- Types: Classes, interfaces, structs mentioned  
- Functions: Method or function names mentioned
- Concepts: Abstract concepts or patterns mentioned

**Step 3: Complexity Assessment**
Assess query complexity and reasoning requirements:
- Simple: Direct lookup or single fact
- Complex: Multi-step reasoning or synthesis required

**Step 4: Optimal Weighting Decision**
Based on the analysis above, determine:
- Vector weight (0.0 to 1.0)
- CPG weight (must sum to 1.0 with vector weight)
- Primary intent classification
- Confidence in classification (0.0 to 1.0)

**OUTPUT FORMAT**:
Return ONLY a valid JSON object with this exact structure:
{{
    "intent": "ARCHITECTURAL|DIRECT_LOOKUP|STRUCTURAL|RELATIONAL|SEMANTIC|QUANTITATIVE",
    "confidence": <float 0.0-1.0>,
    "vector_weight": <float 0.0-1.0>,
    "cpg_weight": <float 0.0-1.0>,
    "reasoning": "Detailed step-by-step reasoning following the chain of thought above"
}}"""
            
            # Generate intent analysis with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=intent_prompt,
                pydantic_model=IntentAnalysisRawResponse,
                max_tokens=16000,
                temperature=0.1,  # Low temperature for consistent intent classification
                max_retries=3
            )
            
            if raw_response:
                try:
                    # Convert raw response to validated IntentAnalysis
                    intent_analysis = IntentAnalysis(
                        intent=QueryIntent(raw_response.intent.lower()),
                        confidence=raw_response.confidence,
                        vector_weight=raw_response.vector_weight,
                        cpg_weight=raw_response.cpg_weight,
                        reasoning=raw_response.reasoning
                    )
                    
                    logger.info(f"✅ Intent analysis completed: {intent_analysis.intent} (confidence: {intent_analysis.confidence:.2f})")
                    logger.info(f"📊 Weighting: Vector={intent_analysis.vector_weight:.2f}, CPG={intent_analysis.cpg_weight:.2f}")
                    
                    return {"intent_analysis": intent_analysis}
                    
                except (ValueError, ValidationError) as e:
                    logger.error(f"❌ Intent analysis enum conversion failed: {e}")
                    
            # Fallback intent analysis
            logger.warning(f"⚠️ Using fallback intent analysis. Error: {error}")
            fallback_analysis = IntentAnalysis(
                intent=QueryIntent.UNKNOWN,
                confidence=0.5,
                vector_weight=0.5,
                cpg_weight=0.5,
                reasoning=f"Fallback analysis due to LLM failure: {error}"
            )
            return {"intent_analysis": fallback_analysis}
            
        except Exception as e:
            logger.error(f"❌ Intent analysis failed: {e}")
            
            # Fallback with error logging
            error_fallback = IntentAnalysis(
                intent=QueryIntent.UNKNOWN,
                confidence=0.3,
                vector_weight=0.5,
                cpg_weight=0.5,
                reasoning=f"Error fallback: {str(e)}"
            )
            
            return {
                "intent_analysis": error_fallback,
                "error_log": state.error_log + [f"Intent analysis error: {str(e)}"]
            }
    
    # ------------------------------------------------------------------
    # PageIndex retrieval  (primary path)
    # ------------------------------------------------------------------

    async def pageindex_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute high-level PageIndex retrieval (primary path).

        Calls genpod-semantic-rag --retriever pageindex --project-path <path>.
        Determines sufficiency via:
          • non-empty results
          • answer length >= _PAGEINDEX_SUFFICIENCY_MIN_ANSWER_CHARS
          • confidence_score >= _PAGEINDEX_SUFFICIENCY_MIN_CONFIDENCE

        On success  → use_fallback=False, workflow routes to synthesize_response.
        On failure  → use_fallback=True, pageindex_learnings extracted to guide
                       vector + CPG fallback.
        """
        logger.info("📖 Node: pageindex_retrieval")

        try:
            user_query = state.user_query
            config = state.execution_metadata.get("config", {})
            pageindex_config = config.get("pageindex_config", {})

            project_path = pageindex_config.get("project_path")
            mcts_iterations = pageindex_config.get("mcts_iterations", 20)
            enable_ai = pageindex_config.get("enable_ai", True)
            semantic_rag_config = pageindex_config.get("config_path")  # optional --config

            if not project_path:
                logger.warning("⚠️ pageindex_config.project_path not set — skipping PageIndex, routing to fallback")
                return {
                    "pageindex_result": RetrieverResult(
                        retriever_type="pageindex",
                        status=RetrievalStatus.FAILED,
                        raw_results=[],
                        processed_results=[],
                        error="project_path not configured",
                        metadata={},
                        execution_time=0.0,
                    ),
                    "use_fallback": True,
                    "pageindex_learnings": {"failure_reason": "project_path not configured"},
                }

            cli_command = ["genpod-semantic-rag"]
            if semantic_rag_config:
                cli_command += ["--config", semantic_rag_config]
            cli_command += [
                "query", user_query,
                "--retriever", "pageindex",
                "--project-path", str(project_path),
                "--mcts-iterations", str(mcts_iterations),
                "--output-format", "json",
            ]
            if not enable_ai:
                cli_command.append("--disable-ai")

            logger.info(f"⚡ Executing PageIndex retrieval: {' '.join(cli_command)}")
            start_time = asyncio.get_event_loop().time()

            # Use a temp file for stderr instead of a pipe to prevent grandchild
            # processes (e.g. Claude SDK spawned by genpod-semantic-rag) from
            # inheriting the pipe and keeping it open indefinitely.
            with tempfile.NamedTemporaryFile(mode='w', suffix='.stderr', delete=False) as _stderr_f:
                _stderr_path = _stderr_f.name
                cli_result = subprocess.run(
                    cli_command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=_stderr_f,
                    check=False,
                    cwd=os.getcwd(),
                )
            with open(_stderr_path) as _f:
                cli_result.stderr = _f.read()
            os.unlink(_stderr_path)

            execution_time = asyncio.get_event_loop().time() - start_time

            if cli_result.returncode == 0:
                try:
                    parsed = json.loads(cli_result.stdout)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ PageIndex JSON parse error: {e}")
                    return {
                        "pageindex_result": RetrieverResult(
                            retriever_type="pageindex",
                            status=RetrievalStatus.FAILED,
                            raw_results=[],
                            processed_results=[],
                            error=f"JSON parse error: {e}",
                            metadata={},
                            execution_time=execution_time,
                        ),
                        "use_fallback": True,
                        "pageindex_learnings": {"failure_reason": f"json_parse_error: {e}"},
                        "error_log": state.error_log + [f"PageIndex JSON parse error: {e}"],
                    }

                results = parsed.get("results", [])
                response_text = parsed.get("response") or parsed.get("answer") or ""
                metadata = parsed.get("metadata") or {}
                confidence_score = parsed.get("confidence_score") or 0.0

                # Sufficiency check
                is_sufficient = (
                    bool(results)
                    and len(response_text.strip()) >= _PAGEINDEX_SUFFICIENCY_MIN_ANSWER_CHARS
                    and confidence_score >= _PAGEINDEX_SUFFICIENCY_MIN_CONFIDENCE
                )

                logger.info(
                    f"📖 PageIndex: {len(results)} nodes, answer={len(response_text)} chars, "
                    f"confidence={confidence_score:.2f}, sufficient={is_sufficient}"
                )

                validation = metadata.get("validation", {})
                entity_grounding = validation.get("entity_grounding", {})

                pi_result = RetrieverResult(
                    retriever_type="pageindex",
                    status=RetrievalStatus.SUCCESS if is_sufficient else RetrievalStatus.PARTIAL,
                    raw_results=results,
                    processed_results=results,
                    response_text=response_text,
                    metadata={
                        "query": user_query,
                        "results_count": len(results),
                        "total_results": parsed.get("total_results", len(results)),
                        "processing_time": parsed.get("processing_time", execution_time),
                        "confidence_score": confidence_score,
                        "mcts_iterations": mcts_iterations,
                        # flattened from metadata.validation
                        "faithfulness_score": validation.get("faithfulness_score"),
                        "coverage_score": validation.get("coverage_score"),
                        "unsupported_claims": validation.get("unsupported_claims", []),
                        "uncovered_topics": validation.get("uncovered_topics", []),
                        "hallucinated_count": entity_grounding.get("hallucinated_count"),
                        "hallucinated_entities": entity_grounding.get("hallucinated_entities", []),
                        "answer_identifiers": entity_grounding.get("answer_identifiers"),
                        "symbol_table_size": entity_grounding.get("symbol_table_size"),
                    },
                    execution_time=execution_time,
                )

                if is_sufficient:
                    logger.info("✅ PageIndex answer is sufficient — routing to synthesize_response")
                    return {"pageindex_result": pi_result, "use_fallback": False, "pageindex_learnings": {}}

                # Insufficient — extract rich learnings to guide fallback
                learnings = self._extract_pageindex_learnings(parsed, reason="insufficient_results")
                logger.info(
                    f"⚠️ PageIndex insufficient — learnings extracted: "
                    f"{len(learnings.get('relevant_files', []))} files, "
                    f"{len(learnings.get('citation_extracts', []))} citations, "
                    f"{len(learnings.get('uncovered_topics', []))} uncovered topics"
                )
                return {"pageindex_result": pi_result, "use_fallback": True, "pageindex_learnings": learnings}

            else:
                logger.error(f"❌ PageIndex CLI failed (exit {cli_result.returncode}): {cli_result.stderr}")
                learnings = {"failure_reason": "cli_error", "stderr": cli_result.stderr}
                return {
                    "pageindex_result": RetrieverResult(
                        retriever_type="pageindex",
                        status=RetrievalStatus.FAILED,
                        raw_results=[],
                        processed_results=[],
                        error=cli_result.stderr,
                        metadata={},
                        execution_time=execution_time,
                    ),
                    "use_fallback": True,
                    "pageindex_learnings": learnings,
                    "error_log": state.error_log + [f"PageIndex CLI error (exit {cli_result.returncode})"],
                }

        except Exception as e:
            logger.error(f"❌ PageIndex retrieval exception: {e}")
            return {
                "pageindex_result": RetrieverResult(
                    retriever_type="pageindex",
                    status=RetrievalStatus.FAILED,
                    raw_results=[],
                    processed_results=[],
                    error=str(e),
                    metadata={},
                    execution_time=0.0,
                ),
                "use_fallback": True,
                "pageindex_learnings": {"failure_reason": str(e)},
                "error_log": state.error_log + [f"PageIndex retrieval error: {str(e)}"],
            }

    def _extract_pageindex_learnings(self, parsed: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """
        Extract structured learnings from a partial/failed PageIndex CLI response.

        These learnings are stored in state.pageindex_learnings and used by:
          • combine_results  — folds partial pageindex results into the combined set
          • _build_hybrid_synthesis_prompt — gives synthesis the high-level context

        Fields drawn from the CLI JSON schema:
          results[].scoring_text  — rich per-node summaries
          results[].is_leaf/path  — relevant source files identified
          citations[].extract     — key verified text excerpts
          metadata.validation.uncovered_topics  — gaps to fill
          metadata.verification.claim_details   — unresolved claims
          metadata.validation.entity_grounding  — hallucination signals
          confidence_score        — top-level quality signal
        """
        results   = parsed.get("results", [])
        metadata  = parsed.get("metadata") or {}
        citations = parsed.get("citations") or []
        verification = metadata.get("verification", {})
        validation   = metadata.get("validation", {})
        entity_grounding = validation.get("entity_grounding", {})

        # Files the PageIndex identified as relevant (leaf nodes only)
        relevant_files = [
            {
                "title":   r.get("title", ""),
                "path":    r.get("path", ""),
                "md_path": r.get("md_path", ""),
                "score":   r.get("score", 0.0),
            }
            for r in results
            if r.get("is_leaf")
        ]

        # Compact node summaries from scoring_text (already trimmed by CLI)
        node_summaries = [
            {
                "title":   r.get("title", ""),
                "path":    r.get("path", ""),
                "depth":   r.get("depth"),
                "summary": r.get("scoring_text") or "",
            }
            for r in results
        ]

        # Key verified excerpts from citations
        citation_extracts = [
            {"title": c.get("title", ""), "extract": c.get("extract", ""), "score": c.get("score", 0.0)}
            for c in citations
        ]

        # Claims that were NOT supported — the gaps vector+CPG should resolve
        unsupported_claims = [
            c.get("claim", "")
            for c in verification.get("claim_details", [])
            if c.get("verdict") != "supported"
        ]

        return {
            "partial_response":      parsed.get("response") or parsed.get("answer") or "",
            "confidence_score":      parsed.get("confidence_score", 0.0),
            "relevant_files":        relevant_files,
            "node_summaries":        node_summaries,
            "citation_extracts":     citation_extracts,
            "uncovered_topics":      validation.get("uncovered_topics", []),
            "unsupported_claims":    unsupported_claims,
            "hallucinated_entities": entity_grounding.get("hallucinated_entities", []),
            "faithfulness_score":    validation.get("faithfulness_score"),
            "coverage_score":        validation.get("coverage_score"),
            "failure_reason":        reason,
            "result_count":          len(results),
        }

    # ------------------------------------------------------------------
    # Query enhancement  (always runs after pageindex_retrieval)
    # ------------------------------------------------------------------

    async def enhance_query(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Optionally reformulate the user query using PageIndex learnings,
        then fan out to the configured downstream retrievers.

        Rules:
        • 'and' combinations (PAGEINDEX_AND_GRAPH, PAGEINDEX_AND_VECTOR):
            Never reformulate.  Always forward original user_query.
        • '->' combinations (PAGEINDEX_VECTOR_GRAPH, PAGEINDEX_VECTOR, PAGEINDEX_GRAPH):
            Reformulate ONLY when pageindex_learnings contains non-empty
            uncovered_topics or unsupported_claims.
            If both are empty (pageindex had no answer or was confidently wrong),
            forward the original user_query unchanged.
        """
        combination  = state.retriever_combination
        learnings    = state.pageindex_learnings
        user_query   = state.user_query

        _AND_COMBOS = {
            RetrieverCombination.PAGEINDEX_AND_GRAPH,
            RetrieverCombination.PAGEINDEX_AND_VECTOR,
        }

        if combination in _AND_COMBOS:
            logger.info(
                f"🔀 Node: enhance_query — parallel mode ({combination}), "
                "no reformulation, forwarding original query"
            )
            return {"enhanced_query": None}

        # '->' combination — check for reformulation signals
        uncovered   = learnings.get("uncovered_topics", [])
        unsupported = learnings.get("unsupported_claims", [])

        if not uncovered and not unsupported:
            logger.info(
                "🔀 Node: enhance_query — no uncovered_topics or unsupported_claims "
                "from PageIndex, forwarding original query to downstream retrievers"
            )
            return {"enhanced_query": None}

        # Build LLM prompt for reformulation
        uncovered_str   = "\n".join(f"  - {t}" for t in uncovered)   if uncovered   else "  (none)"
        unsupported_str = "\n".join(f"  - {c}" for c in unsupported) if unsupported else "  (none)"
        partial_response = learnings.get("partial_response", "").strip()

        reformulation_prompt = f"""You are a query reformulation assistant for a code retrieval system.

A first-pass retrieval (PageIndex) already answered part of the user's question but left some gaps.
Your job is to write a focused, concise follow-up query that targets ONLY the gaps — do not ask
for information that was already answered.

## Original user query
{user_query}

## What PageIndex already answered (do NOT re-ask for this)
{partial_response if partial_response else "(no prior answer)"}

## Gaps to fill
Uncovered topics (topics the answer missed):
{uncovered_str}

Unsupported claims (claims made but not backed by evidence):
{unsupported_str}

## Instructions
- Write a single, self-contained query that a code retrieval system can execute directly.
- Target only the gaps listed above.
- Be specific — reference exact class names, method names, or concepts from the gaps.
- Do NOT include explanations, preamble, or markdown — output the query text only.
"""

        llm_service = state.llm_service
        try:
            result = await llm_service.generate_response(
                reformulation_prompt,
                json_mode=False,
                use_cache=False,
                max_tokens=512,
                temperature=0.2,
            )
            if result and not result.error and result.content.strip():
                reformulated = result.content.strip()
                logger.info(
                    f"✏️  Node: enhance_query — LLM reformulated query "
                    f"({len(uncovered)} uncovered topics, {len(unsupported)} unsupported claims)"
                )
                logger.debug(f"   Reformulated: {reformulated[:200]}")
                return {"enhanced_query": reformulated}
            else:
                logger.warning(f"⚠️  enhance_query LLM call failed: {result.error if result else 'no result'} — using original query")
        except Exception as e:
            logger.warning(f"⚠️  enhance_query LLM exception: {e} — using original query")

        return {"enhanced_query": None}

    # ------------------------------------------------------------------
    # Vector retrieval
    # ------------------------------------------------------------------

    async def vector_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute vector retrieval using genpod-semantic-rag CLI.

        Skipped (returns empty result) when the combination does not include
        vector: PAGEINDEX_GRAPH or PAGEINDEX_AND_GRAPH.

        Uses enhanced_query when set (reformulated by enhance_query node),
        otherwise falls back to the original user_query.
        """
        combination = state.retriever_combination
        _SKIP_COMBOS = {
            RetrieverCombination.PAGEINDEX_GRAPH,
            RetrieverCombination.PAGEINDEX_AND_GRAPH,
        }
        if combination in _SKIP_COMBOS:
            logger.info(f"⏭️  Node: vector_retrieval — skipped (combination={combination})")
            return {
                "vector_result": RetrieverResult(
                    retriever_type="vector",
                    status=RetrievalStatus.SKIPPED,
                    raw_results=[],
                    processed_results=[],
                    error="skipped — not part of selected retriever combination",
                    metadata={},
                    execution_time=0.0,
                )
            }

        logger.info("🔍 Node: vector_retrieval")

        try:
            user_query = state.enhanced_query or state.user_query
            intent_analysis = state.intent_analysis

            # Extract vector config from execution metadata
            config = state.execution_metadata.get("config", {})
            vector_config = config.get("vector_config", {})

            collection_name = vector_config.get("collection_name", "helloworldapp-benchmarking")
            vector_db = vector_config.get("vector_db", "qdrant")
            config_path = vector_config.get("config_path")
            max_results = vector_config.get("max_results", 5)
            enable_reasoning = vector_config.get("enable_reasoning", True)
            max_branches = vector_config.get("max_branches", 2)

            # Build CLI command for genpod-semantic-rag (following query_vector_only pattern)
            cli_command = [
                "genpod-semantic-rag", 
                "--config", config_path, 
                "query", user_query,
                "--collection-name", collection_name,
                "--vector-db", vector_db,
                "--max-results", str(max_results),
                "--output-format", "json"
            ]

            # Add reasoning flags if enabled
            if enable_reasoning:
                cli_command.append("--reasoning")
                cli_command.extend(["--max-branches", str(max_branches)])

            # Execute vector retrieval
            logger.info(f"⚡ Executing vector search: {' '.join(cli_command)}")
            start_time = asyncio.get_event_loop().time()

            # Use a temp file for stderr instead of a pipe to prevent grandchild
            # processes (e.g. Claude SDK spawned by genpod-semantic-rag) from
            # inheriting the pipe and keeping it open indefinitely.
            with tempfile.NamedTemporaryFile(mode='w', suffix='.stderr', delete=False) as _stderr_f:
                _stderr_path = _stderr_f.name
                cli_result = subprocess.run(
                    cli_command,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=_stderr_f,
                    check=False,
                    cwd=os.getcwd()
                )
            with open(_stderr_path) as _f:
                cli_result.stderr = _f.read()
            os.unlink(_stderr_path)

            execution_time = asyncio.get_event_loop().time() - start_time

            if cli_result.returncode == 0:
                try:
                    parsed_results = json.loads(cli_result.stdout)
                    raw_results = parsed_results.get("results", [])
                    ai_response = parsed_results.get("response", "")

                    logger.info(f"✅ Vector retrieval successful: {len(raw_results)} results")
                    # logger.info(f"📝 Vector CLI response body: {cli_result.stdout}")
                    logger.info(f"🤖 Vector AI response: {ai_response}")

                    # Extract reasoning metadata if available
                    reasoning_metadata = {}
                    if enable_reasoning:
                        reasoning_metadata = {
                            "reasoning_used": parsed_results.get("reasoning_used", False),
                            "reasoning_metrics": parsed_results.get("reasoning_metrics"),
                            "reasoning_trace": parsed_results.get("reasoning_trace")
                        }
                        if reasoning_metadata.get("reasoning_used"):
                            logger.info("🧠 Reasoning was used for this query")

                    vector_result = RetrieverResult(
                        retriever_type="vector",
                        status=RetrievalStatus.SUCCESS,
                        raw_results=raw_results,
                        processed_results=raw_results,  # Vector results are already processed
                        response_text=ai_response,
                        metadata={
                            "query": user_query,
                            "results_count": len(raw_results),
                            "total_results": parsed_results.get("total_results", len(raw_results)),
                            "processing_time": parsed_results.get("processing_time", execution_time),
                            "confidence_score": parsed_results.get("confidence_score"),
                            "has_diagram": parsed_results.get("has_diagram", False),
                            **reasoning_metadata
                        },
                        execution_time=execution_time
                    )

                    return {"vector_result": vector_result}
                    
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Vector results parsing failed: {e}")
                    vector_result = RetrieverResult(
                        retriever_type="vector",
                        status=RetrievalStatus.FAILED,
                        raw_results=[],
                        processed_results=[],
                        error=f"JSON parsing failed: {e}",
                        metadata={},
                        execution_time=execution_time
                    )
                    return {"vector_result": vector_result}
            else:
                logger.error(f"❌ Vector CLI failed: {cli_result.stderr}")
                vector_result = RetrieverResult(
                    retriever_type="vector",
                    status=RetrievalStatus.FAILED,
                    raw_results=[],
                    processed_results=[],
                    error=cli_result.stderr,
                    metadata={},
                    execution_time=execution_time
                )
                return {"vector_result": vector_result}
                
        except Exception as e:
            logger.error(f"❌ Vector retrieval failed: {e}")
            vector_result = RetrieverResult(
                retriever_type="vector",
                status=RetrievalStatus.FAILED,
                raw_results=[],
                processed_results=[],
                error=str(e),
                metadata={},
                execution_time=0.0
            )
            
            return {
                "vector_result": vector_result,
                "error_log": state.error_log + [f"Vector retrieval error: {str(e)}"]
            }
        
    # DEPRECATED - use Multi-Agent CoT CPG retrieval instead
    # async def cpg_retrieval(self, state: HybridState) -> Dict[str, Any]:
    #     """
    #     Node: Execute CPG retrieval using the existing adaptive CPG workflow.

    #     Integrates with the CPG workflow for structural code analysis.
    #     """
    #     logger.info("🔍 Node: cpg_retrieval")

    #     try:
    #         user_query = state.user_query

    #         # Extract max_agent_iterations from config (passed from MCP tool)
    #         config = state.execution_metadata.get("config", {})
    #         cpg_config = config.get("cpg_config", {})
    #         max_iterations = cpg_config.get("max_agent_iterations", 10)  # Default to 10 if not specified

    #         logger.info(f"⚡ Executing CPG agent workflow for: {user_query}")
    #         logger.info(f"🔢 Max iterations per approach: {max_iterations}")
    #         start_time = asyncio.get_event_loop().time()

    #         # Use the same approach as query_cpg_rag MCP tool
    #         from src.core.adaptive_cpg_agent_workflow import execute_adaptive_cpg_workflow

    #         cpg_result = await execute_adaptive_cpg_workflow(
    #             user_query=user_query,
    #             project_name="HelloWorldApp",
    #             neo4j_config="/opt/genpod/neo4j_config.json",
    #             project_path="/opt/HelloWorldApp/",
    #             mappings_path="/opt/genpod/genpod-graph-indexer/project_analyzer/parsing_utils/mappings.yaml",
    #             queries_path="/opt/genpod/genpod-graph-indexer/project_analyzer/final_queries",
    #             max_iterations=max_iterations  # Use config value instead of hardcoded 10
    #         )

    #         execution_time = asyncio.get_event_loop().time() - start_time

    #         if cpg_result and cpg_result.get("status") == "success":
    #             raw_results = cpg_result.get("raw_results", [])

    #             # Extract AI response - CPG workflow returns response as a string
    #             response_text = cpg_result.get("response", "")
                
    #             logger.info(f"✅ CPG retrieval successful: {len(raw_results)} results")
    #             # logger.info(f"📝 CPG workflow response body: {json.dumps(cpg_result, indent=2)}")
    #             logger.info(f"🤖 CPG AI response: {response_text}")
                
    #             cpg_retriever_result = RetrieverResult(
    #                 retriever_type="cpg",
    #                 status=RetrievalStatus.SUCCESS,
    #                 raw_results=raw_results,
    #                 processed_results=raw_results,
    #                 response_text=response_text,
    #                 metadata={
    #                     "agent_metadata": cpg_result.get("agent_metadata", {}),
    #                     "approach_statuses": cpg_result.get("approach_statuses", {}),
    #                     "approach_count": len(cpg_result.get("approach_statuses", {})),
    #                     "results_count": len(raw_results),
    #                     "iterations_used": cpg_result.get("iterations_used", 0),
    #                     "total_queries_executed": len(cpg_result.get("query_history", [])),
    #                     "tokens_used": cpg_result.get("total_tokens_used", 0),
    #                     "total_input_tokens": cpg_result.get("total_input_tokens", 0),
    #                     "total_output_tokens": cpg_result.get("total_output_tokens", 0),
    #                     "cost_usd": cpg_result.get("total_estimated_cost_usd", 0.0)
    #                 },
    #                 execution_time=execution_time
    #             )
    #             return {"cpg_result": cpg_retriever_result}
    #         else:
    #             error_msg = cpg_result.get("error", "CPG workflow failed") if cpg_result else "No CPG result"
    #             logger.error(f"❌ CPG workflow failed: {error_msg}")
                
    #             cpg_retriever_result = RetrieverResult(
    #                 retriever_type="cpg",
    #                 status=RetrievalStatus.FAILED,
    #                 raw_results=[],
    #                 processed_results=[],
    #                 error=error_msg,
    #                 metadata={},
    #                 execution_time=execution_time
    #             )
    #             return {"cpg_result": cpg_retriever_result}
                
    #     except Exception as e:
    #         logger.error(f"❌ CPG retrieval failed: {e}")
    #         cpg_retriever_result = RetrieverResult(
    #             retriever_type="cpg",
    #             status=RetrievalStatus.FAILED,
    #             raw_results=[],
    #             processed_results=[],
    #             error=str(e),
    #             metadata={},
    #             execution_time=0.0
    #         )
            
    #         return {
    #             "cpg_result": cpg_retriever_result,
    #             "error_log": state.error_log + [f"CPG retrieval error: {str(e)}"]
    #         }

    async def cpg_retrieval(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Execute CPG retrieval using the Multi-Agent CoT system (graph_rag).

        Skipped (returns empty result) when the combination does not include
        CPG: PAGEINDEX_VECTOR or PAGEINDEX_AND_VECTOR.

        Uses enhanced_query when set (reformulated by enhance_query node),
        otherwise falls back to the original user_query.
        For 'and' combinations enhanced_query is always None, so original
        user_query is always used.
        """
        combination = state.retriever_combination
        _SKIP_COMBOS = {
            RetrieverCombination.PAGEINDEX_VECTOR,
            RetrieverCombination.PAGEINDEX_AND_VECTOR,
        }
        if combination in _SKIP_COMBOS:
            logger.info(f"⏭️  Node: cpg_retrieval — skipped (combination={combination})")
            return {
                "cpg_result": RetrieverResult(
                    retriever_type="cpg",
                    status=RetrievalStatus.SKIPPED,
                    raw_results=[],
                    processed_results=[],
                    error="skipped — not part of selected retriever combination",
                    metadata={},
                    execution_time=0.0,
                )
            }

        logger.info("🔍 Node: cpg_retrieval (Multi-Agent CoT)")

        system = None  # Track for cleanup in finally block
        try:
            user_query = state.enhanced_query or state.user_query

            # Extract configuration from state
            config = state.execution_metadata.get("config", {})
            cpg_config = config.get("cpg_config", {})
            max_cot_iterations = cpg_config.get("max_agent_iterations", 15)
            max_verifier_iterations = cpg_config.get("max_verifier_iterations", 10)
            neo4j_config = cpg_config.get("config_path", NEO4J_CONFIG)
            schema_path = cpg_config.get("schema_path", SCHEMA_PATH)
            llm_model = cpg_config.get("llm_model", "gpt-4o")
            parallel_agents = cpg_config.get("parallel_agents", True)
            enable_verification = cpg_config.get("enable_verification", True)
            enable_entity_resolution = cpg_config.get("enable_entity_resolution", True)
            # 4-Agent Team configuration
            use_4_agent_team = cpg_config.get("use_4_agent_team", True)
            four_agent_max_iterations = cpg_config.get("four_agent_max_iterations", 3)

            workflow_type = "4-Agent Team" if use_4_agent_team else "Multi-Agent CoT"
            logger.info(f"⚡ Executing {workflow_type} for: {user_query}")
            logger.info(f"🔢 Max iterations: {max_cot_iterations}, parallel: {parallel_agents}, 4-agent: {use_4_agent_team}")
            start_time = asyncio.get_event_loop().time()

            # Import and use the new graph_rag Multi-Agent system
            from src.core.graph_rag import MultiAgentCoT, SystemConfig

            # Create configuration
            system_config = SystemConfig(
                mcp_config_path=neo4j_config,
                yaml_schema_path=schema_path,
                llm_model=llm_model,
                max_cot_iterations=max_cot_iterations,
                max_verifier_iterations=max_verifier_iterations,
                parallel_cot_agents=parallel_agents,
                verification_enabled=enable_verification,
                entity_resolution_enabled=enable_entity_resolution,
                # 4-Agent Team configuration
                use_4_agent_team=use_4_agent_team,
                four_agent_max_iterations=four_agent_max_iterations,
            )

            # Initialize and run the multi-agent system
            system = MultiAgentCoT(system_config, enable_observer=False)
            await system.initialize()

            # Execute the query
            response = await system.run(user_query)

            # Extract execution traces for debugging/analysis (4-agent workflow)
            execution_traces = system.last_execution_traces if use_4_agent_team else []

            execution_time = asyncio.get_event_loop().time() - start_time

            # Convert citations to raw_results format for compatibility
            raw_results = []
            for citation in response.citations:
                raw_results.append({
                    "claim": citation.claim,
                    "source_file": citation.source_file,
                    "source_line": citation.source_line,
                    "entity_name": citation.entity_name,
                    "entity_type": citation.entity_type,
                    "evidence": citation.evidence,
                    "verification_status": citation.verification_status.value if citation.verification_status else None,
                    "cot_agent_id": citation.cot_agent_id,
                    "confidence": citation.confidence.value if citation.confidence else None
                })

            # Build token usage dict
            token_usage = {}
            if response.token_usage:
                token_usage = {
                    "total_tokens": response.token_usage.total_tokens,
                    "total_prompt_tokens": response.token_usage.total_prompt_tokens,
                    "total_completion_tokens": response.token_usage.total_completion_tokens,
                    "call_count": response.token_usage.call_count
                }

            logger.info(f"✅ CPG {workflow_type} retrieval successful: {len(raw_results)} citations ({response.verified_count} verified)")
            logger.info(f"🤖 CPG AI response: {response.answer}")

            cpg_retriever_result = RetrieverResult(
                retriever_type="cpg",
                status=RetrievalStatus.SUCCESS,
                raw_results=raw_results,
                processed_results=raw_results,
                response_text=response.answer,
                metadata={
                    "workflow_type": "4_agent_team" if use_4_agent_team else "multi_agent_tot_cot",
                    "use_4_agent_team": use_4_agent_team,
                    "four_agent_max_iterations": four_agent_max_iterations,
                    "confidence": response.confidence.value,
                    "verified_count": response.verified_count,
                    "unverified_count": response.unverified_count,
                    "sub_queries_count": response.sub_queries_count,
                    "llm_calls_count": response.llm_calls_count,
                    "results_count": len(raw_results),
                    "tokens_used": token_usage.get("total_tokens", 0),
                    "total_input_tokens": token_usage.get("total_prompt_tokens", 0),
                    "total_output_tokens": token_usage.get("total_completion_tokens", 0),
                    "execution_time_ms": response.execution_time_ms,
                    # Execution traces with Cypher queries for debugging/analysis
                    "execution_traces": execution_traces
                },
                execution_time=execution_time
            )
            return {"cpg_result": cpg_retriever_result}

        except Exception as e:
            logger.error(f"❌ CPG Multi-Agent retrieval failed: {e}")
            cpg_retriever_result = RetrieverResult(
                retriever_type="cpg",
                status=RetrievalStatus.FAILED,
                raw_results=[],
                processed_results=[],
                error=str(e),
                metadata={},
                execution_time=0.0
            )

            return {
                "cpg_result": cpg_retriever_result,
                "error_log": state.error_log + [f"CPG Multi-Agent retrieval error: {str(e)}"]
            }
        finally:
            # Gracefully shutdown the multi-agent system to prevent cancel scope errors
            if system:
                try:
                    await system.shutdown()
                except Exception:
                    pass  # Suppress cleanup errors
    
    async def combine_results(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Combine and batch raw results from both retrievers.
        
        Implements intelligent batching for context window management.
        """
        logger.info("🔗 Node: combine_results")

        try:
            combined_results = []
            # citation_lookup: deduped map of citation_id → original raw object.
            # Built here so synthesis nodes can resolve IDs back to raw objects
            # without re-scanning all results. Each raw object is stored once,
            # keyed by its stable ID, preventing duplicate citations in the
            # final response payload regardless of how many retrievers returned it.
            citation_lookup: Dict[str, Any] = {}
            seen_ids: set = set()

            def _add_results(raw_results: List[Any], source: str) -> int:
                """Tag, deduplicate, and append raw results. Returns count added."""
                added = 0
                for idx, result in enumerate(raw_results):
                    item = dict(result) if isinstance(result, dict) else {"content": result}
                    cid = (
                        item.get("node_id") or
                        item.get("id") or
                        item.get("chunk_id") or
                        f"{source}:{idx}"
                    )
                    # Store original (untagged) object in citation_lookup once
                    if cid not in seen_ids:
                        citation_lookup[cid] = dict(result) if isinstance(result, dict) else {"content": result}
                        seen_ids.add(cid)

                    # Always include in combined_results for batching/context,
                    # but tag with source so prompt builders can filter by retriever
                    item["_source"] = source
                    item["_citation_id"] = cid
                    combined_results.append(item)
                    added += 1
                return added

            # PageIndex results — always include when available (sufficient or partial)
            if state.pageindex_result and state.pageindex_result.raw_results:
                source_tag = "pageindex" if state.pageindex_result.succeeded else "pageindex_partial"
                n = _add_results(state.pageindex_result.raw_results, source_tag)
                logger.info(f"📊 Added {n} pageindex results (tag={source_tag})")

            # Vector results
            if state.vector_result and state.vector_result.succeeded:
                n = _add_results(state.vector_result.raw_results, "vector")
                # NOTE: _retriever_metadata removed to prevent data explosion (was 278KB per item)
                # Metadata is available at state.vector_result.metadata for synthesis
                logger.info(f"📊 Added {n} vector results")

            # CPG results
            if state.cpg_result and state.cpg_result.succeeded:
                n = _add_results(state.cpg_result.raw_results, "cpg")
                # NOTE: _retriever_metadata removed to prevent data explosion
                # Metadata is available at state.cpg_result.metadata for synthesis
                logger.info(f"📊 Added {n} CPG results")

            logger.info(f"📊 citation_lookup contains {len(citation_lookup)} unique citations across all retrievers")
            
            # Batch results for context management
            batched_results = self._create_intelligent_batches(
                combined_results, 
                state.batch_size,
                state.max_context_limit
            )
            
            context_size = self._estimate_context_size(combined_results)
            
            logger.info(f"✅ Combined {len(combined_results)} total results into {len(batched_results)} batches")
            logger.info(f"📊 Estimated context size: {context_size} characters")
            
            return {
                "combined_raw_results": combined_results,
                "batched_results": batched_results,
                "context_size": context_size,
                "citation_lookup": citation_lookup,
            }

        except Exception as e:
            logger.error(f"❌ Result combination failed: {e}")

            # Fallback
            return {
                "combined_raw_results": [],
                "batched_results": [],
                "context_size": 0,
                "citation_lookup": {},
                "error_log": state.error_log + [f"Result combination error: {str(e)}"]
            }
    
    async def synthesize_response(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Synthesize final response using chain-of-thought reasoning.
        
        Implements sophisticated synthesis with cross-validation between retrievers.
        """
        logger.info("🧠 Node: synthesize_response") 
        
        try:
            synthesis_strategy = self._determine_synthesis_strategy(state)
            logger.info(f"📝 Using synthesis strategy: {synthesis_strategy}")
            
            # Execute synthesis based on strategy
            if synthesis_strategy == SynthesisStrategy.PAGEINDEX_PRIMARY:
                synthesis_result = await self._synthesize_pageindex_primary(state)
            elif synthesis_strategy == SynthesisStrategy.NO_RESULTS:
                synthesis_result = await self._synthesize_no_results(state)
            elif _USE_MULTI_SOURCE_SYNTHESIS:
                # Issue #1: all active retrievers are equal participants.
                # Map-reduce: extract claims per retriever → reconcile → synthesise.
                synthesis_result = await self._synthesize_multi_source(state, synthesis_strategy)
            elif synthesis_strategy in [SynthesisStrategy.FALLBACK_VECTOR, SynthesisStrategy.FALLBACK_CPG]:
                # Legacy path — only reachable when _USE_MULTI_SOURCE_SYNTHESIS=False
                synthesis_result = await self._synthesize_single_source(state, synthesis_strategy)
            else:
                # Legacy path — only reachable when _USE_MULTI_SOURCE_SYNTHESIS=False
                synthesis_result = await self._synthesize_hybrid_with_cross_validation(state, synthesis_strategy)
            
            logger.info(f"✅ Synthesis completed: {synthesis_result.status} (confidence: {synthesis_result.confidence:.2f})")
            return {"synthesis_result": synthesis_result}
            
        except Exception as e:
            logger.error(f"❌ Synthesis failed: {e}")
            
            # Fallback synthesis
            fallback_synthesis = SynthesisResult(
                strategy_used=SynthesisStrategy.NO_RESULTS,
                answer="Analysis failed due to synthesis error.",
                details=f"Synthesis error: {str(e)}",
                confidence=0.1,
                status="error",
                suggestions=["Please try rephrasing your query"],
                cross_validation=CrossValidationResult(
                    vector_validates_cpg=False,
                    cpg_validates_vector=False,
                    conflicts_found=[],
                    consensus_points=[],
                    confidence_score=0.0,
                    validation_details={}
                ),
                evidence={},
                batch_metadata={}
            )
            
            return {
                "synthesis_result": fallback_synthesis,
                "error_log": state.error_log + [f"Synthesis error: {str(e)}"]
            }
    
    async def critic_validation(self, state: HybridState) -> Dict[str, Any]:
        """
        Node: Validate synthesis output for hallucination, faithfulness, and accuracy.
        
        Uses chain-of-thought reasoning to grade evidence and validate claims.
        """
        logger.info("🔍 Node: critic_validation")
        
        try:
            llm_service = state.llm_service
            synthesis_result = state.synthesis_result
            
            if not synthesis_result:
                logger.warning("⚠️ No synthesis result to validate")
                return state
            
            # Chain-of-thought validation prompt
            validation_prompt = f"""You are an expert critic for hybrid code analysis systems. 
Validate this synthesis output for hallucination, faithfulness, and accuracy using chain-of-thought reasoning.

**SYNTHESIS TO VALIDATE**:
Answer: {synthesis_result.answer}
Details: {synthesis_result.details}
Confidence: {synthesis_result.confidence}
Strategy: {synthesis_result.strategy_used}

**AVAILABLE EVIDENCE**:
Vector Evidence: {json.dumps(state.vector_result.raw_results if state.vector_result and state.vector_result.succeeded else [], indent=2)}
CPG Evidence: {json.dumps(state.cpg_result.raw_results if state.cpg_result and state.cpg_result.succeeded else [], indent=2)}
PageIndex Evidence: {json.dumps(state.pageindex_result.raw_results if state.pageindex_result and state.pageindex_result.raw_results else [], indent=2)}

**CHAIN OF THOUGHT VALIDATION**:

**Step 1: Hallucination Detection**
Check if the synthesis makes claims not supported by evidence:
- Are all facts mentioned in the answer supported by the evidence?
- Are there any invented details, functions, or files not in the evidence?
- Rate hallucination risk (0.0 = no hallucination, 1.0 = severe hallucination)

**Step 2: Faithfulness Assessment** 
Check if the synthesis stays faithful to the source evidence:
- Does the answer accurately represent what was found in the evidence?
- Are quotes and references accurate?
- Rate faithfulness (0.0 = unfaithful, 1.0 = completely faithful)

**Step 3: Accuracy Evaluation**
Check the accuracy of reasoning and conclusions:
- Are the logical connections sound?
- Are the conclusions supported by the evidence?
- Rate accuracy (0.0 = inaccurate, 1.0 = highly accurate)

**Step 4: Evidence Quality Grading**
Grade the quality and relevance of evidence used:
- Vector evidence quality and relevance
- CPG evidence quality and relevance  
- Overall evidence sufficiency

**Step 5: Final Decision**
Based on the analysis above:
- ACCEPT: High quality, faithful, accurate synthesis
- RETRY: Issues found that can be fixed
- REJECT: Severe problems, synthesis is unreliable

**OUTPUT FORMAT**:
Return ONLY a valid JSON object:
{{
    "decision": "accept|retry|reject",
    "overall_score": <float 0.0-1.0>,
    "hallucination_score": <float 0.0-1.0>,
    "faithfulness_score": <float 0.0-1.0>,
    "accuracy_score": <float 0.0-1.0>,
    "validation_issues": ["issue1", "issue2"],
    "reasoning": "Detailed step-by-step validation reasoning",
    "improvement_suggestions": ["suggestion1", "suggestion2"],
    "evidence_grading": {{
        "vector_quality": <float 0.0-1.0>,
        "cpg_quality": <float 0.0-1.0>,
        "overall_sufficiency": <float 0.0-1.0>
    }}
}}"""
            
            # Generate critic validation with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=validation_prompt,
                pydantic_model=CriticValidationRawResponse,
                max_tokens=16000,
                temperature=0.1,  # Low temperature for precise validation and scoring
                max_retries=3
            )
            
            if raw_response:
                critic_validation = CriticValidation(
                    decision=raw_response.decision,
                    overall_score=raw_response.overall_score,
                    hallucination_score=raw_response.hallucination_score,
                    faithfulness_score=raw_response.faithfulness_score,
                    accuracy_score=raw_response.accuracy_score,
                    validation_issues=raw_response.validation_issues,
                    reasoning=raw_response.reasoning,
                    improvement_suggestions=raw_response.improvement_suggestions,
                    evidence_grading=raw_response.evidence_grading
                )
                
                logger.info(f"✅ Critic validation: {critic_validation.decision} (score: {critic_validation.overall_score:.2f})")
                
                # If retry needed and score is low, attempt to improve synthesis
                if (critic_validation.decision == "retry" and 
                    critic_validation.overall_score < 0.7):
                    logger.info("🔄 Attempting to improve synthesis based on critic feedback")
                    improved_synthesis = await self._improve_synthesis_with_critic_feedback(
                        state, critic_validation
                    )
                    if improved_synthesis:
                        logger.info("✅ Synthesis improved using critic feedback")
                        return {
                            "critic_validation": critic_validation,
                            "synthesis_result": improved_synthesis
                        }
                
                return {"critic_validation": critic_validation}
            
            logger.error(f"❌ Critic validation failed after retries: {error}")
                    
            # Fallback validation  
            logger.warning("⚠️ Using fallback critic validation")
            fallback_validation = CriticValidation(
                decision="accept",
                overall_score=0.6,
                hallucination_score=0.7,
                faithfulness_score=0.7,
                accuracy_score=0.6,
                validation_issues=[],
                reasoning="Fallback validation due to critic failure",
                improvement_suggestions=[],
                evidence_grading={}
            )
            return {"critic_validation": fallback_validation}
                
        except Exception as e:
            logger.error(f"❌ Critic validation failed: {e}")
            
            # Fallback
            error_validation = CriticValidation(
                decision="accept",
                overall_score=0.5,
                hallucination_score=0.5,
                faithfulness_score=0.5,
                accuracy_score=0.5,
                validation_issues=[f"Validation error: {str(e)}"],
                reasoning="Error fallback validation",
                improvement_suggestions=[],
                evidence_grading={}
            )
            
            return {
                "critic_validation": error_validation,
                "error_log": state.error_log + [f"Critic validation error: {str(e)}"]
            }
    
    
    def _create_intelligent_batches(
        self, 
        results: List[Dict[str, Any]], 
        batch_size: int,
        max_context_limit: int
    ) -> List[List[Dict[str, Any]]]:
        """Create intelligent batches considering context size limits"""
        if not results:
            return []
        
        batches = []
        current_batch = []
        current_size = 0
        
        for result in results:
            result_size = len(str(result))
            
            # If single result exceeds limit, truncate it
            if result_size > max_context_limit:
                result = self._truncate_result(result, max_context_limit // 2)
                result_size = len(str(result))
            
            # If adding this result would exceed context limit or batch size, start new batch
            if ((current_size + result_size > max_context_limit) or 
                (len(current_batch) >= batch_size)) and current_batch:
                batches.append(current_batch)
                current_batch = [result]
                current_size = result_size
            else:
                current_batch.append(result)
                current_size += result_size
        
        # Add final batch if not empty
        if current_batch:
            batches.append(current_batch)
        
        return batches
    
    def _truncate_result(self, result: Dict[str, Any], max_size: int) -> Dict[str, Any]:
        """Truncate a result to fit within size limits"""
        result_str = str(result)
        if len(result_str) <= max_size:
            return result
        
        # Try to keep structured data
        if isinstance(result, dict):
            truncated = {}
            current_size = 0
            
            # Prioritize certain keys
            priority_keys = ['name', 'type', 'file_path', 'content', 'body']
            
            for key in priority_keys:
                if key in result and current_size < max_size * 0.8:
                    value = result[key]
                    value_str = str(value)
                    if len(value_str) > max_size // 4:
                        value_str = value_str[:max_size // 4] + "...[truncated]"
                    truncated[key] = value_str
                    current_size += len(str(value_str))
            
            # Add other keys if space allows
            for key, value in result.items():
                if key not in priority_keys and current_size < max_size:
                    value_str = str(value)
                    if current_size + len(value_str) <= max_size:
                        truncated[key] = value_str
                        current_size += len(value_str)
                    else:
                        break
            
            truncated["_truncated"] = True
            return truncated
        
        # Fallback: string truncation
        return {"content": result_str[:max_size] + "...[truncated]", "_truncated": True}
    
    def _estimate_context_size(self, results: List[Dict[str, Any]]) -> int:
        """Estimate total context size for all results"""
        return sum(len(str(result)) for result in results)
    
    def _determine_synthesis_strategy(self, state: HybridState) -> SynthesisStrategy:
        """
        Determine synthesis strategy based on retriever_combination and what succeeded.

        PAGEINDEX_PRIMARY is only used when the combination is pageindex-only
        (no vector/CPG configured to run). For all '->' and 'and' combinations
        the downstream retrievers always ran, so their results must be included
        in synthesis regardless of pageindex sufficiency.
        """
        combination = state.retriever_combination

        _AND_COMBOS = {
            RetrieverCombination.PAGEINDEX_AND_GRAPH,
            RetrieverCombination.PAGEINDEX_AND_VECTOR,
        }
        _VECTOR_COMBOS = {
            RetrieverCombination.PAGEINDEX_VECTOR_GRAPH,
            RetrieverCombination.PAGEINDEX_VECTOR,
            RetrieverCombination.PAGEINDEX_AND_VECTOR,
        }
        _CPG_COMBOS = {
            RetrieverCombination.PAGEINDEX_VECTOR_GRAPH,
            RetrieverCombination.PAGEINDEX_GRAPH,
            RetrieverCombination.PAGEINDEX_AND_GRAPH,
        }

        vector_succeeded = state.vector_result and state.vector_result.succeeded
        cpg_succeeded    = state.cpg_result    and state.cpg_result.succeeded

        # For combinations that always run downstream retrievers, never use
        # PAGEINDEX_PRIMARY — always incorporate all available results.
        downstream_ran = combination in (_AND_COMBOS |
                                         {RetrieverCombination.PAGEINDEX_VECTOR_GRAPH,
                                          RetrieverCombination.PAGEINDEX_VECTOR,
                                          RetrieverCombination.PAGEINDEX_GRAPH})

        if not downstream_ran:
            # Pageindex is the only retriever — use its response directly
            if state.pageindex_result and state.pageindex_result.succeeded:
                return SynthesisStrategy.PAGEINDEX_PRIMARY
            return SynthesisStrategy.NO_RESULTS

        # Downstream retrievers were configured — use their results for synthesis
        if not vector_succeeded and not cpg_succeeded:
            # Downstream both failed/skipped — fall back to pageindex if available
            if state.pageindex_result and state.pageindex_result.succeeded:
                return SynthesisStrategy.PAGEINDEX_PRIMARY
            return SynthesisStrategy.NO_RESULTS

        pageindex_succeeded = state.pageindex_result and state.pageindex_result.succeeded

        if vector_succeeded and not cpg_succeeded:
            # FALLBACK_VECTOR only when pageindex also failed/was absent.
            # When pageindex succeeded alongside vector, both are full participants.
            if pageindex_succeeded:
                return SynthesisStrategy.VECTOR_PRIMARY
            return SynthesisStrategy.FALLBACK_VECTOR

        if cpg_succeeded and not vector_succeeded:
            # Same logic for CPG-only downstream path.
            if pageindex_succeeded:
                return SynthesisStrategy.CPG_PRIMARY
            return SynthesisStrategy.FALLBACK_CPG

        # Both vector and CPG succeeded — pick strategy by intent
        intent = state.intent_analysis.intent if state.intent_analysis else QueryIntent.UNKNOWN
        if intent in [QueryIntent.ARCHITECTURAL, QueryIntent.SEMANTIC]:
            return SynthesisStrategy.VECTOR_PRIMARY
        elif intent in [QueryIntent.DIRECT_LOOKUP, QueryIntent.QUANTITATIVE, QueryIntent.RELATIONAL]:
            return SynthesisStrategy.CPG_PRIMARY
        return SynthesisStrategy.HYBRID_CONSENSUS
    
    async def _synthesize_pageindex_primary(self, state: HybridState) -> SynthesisResult:
        """
        Synthesize directly from a sufficient PageIndex answer.

        PageIndex already performs internal Pass-2 verification and faithfulness
        validation, so we use its response_text directly rather than running an
        additional LLM synthesis call.  Verification scores from the CLI output
        are surfaced in cross_validation for the critic node to inspect.
        """
        pi = state.pageindex_result
        metadata = pi.metadata or {}
        verification = metadata.get("verification", {})
        validation   = metadata.get("validation", {})

        faithfulness = validation.get("faithfulness_score", 0.9)
        coverage     = validation.get("coverage_score", 0.9)
        confidence   = min((faithfulness + coverage) / 2.0, 1.0) if (faithfulness and coverage) else 0.85

        unsupported = verification.get("unsupported", 0)
        wrong       = verification.get("wrong", 0)
        claims_ok   = unsupported == 0 and wrong == 0

        return SynthesisResult(
            strategy_used=SynthesisStrategy.PAGEINDEX_PRIMARY,
            answer=pi.response_text or "",
            details=pi.response_text or "",
            confidence=confidence,
            status="found" if pi.raw_results else "partial",
            suggestions=[] if claims_ok else [
                f"{unsupported} unsupported claim(s) detected by PageIndex verification",
                f"{wrong} wrong claim(s) corrected by PageIndex verification",
            ],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False,
                cpg_validates_vector=False,
                conflicts_found=[],
                consensus_points=[
                    f"PageIndex retrieved {len(pi.raw_results)} node(s) with "
                    f"faithfulness={faithfulness:.0%}, coverage={coverage:.0%}"
                ],
                confidence_score=confidence,
                validation_details={
                    "source":         "pageindex_primary",
                    "verification":   verification,
                    "validation":     validation,
                    "citations":      metadata.get("citations", []),
                    "nodes_returned": metadata.get("nodes_returned", len(pi.raw_results)),
                },
            ),
            evidence={"pageindex": pi.raw_results},
            batch_metadata={
                "strategy":      "pageindex_primary",
                "nodes_returned": len(pi.raw_results),
                "mcts_iterations": metadata.get("mcts_iterations"),
            },
        )

    async def _synthesize_no_results(self, state: HybridState) -> SynthesisResult:
        """Synthesize response when no retrieval succeeded"""
        return SynthesisResult(
            strategy_used=SynthesisStrategy.NO_RESULTS,
            answer="No results found for your query.",
            details="Both vector and CPG retrievers were unable to find relevant information for your query. This could be due to the query being outside the scope of the codebase or issues with the retrieval systems.",
            confidence=0.1,
            status="not_found",
            suggestions=[
                "Try rephrasing your query with different keywords",
                "Check if the entities mentioned in your query exist in the codebase",
                "Try a more general or more specific version of your query"
            ],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False,
                cpg_validates_vector=False,
                conflicts_found=[],
                consensus_points=[],
                confidence_score=0.0,
                validation_details={"reason": "no_results"}
            ),
            evidence={},
            batch_metadata={"strategy": "no_results"}
        )
    
    # ------------------------------------------------------------------
    # Multi-source synthesis helpers (Issue #1)
    # ------------------------------------------------------------------

    def _get_retriever_citations(self, state: HybridState, retriever: str) -> List[Dict[str, Any]]:
        """Return raw results for a given retriever, each annotated with _citation_id."""
        source_tags = {
            "pageindex": {"pageindex", "pageindex_partial"},
            "vector":    {"vector"},
            "cpg":       {"cpg"},
        }
        tags = source_tags.get(retriever, {retriever})
        return [r for r in state.combined_raw_results if r.get("_source") in tags]

    async def _extract_retriever_claims(
        self,
        state: HybridState,
        retriever: str,
        response_text: str,
        citations: List[Dict[str, Any]],
    ) -> RetrieverSummary:
        """Stage 1 (Map): one focused LLM call per retriever.

        The LLM extracts structured claims and maps each claim to the IDs of
        the raw citations that support it.  It never paraphrases or copies
        citation text — only references citation IDs from the provided list.
        """
        if not response_text or not citations:
            return RetrieverSummary(retriever=retriever, claims=[], gaps=["No response or citations available"], overall_confidence=0.0)

        # Build a compact citation index for the prompt: id → short excerpt only
        citation_index = {}
        for c in citations:
            cid = c.get("_citation_id", c.get("node_id", c.get("id", "")))
            excerpt = (
                c.get("scoring_text") or
                c.get("md_content") or
                c.get("content") or
                str(c)
            )
            citation_index[cid] = str(excerpt)[:300]  # cap excerpt length

        citation_list_str = "\n".join(
            f'  - ID: "{cid}"\n    Excerpt: {excerpt}'
            for cid, excerpt in citation_index.items()
        )

        prompt = f"""You are extracting structured claims from a retriever's response for code analysis synthesis.

RETRIEVER: {retriever}

RETRIEVER RESPONSE:
{response_text}

AVAILABLE CITATIONS (each has an ID and a short excerpt):
{citation_list_str}

TASK:
1. Extract 3-7 key factual claims from the response.
2. For each claim, list which citation IDs support it (use ONLY IDs from the list above).
3. Do NOT paraphrase or copy citation text — only reference IDs.
4. Identify any topics the response was uncertain about or could not answer.

Return ONLY valid JSON:
{{
    "claims": [
        {{"text": "claim statement", "confidence": <0.0-1.0>, "citation_ids": ["id1", "id2"]}}
    ],
    "gaps": ["topic not covered or uncertain"],
    "overall_confidence": <0.0-1.0>
}}"""

        raw_response, error = await self._robust_llm_call_with_pydantic_validation(
            llm_service=state.llm_service,
            prompt=prompt,
            pydantic_model=ClaimExtractionRawResponse,
            max_tokens=2000,
            temperature=0.2,
            max_retries=2,
        )

        if raw_response:
            claims = [
                EvidenceClaim(
                    text=c.get("text", ""),
                    confidence=float(c.get("confidence", 0.5)),
                    citation_ids=[cid for cid in c.get("citation_ids", []) if cid in citation_index],
                )
                for c in raw_response.claims
                if c.get("text")
            ]
            return RetrieverSummary(
                retriever=retriever,
                claims=claims,
                gaps=raw_response.gaps,
                overall_confidence=raw_response.overall_confidence,
            )

        logger.warning(f"⚠️ Claim extraction failed for {retriever}: {error} — using empty summary")
        return RetrieverSummary(retriever=retriever, claims=[], gaps=[f"Extraction failed: {error}"], overall_confidence=0.3)

    async def _reconcile_claims(
        self,
        summaries: List[RetrieverSummary],
        llm_service: Any,
    ) -> ReconciliationRawResponse:
        """Stage 2 (Reconcile): cross-validate claim sets from all retrievers.

        Operates only on compressed claim texts — no raw evidence passed.
        """
        summary_blocks = []
        for s in summaries:
            claim_lines = "\n".join(
                f'    - [{c.confidence:.2f}] {c.text}  (cites: {c.citation_ids})'
                for c in s.claims
            ) or "    (no claims extracted)"
            gap_lines = ", ".join(s.gaps) or "none"
            summary_blocks.append(
                f"RETRIEVER: {s.retriever} (overall_confidence={s.overall_confidence:.2f})\n"
                f"  Claims:\n{claim_lines}\n"
                f"  Gaps: {gap_lines}"
            )

        prompt = f"""You are reconciling claims from multiple code analysis retrievers.

{chr(10).join(summary_blocks)}

TASK:
1. Identify claims that multiple retrievers AGREE on (consensus).
2. Identify claims that CONFLICT between retrievers — note which retrievers disagree.
3. Identify claims that are UNIQUE to a single retriever (potential novel insight or noise).

Return ONLY valid JSON:
{{
    "agreements": ["agreed claim 1", "agreed claim 2"],
    "conflicts": ["retriever_a says X but retriever_b says Y"],
    "unique_per_retriever": {{
        "pageindex": ["unique claim"],
        "vector": ["unique claim"],
        "cpg": ["unique claim"]
    }},
    "confidence_score": <0.0-1.0>
}}"""

        raw_response, error = await self._robust_llm_call_with_pydantic_validation(
            llm_service=llm_service,
            prompt=prompt,
            pydantic_model=ReconciliationRawResponse,
            max_tokens=2000,
            temperature=0.2,
            max_retries=2,
        )

        if raw_response:
            return raw_response

        logger.warning(f"⚠️ Reconciliation failed: {error} — using empty reconciliation")
        return ReconciliationRawResponse(
            agreements=[],
            conflicts=[],
            unique_per_retriever={s.retriever: [] for s in summaries},
            confidence_score=0.3,
        )

    def _resolve_citation_ids(
        self,
        summaries: List[RetrieverSummary],
        citation_lookup: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve all citation IDs referenced across summaries back to original raw objects.

        Deduplicates by citation ID — each raw object appears exactly once in the
        returned dict regardless of how many claims or retrievers reference it.
        Returns {citation_id: raw_object} preserving the original untagged object.
        """
        resolved: Dict[str, Any] = {}
        for summary in summaries:
            for claim in summary.claims:
                for cid in claim.citation_ids:
                    if cid not in resolved and cid in citation_lookup:
                        resolved[cid] = citation_lookup[cid]
        return resolved

    async def _synthesize_multi_source(
        self,
        state: HybridState,
        strategy: SynthesisStrategy,
    ) -> SynthesisResult:
        """Map-reduce synthesis treating all active retrievers as equal participants.

        Stage 1 (Map)     — extract structured claims per retriever (parallel LLM calls)
        Stage 2 (Reduce)  — reconcile claim sets across retrievers
        Stage 3 (Synthesise) — generate final answer from reconciled claims only
        """
        citation_lookup = state.citation_lookup or {}

        # ── Stage 1: extract claims from each active retriever ──────────────
        active = []
        if state.pageindex_result and state.pageindex_result.succeeded:
            active.append(("pageindex", state.pageindex_result.response_text or ""))
        if state.vector_result and state.vector_result.succeeded:
            active.append(("vector", state.vector_result.response_text or ""))
        if state.cpg_result and state.cpg_result.succeeded:
            active.append(("cpg", state.cpg_result.response_text or ""))

        if not active:
            return await self._synthesize_no_results(state)

        extraction_tasks = [
            self._extract_retriever_claims(
                state,
                retriever,
                response_text,
                self._get_retriever_citations(state, retriever),
            )
            for retriever, response_text in active
        ]
        summaries: List[RetrieverSummary] = await asyncio.gather(*extraction_tasks)
        logger.info(f"✅ Stage 1 complete — extracted claims from {len(summaries)} retriever(s): "
                    f"{[s.retriever for s in summaries]}")

        # ── Stage 2: reconcile claim sets ────────────────────────────────────
        reconciliation = await self._reconcile_claims(summaries, state.llm_service)
        logger.info(f"✅ Stage 2 complete — {len(reconciliation.agreements)} agreements, "
                    f"{len(reconciliation.conflicts)} conflicts")

        # ── Stage 3: synthesise from reconciled claims ───────────────────────
        synthesis_prompt = self._build_multi_source_synthesis_prompt(
            state, summaries, reconciliation, strategy
        )
        raw_response, error = await self._robust_llm_call_with_pydantic_validation(
            llm_service=state.llm_service,
            prompt=synthesis_prompt,
            pydantic_model=SynthesisRawResponse,
            max_tokens=16000,
            temperature=0.7,
            max_retries=3,
        )

        # ── Resolve citation IDs → original raw objects (deduped) ───────────
        resolved_evidence = self._resolve_citation_ids(summaries, citation_lookup)
        logger.info(f"📎 Resolved {len(resolved_evidence)} unique citation(s) across all retrievers")

        if raw_response:
            return SynthesisResult(
                strategy_used=strategy,
                answer=raw_response.answer,
                details=raw_response.details,
                confidence=raw_response.confidence,
                status=raw_response.status,
                suggestions=raw_response.suggestions,
                cross_validation=CrossValidationResult(
                    vector_validates_cpg=raw_response.cross_validation.get("vector_validates_cpg", False),
                    cpg_validates_vector=raw_response.cross_validation.get("cpg_validates_vector", False),
                    conflicts_found=reconciliation.conflicts,
                    consensus_points=reconciliation.agreements,
                    confidence_score=reconciliation.confidence_score,
                    validation_details={
                        "strategy": "multi_source_map_reduce",
                        "retrievers": [s.retriever for s in summaries],
                        "unique_per_retriever": reconciliation.unique_per_retriever,
                    },
                ),
                evidence={"citations": list(resolved_evidence.values())},
                batch_metadata={
                    **(raw_response.batch_metadata or {}),
                    "strategy_applied": str(strategy),
                    "retrievers_used": [s.retriever for s in summaries],
                    "unique_citations": len(resolved_evidence),
                },
            )

        logger.error(f"❌ Multi-source synthesis LLM call failed: {error}")
        # Graceful degradation — fall back to best available single-source response
        best = max(summaries, key=lambda s: s.overall_confidence)
        fallback_result = state.pageindex_result if best.retriever == "pageindex" else \
                          state.vector_result    if best.retriever == "vector"    else \
                          state.cpg_result
        return SynthesisResult(
            strategy_used=strategy,
            answer=fallback_result.response_text or "Synthesis failed.",
            details=f"Multi-source synthesis failed ({error}). Showing best single-source response from {best.retriever}.",
            confidence=0.4,
            status="partial",
            suggestions=["Multi-source synthesis failed — result may be incomplete"],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False, cpg_validates_vector=False,
                conflicts_found=[], consensus_points=[],
                confidence_score=0.3,
                validation_details={"fallback": True, "reason": error},
            ),
            evidence={"citations": list(resolved_evidence.values())},
            batch_metadata={"fallback": True, "reason": error},
        )

    def _build_multi_source_synthesis_prompt(
        self,
        state: HybridState,
        summaries: List[RetrieverSummary],
        reconciliation: ReconciliationRawResponse,
        strategy: SynthesisStrategy,
    ) -> str:
        """Build synthesis prompt from compressed claim sets only — no raw evidence."""
        summary_blocks = []
        for s in summaries:
            claim_lines = "\n".join(
                f"  - [{c.confidence:.2f}] {c.text}"
                for c in s.claims
            ) or "  (no claims extracted)"
            gap_lines = ", ".join(s.gaps) or "none"
            summary_blocks.append(
                f"### {s.retriever.upper()} (confidence={s.overall_confidence:.2f})\n"
                f"Claims:\n{claim_lines}\n"
                f"Gaps: {gap_lines}"
            )

        agreements_str = "\n".join(f"  ✓ {a}" for a in reconciliation.agreements) or "  (none identified)"
        conflicts_str  = "\n".join(f"  ✗ {c}" for c in reconciliation.conflicts)  or "  (none identified)"

        combination = state.retriever_combination.value if hasattr(state.retriever_combination, "value") else str(state.retriever_combination)
        _combination_labels = {
            "pageindex_vector_graph": "PageIndex, Vector, and CPG",
            "pageindex_vector":       "PageIndex and Vector",
            "pageindex_graph":        "PageIndex and CPG",
            "pageindex_and_graph":    "PageIndex and CPG (parallel)",
            "pageindex_and_vector":   "PageIndex and Vector (parallel)",
        }
        active_label = _combination_labels.get(combination, combination)

        return f"""You are an expert code analysis synthesizer.
Produce a final answer by reasoning across compressed findings from {active_label}.

**USER QUERY**: {state.user_query}
**SYNTHESIS STRATEGY**: {strategy}

## Per-Retriever Findings (compressed — all retrievers are equal participants)

{chr(10).join(summary_blocks)}

## Cross-Retriever Reconciliation

Agreements (high-confidence facts):
{agreements_str}

Conflicts (resolve these carefully using the agreement and confidence scores above):
{conflicts_str}

## Instructions

1. Ground your answer in the AGREEMENTS first — these are confirmed across retrievers.
2. For CONFLICTS, reason about which retriever is more authoritative for that claim type and explain.
3. Incorporate UNIQUE findings from each retriever only if they are plausible and not contradicted.
4. Do NOT invent facts not present in the findings above.
5. Cite which retriever(s) support each key claim in your details.

**OUTPUT FORMAT** — return ONLY valid JSON:
{{
    "answer": "Direct, comprehensive answer to the user query",
    "details": "Detailed explanation noting which retriever(s) support each claim",
    "confidence": <float 0.0-1.0>,
    "status": "found|not_found|partial",
    "suggestions": ["suggestion if needed"],
    "cross_validation": {{
        "vector_validates_cpg": <boolean>,
        "cpg_validates_vector": <boolean>,
        "conflicts_found": {json.dumps(reconciliation.conflicts)},
        "consensus_points": {json.dumps(reconciliation.agreements)},
        "confidence_score": {reconciliation.confidence_score},
        "validation_details": {{"strategy": "multi_source_map_reduce"}}
    }},
    "batch_metadata": {{
        "retrievers_used": {json.dumps([s.retriever for s in summaries])},
        "strategy_applied": "{strategy}"
    }}
}}"""

    async def _synthesize_single_source(self, state: HybridState, strategy: SynthesisStrategy) -> SynthesisResult:
        """Synthesize response from a single successful retriever"""
        if strategy == SynthesisStrategy.FALLBACK_VECTOR:
            source_result = state.vector_result
            source_name = "vector"
        else:
            source_result = state.cpg_result
            source_name = "cpg"
        
        # Use the existing response if available, otherwise synthesize new one
        if source_result.response_text:
            answer  = source_result.response_text
            details = source_result.response_text
        else:
            answer  = f"Found {len(source_result.raw_results)} results from {source_name} analysis."
            details = f"Analysis completed using {source_name} retrieval. Results: {source_result.raw_results}"
        
        return SynthesisResult(
            strategy_used=strategy,
            answer=answer,
            details=details,
            confidence=0.7 if source_result.status == RetrievalStatus.SUCCESS else 0.5,
            status="found" if source_result.raw_results else "partial",
            suggestions=[f"Results are based only on {source_name} analysis"],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=False,
                cpg_validates_vector=False,
                conflicts_found=[],
                consensus_points=[],
                confidence_score=0.5,
                validation_details={"single_source": source_name}
            ),
            evidence={source_name: source_result.raw_results},
            batch_metadata={"strategy": "single_source", "source": source_name}
        )
    
    async def _synthesize_hybrid_with_cross_validation(
        self, 
        state: HybridState, 
        strategy: SynthesisStrategy
    ) -> SynthesisResult:
        """Synthesize response with cross-validation between retrievers"""
        llm_service = state.llm_service
        
        # Process batched results to avoid context overflow
        synthesis_prompt = await self._build_hybrid_synthesis_prompt(state, strategy)
        
        # Generate synthesis with robust validation
        raw_response, error = await self._robust_llm_call_with_pydantic_validation(
            llm_service=llm_service,
            prompt=synthesis_prompt,
            pydantic_model=SynthesisRawResponse,
            max_tokens=16000,
            temperature=0.7,  # Higher temperature for creative synthesis and reasoning
            max_retries=3
        )
        
        if raw_response:
            return SynthesisResult(
                strategy_used=strategy,
                answer=raw_response.answer,
                details=raw_response.details,
                confidence=raw_response.confidence,
                status=raw_response.status,
                suggestions=raw_response.suggestions,
                cross_validation=CrossValidationResult(
                    vector_validates_cpg=raw_response.cross_validation.get("vector_validates_cpg", True),
                    cpg_validates_vector=raw_response.cross_validation.get("cpg_validates_vector", True),
                    conflicts_found=raw_response.cross_validation.get("conflicts_found", []),
                    consensus_points=raw_response.cross_validation.get("consensus_points", []),
                    confidence_score=raw_response.cross_validation.get("confidence_score", 0.7),
                    validation_details=raw_response.cross_validation.get("validation_details", {})
                ),
                evidence={
                    "vector": state.vector_result.raw_results if state.vector_result else [],
                    "cpg": state.cpg_result.raw_results if state.cpg_result else []
                },
                batch_metadata=raw_response.batch_metadata
            )
        
        logger.error(f"❌ Hybrid synthesis failed after retries: {error}")
        
        # Fallback hybrid synthesis
        return SynthesisResult(
            strategy_used=strategy,
            answer="Analysis completed with hybrid approach",
            details="Combined vector and CPG analysis results",
            confidence=0.6,
            status="found",
            suggestions=[],
            cross_validation=CrossValidationResult(
                vector_validates_cpg=True,
                cpg_validates_vector=True,
                conflicts_found=[],
                consensus_points=["Both retrievers provided results"],
                confidence_score=0.6,
                validation_details={"fallback": True}
            ),
            evidence={
                "vector": state.vector_result.raw_results if state.vector_result else [],
                "cpg": state.cpg_result.raw_results if state.cpg_result else []
            },
            batch_metadata={"fallback": True}
        )
    
    async def _build_hybrid_synthesis_prompt(self, state: HybridState, strategy: SynthesisStrategy) -> str:
        """Build synthesis prompt with intelligent batching"""
        # Process results in batches to manage context
        batch_summaries = []
        
        for i, batch in enumerate(state.batched_results):
            vector_items   = [item for item in batch if item.get("_source") == "vector"]
            cpg_items      = [item for item in batch if item.get("_source") == "cpg"]
            pageindex_items = [item for item in batch if item.get("_source") == "pageindex_partial"]

            batch_summary = (
                f"Batch {i+1}: {len(vector_items)} vector, "
                f"{len(cpg_items)} CPG, {len(pageindex_items)} pageindex items"
            )
            if vector_items:
                batch_summary += f" - Vector sample: {str(vector_items[0])}"
            if cpg_items:
                batch_summary += f" - CPG sample: {str(cpg_items[0])}"
            if pageindex_items:
                batch_summary += f" - PageIndex sample: {str(pageindex_items[0])}"

            batch_summaries.append(batch_summary)
        
        # Get responses from individual retrievers
        vector_response   = state.vector_result.response_text   if state.vector_result   and state.vector_result.response_text   else "No vector response"
        cpg_response      = state.cpg_result.response_text      if state.cpg_result      and state.cpg_result.response_text      else "No CPG response"
        pageindex_response = state.pageindex_result.response_text if state.pageindex_result and state.pageindex_result.response_text else "No PageIndex response"

        # Build pageindex context block — full response for '->' and 'and' combinations,
        # learnings summary when pageindex was insufficient
        pageindex_context = ""
        if state.pageindex_result and state.pageindex_result.succeeded:
            pi_meta = state.pageindex_result.metadata or {}
            pageindex_context = (
                f"\n**PAGEINDEX RESPONSE** (ran first — use as additional evidence):\n"
                f"{pageindex_response}\n"
                f"Confidence: {pi_meta.get('confidence_score', 'n/a')}  "
                f"Coverage: {pi_meta.get('coverage_score', 'n/a')}  "
                f"Faithfulness: {pi_meta.get('faithfulness_score', 'n/a')}\n"
            )

        learnings = state.pageindex_learnings
        if learnings:
            partial   = learnings.get("partial_response", "")
            files     = learnings.get("relevant_files", [])
            cites     = learnings.get("citation_extracts", [])
            gaps      = learnings.get("uncovered_topics", [])
            unres     = learnings.get("unsupported_claims", [])

            file_list   = ", ".join(f["title"] for f in files) if files else "none identified"
            cite_block  = "\n".join(f"  - [{c['title']}]: {c['extract']}" for c in cites) if cites else "  none"
            gap_block   = ", ".join(gaps) if gaps else "none"
            unres_block = "; ".join(unres) if unres else "none"

            pageindex_context = f"""
**PAGEINDEX HIGH-LEVEL FINDINGS** (partial — answer was insufficient, using vector+CPG for deeper retrieval):
Partial answer: {partial}
Relevant files identified: {file_list}
Verified excerpts from PageIndex:
{cite_block}
Topics not fully covered by PageIndex: {gap_block}
Unresolved claims (need vector/CPG confirmation): {unres_block}
"""

        # Build active retriever label based on which combination was run
        combination = state.retriever_combination.value if hasattr(state.retriever_combination, 'value') else str(state.retriever_combination)
        _combination_labels = {
            "pageindex_vector_graph": "PageIndex, Vector, and CPG",
            "pageindex_vector":       "PageIndex and Vector",
            "pageindex_graph":        "PageIndex and CPG",
            "pageindex_and_graph":    "PageIndex and CPG (parallel)",
            "pageindex_and_vector":   "PageIndex and Vector (parallel)",
        }
        active_retrievers_label = _combination_labels.get(combination, combination)

        return f"""You are an expert code analysis synthesizer using chain-of-thought reasoning.
Synthesize a comprehensive response by cross-validating {active_retrievers_label} retrieval results.

**USER QUERY**: {state.user_query}
**SYNTHESIS STRATEGY**: {strategy}
{pageindex_context}
**INDIVIDUAL RETRIEVER RESPONSES**:
Vector Response: {vector_response}
CPG Response: {cpg_response}

**BATCHED EVIDENCE SUMMARY**:
{chr(10).join(batch_summaries)}

**CHAIN-OF-THOUGHT SYNTHESIS**:

**Step 1: Cross-Validation Analysis**
Compare vector and CPG findings:
- What claims does each retriever make?
- Where do they agree (consensus points)?
- Where do they conflict?
- Can one validate claims made by the other?

**Step 2: Evidence Quality Assessment**
Evaluate the quality of evidence:
- Which retriever provides more relevant results?
- What is the quality and depth of the evidence?
- Are there gaps in either retriever's findings?

**Step 3: Synthesis Strategy Application**
Apply the {strategy} strategy:
- How should the results be weighted?
- What is the primary source of truth?
- How should conflicts be resolved?

**Step 4: Comprehensive Response Construction**
Build the final response:
- Direct answer to the user's query
- Supporting details with evidence
- Clear indication of confidence level
- Actionable suggestions if needed

**OUTPUT FORMAT**:
Return ONLY a valid JSON object:
{{
    "answer": "Direct, comprehensive answer to the user's query",
    "details": "Detailed explanation with evidence from both retrievers",
    "confidence": <float 0.0-1.0>,
    "status": "found|not_found|partial",
    "suggestions": ["suggestion1", "suggestion2"],
    "cross_validation": {{
        "vector_validates_cpg": <boolean>,
        "cpg_validates_vector": <boolean>,
        "conflicts_found": ["conflict1", "conflict2"],
        "consensus_points": ["consensus1", "consensus2"],
        "confidence_score": <float 0.0-1.0>,
        "validation_details": {{
            "primary_source": "vector|cpg|balanced",
            "agreement_level": "high|medium|low"
        }}
    }},
    "batch_metadata": {{
        "batches_processed": {len(state.batched_results)},
        "total_items": {len(state.combined_raw_results)},
        "strategy_applied": "{strategy}"
    }}
}}"""
    
    async def _improve_synthesis_with_critic_feedback(
        self, 
        state: HybridState, 
        critic_validation: CriticValidation
    ) -> Optional[SynthesisResult]:
        """Improve synthesis based on critic feedback"""
        try:
            llm_service = state.llm_service
            original_synthesis = state.synthesis_result
            
            improvement_prompt = f"""You are a synthesis improvement expert. Improve this response based on critic feedback.

**ORIGINAL SYNTHESIS**:
Answer: {original_synthesis.answer}
Details: {original_synthesis.details}
Confidence: {original_synthesis.confidence}

**CRITIC FEEDBACK**:
Decision: {critic_validation.decision}
Issues: {'; '.join(critic_validation.validation_issues)}
Suggestions: {'; '.join(critic_validation.improvement_suggestions)}
Scores: Hallucination={critic_validation.hallucination_score:.2f}, Faithfulness={critic_validation.faithfulness_score:.2f}, Accuracy={critic_validation.accuracy_score:.2f}

**AVAILABLE EVIDENCE**:
Vector: {json.dumps(state.vector_result.raw_results if state.vector_result else [], indent=2)}
CPG: {json.dumps(state.cpg_result.raw_results if state.cpg_result else [], indent=2)}
PageIndex: {json.dumps(state.pageindex_result.raw_results if state.pageindex_result else [], indent=2)}

**IMPROVEMENT REQUIREMENTS**:
1. Address all critic issues
2. Improve faithfulness to evidence  
3. Reduce hallucination risk
4. Increase accuracy
5. Maintain JSON format exactly

**OUTPUT FORMAT**:
Return the improved synthesis in exact same JSON format as original:
{{
    "answer": "Improved answer",
    "details": "Improved detailed explanation",
    "confidence": <float>,
    "status": "found|not_found|partial",
    "suggestions": ["improved suggestions"],
    "cross_validation": {original_synthesis.cross_validation},
    "evidence": {original_synthesis.evidence},
    "batch_metadata": {original_synthesis.batch_metadata}
}}"""
            
            # Generate improvement with robust validation
            raw_response, error = await self._robust_llm_call_with_pydantic_validation(
                llm_service=llm_service,
                prompt=improvement_prompt,
                pydantic_model=SynthesisImprovementRawResponse,
                max_tokens=16000,
                temperature=0.3,  # Moderate temperature for controlled improvement
                max_retries=3
            )
            
            if raw_response:
                # Create improved synthesis result
                improved_synthesis = SynthesisResult(
                    strategy_used=original_synthesis.strategy_used,
                    answer=raw_response.answer,
                    details=raw_response.details,
                    confidence=min(raw_response.confidence, 1.0),
                    status=raw_response.status,
                    suggestions=raw_response.suggestions,
                    cross_validation=original_synthesis.cross_validation,
                    evidence=original_synthesis.evidence,
                    batch_metadata=dict(original_synthesis.batch_metadata, **{"improved": True})
                )
                
                return improved_synthesis
            
            logger.error(f"❌ Synthesis improvement failed after retries: {error}")
                
        except Exception as e:
            logger.error(f"❌ Synthesis improvement failed: {e}")
        
        return None