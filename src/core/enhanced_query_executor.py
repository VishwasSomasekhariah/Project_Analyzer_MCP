"""
Enhanced Query Executor with Critic-Based Validation
Executes adaptive queries with intelligent validation and sufficiency checking
"""

import json
import time
import asyncio
import logging
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from src.core.adaptive_cpg_discovery import AdaptiveQuery, ProjectCapabilities

logger = logging.getLogger(__name__)

@dataclass
class QueryResult:
    """Enhanced query result with validation metadata"""
    query_id: str
    status: str
    results: List[Dict[str, Any]]
    execution_time: float
    validation_status: str
    sufficiency_score: float
    missing_requirements: List[str]
    suggested_expansions: List[str]

@dataclass
class CriticAnalysis:
    """Critic's assessment of query results sufficiency"""
    is_sufficient: bool
    confidence_score: float
    missing_aspects: List[str]
    suggested_queries: List[AdaptiveQuery]
    reasoning: str

class QueryCritic:
    """
    Intelligent critic that validates query results for sufficiency
    """
    
    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        self.validation_patterns = self._load_validation_patterns()
    
    def _load_validation_patterns(self) -> Dict[str, Any]:
        """Load patterns for validating different query types"""
        return {
            "architectural_analysis": {
                "required_elements": ["project", "files", "types", "relationships"],
                "min_results_per_element": {"files": 3, "types": 2, "relationships": 1},
                "quality_indicators": ["inheritance_info", "dependency_mapping", "component_structure"]
            },
            "dependency_analysis": {
                "required_elements": ["caller", "callee", "relationships"],
                "min_results_per_element": {"relationships": 1},
                "quality_indicators": ["cross_file_dependencies", "interface_usage", "factory_patterns"]
            },
            "implementation_details": {
                "required_elements": ["code_bodies", "method_signatures", "class_structure"],
                "min_results_per_element": {"code_bodies": 1},
                "quality_indicators": ["method_implementations", "constructor_patterns", "field_usage"]
            }
        }
    
    async def assess_sufficiency(
        self, 
        user_query: str, 
        query_results: List[QueryResult],
        intent: str
    ) -> CriticAnalysis:
        """
        Assess whether the retrieved results are sufficient to answer user query
        """
        logger.info(f"🎭 CRITIC: Assessing sufficiency for intent '{intent}'")
        
        # Pattern-based validation first
        pattern_assessment = self._pattern_based_assessment(query_results, intent)
        
        # LLM-based validation if available
        llm_assessment = None
        if self.llm_service:
            llm_assessment = await self._llm_based_assessment(user_query, query_results, intent)
        
        # Combine assessments
        final_analysis = self._combine_assessments(
            pattern_assessment, llm_assessment, user_query, intent
        )
        
        logger.info(f"🎭 CRITIC: Sufficiency={final_analysis.is_sufficient}, "
                   f"Confidence={final_analysis.confidence_score:.2f}")
        
        return final_analysis
    
    def _pattern_based_assessment(self, query_results: List[QueryResult], intent: str) -> Dict[str, Any]:
        """Rule-based assessment using validation patterns"""
        if intent not in self.validation_patterns:
            intent = "architectural_analysis"  # default
        
        pattern = self.validation_patterns[intent]
        required_elements = pattern["required_elements"]
        min_results = pattern["min_results_per_element"]
        quality_indicators = pattern["quality_indicators"]
        
        # Check if we have results for each required element
        coverage = {}
        total_results = 0
        
        for result in query_results:
            if result.status == "success":
                total_results += len(result.results)
                
                # Analyze what elements this result provides
                if "project" in result.query_id.lower() or "overview" in result.query_id.lower():
                    coverage["project"] = len(result.results)
                elif "file" in result.query_id.lower():
                    coverage["files"] = coverage.get("files", 0) + len(result.results)
                elif "type" in result.query_id.lower() or "class" in result.query_id.lower():
                    coverage["types"] = coverage.get("types", 0) + len(result.results)
                elif "relationship" in result.query_id.lower() or "dependency" in result.query_id.lower():
                    coverage["relationships"] = coverage.get("relationships", 0) + len(result.results)
                elif "implementation" in result.query_id.lower() or "body" in result.query_id.lower():
                    coverage["code_bodies"] = coverage.get("code_bodies", 0) + len(result.results)
        
        # Calculate coverage score
        coverage_score = 0.0
        missing_elements = []
        
        for element in required_elements:
            min_required = min_results.get(element, 1)
            actual_count = coverage.get(element, 0)
            
            if actual_count >= min_required:
                coverage_score += 1.0
            elif actual_count > 0:
                coverage_score += actual_count / min_required
            else:
                missing_elements.append(element)
        
        coverage_score = coverage_score / len(required_elements)
        
        # Quality assessment
        quality_score = self._assess_result_quality(query_results, quality_indicators)
        
        return {
            "coverage_score": coverage_score,
            "quality_score": quality_score,
            "missing_elements": missing_elements,
            "total_results": total_results,
            "assessment_type": "pattern_based"
        }
    
    def _assess_result_quality(self, query_results: List[QueryResult], quality_indicators: List[str]) -> float:
        """Assess quality of results based on indicators"""
        quality_score = 0.0
        total_indicators = len(quality_indicators)
        
        # Check for quality indicators in results
        for result in query_results:
            if result.status == "success":
                for item in result.results:
                    # Check for inheritance information
                    if "inheritance_info" in quality_indicators:
                        if item.get("base_list") or item.get("inheritance_info"):
                            quality_score += 0.3
                    
                    # Check for dependency mapping
                    if "dependency_mapping" in quality_indicators:
                        if item.get("caller_name") or item.get("relationship_type"):
                            quality_score += 0.3
                    
                    # Check for implementation details
                    if "method_implementations" in quality_indicators:
                        if item.get("body") or item.get("implementation_preview"):
                            quality_score += 0.4
        
        return min(1.0, quality_score)
    
    async def _llm_based_assessment(
        self, 
        user_query: str, 
        query_results: List[QueryResult],
        intent: str
    ) -> Optional[Dict[str, Any]]:
        """LLM-based intelligent assessment of result sufficiency"""
        try:
            # Prepare results summary for LLM
            results_summary = self._prepare_results_summary(query_results)
            
            assessment_prompt = f"""
Assess whether the following query results are sufficient to answer the user's question.

USER QUERY: {user_query}
QUERY INTENT: {intent}

RETRIEVED RESULTS SUMMARY:
{results_summary}

Analyze:
1. Does the data contain information needed to answer the user's question?
2. What key aspects of the query are covered?
3. What important information is missing?
4. What additional queries would help?

Respond with JSON:
{{
    "is_sufficient": boolean,
    "confidence": float (0-1),
    "covered_aspects": [list of covered topics],
    "missing_aspects": [list of missing information],
    "suggested_expansions": [list of additional query suggestions]
}}
"""
            
            response = await self.llm_service.generate_response(
                prompt=assessment_prompt,
                system_prompt="You are a code analysis expert assessing query result completeness.",
                max_tokens=500,
                temperature=0.1
            )
            
            if response and response.content:
                try:
                    return json.loads(response.content)
                except json.JSONDecodeError:
                    logger.warning("LLM assessment response not valid JSON")
                    return None
            
        except Exception as e:
            logger.warning(f"LLM-based assessment failed: {e}")
            return None
    
    def _prepare_results_summary(self, query_results: List[QueryResult]) -> str:
        """Prepare a concise summary of results for LLM analysis"""
        summary_parts = []
        
        for result in query_results:
            if result.status == "success" and result.results:
                result_count = len(result.results)
                sample_keys = set()
                
                # Collect sample field names
                for item in result.results[:3]:  # First 3 items
                    sample_keys.update(item.keys())
                
                summary_parts.append(
                    f"- {result.query_id}: {result_count} results with fields: {', '.join(sorted(sample_keys))}"
                )
        
        return "\n".join(summary_parts) if summary_parts else "No successful results"
    
    def _combine_assessments(
        self, 
        pattern_assessment: Dict[str, Any],
        llm_assessment: Optional[Dict[str, Any]],
        user_query: str,
        intent: str
    ) -> CriticAnalysis:
        """Combine pattern and LLM assessments into final analysis"""
        
        # Pattern-based scores
        coverage_score = pattern_assessment["coverage_score"]
        quality_score = pattern_assessment["quality_score"]
        pattern_score = (coverage_score * 0.7) + (quality_score * 0.3)
        
        # LLM-based scores (if available)
        llm_score = 0.5  # neutral if no LLM
        if llm_assessment:
            llm_score = llm_assessment.get("confidence", 0.5)
        
        # Combined confidence
        final_confidence = (pattern_score * 0.6) + (llm_score * 0.4)
        
        # Determine sufficiency
        is_sufficient = (
            final_confidence >= 0.7 and
            coverage_score >= 0.6 and
            pattern_assessment["total_results"] >= 3
        )
        
        # Combine missing aspects
        missing_aspects = pattern_assessment["missing_elements"]
        if llm_assessment and "missing_aspects" in llm_assessment:
            missing_aspects.extend(llm_assessment["missing_aspects"])
        
        # Generate reasoning
        reasoning = f"Pattern assessment: {pattern_score:.2f} (coverage: {coverage_score:.2f}, quality: {quality_score:.2f})"
        if llm_assessment:
            reasoning += f", LLM assessment: {llm_score:.2f}"
        
        return CriticAnalysis(
            is_sufficient=is_sufficient,
            confidence_score=final_confidence,
            missing_aspects=list(set(missing_aspects)),
            suggested_queries=[],  # Will be populated by expansion generator
            reasoning=reasoning
        )


class EnhancedQueryExecutor:
    """
    Enhanced query executor with adaptive capabilities and critic validation
    """
    
    def __init__(self, config_path: str = "/opt/genpod/neo4j_config.json"):
        self.config_path = config_path
        self.critic = QueryCritic()
        self.execution_stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "critic_assessments": 0,
            "iterative_expansions": 0
        }
    
    async def execute_adaptive_retrieval(
        self,
        adaptive_queries: List[AdaptiveQuery],
        user_query: str,
        intent: str,
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        Execute adaptive queries with critic-based validation and iterative expansion
        """
        logger.info(f"🚀 EXECUTION: Starting adaptive retrieval with {len(adaptive_queries)} queries")
        start_time = time.time()
        
        all_results = []
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"🔄 ITERATION {iteration}: Executing {len(adaptive_queries)} queries")
            
            # Execute current batch of queries
            batch_results = await self._execute_query_batch(adaptive_queries)
            all_results.extend(batch_results)
            
            # Critic assessment
            critic_analysis = await self.critic.assess_sufficiency(user_query, batch_results, intent)
            self.execution_stats["critic_assessments"] += 1
            
            # If sufficient, we're done
            if critic_analysis.is_sufficient:
                logger.info(f"✅ SUFFICIENT: Critic determined results are sufficient after {iteration} iterations")
                break
            
            # Generate expansion queries based on what's missing
            if iteration < max_iterations:
                expansion_queries = await self._generate_expansion_queries(
                    critic_analysis.missing_aspects, 
                    user_query, 
                    intent
                )
                
                if expansion_queries:
                    adaptive_queries = expansion_queries
                    self.execution_stats["iterative_expansions"] += 1
                    logger.info(f"🎯 EXPANSION: Generated {len(expansion_queries)} additional queries")
                else:
                    logger.info("⚠️ No expansion queries generated, stopping iteration")
                    break
            else:
                logger.info(f"⏹️ Max iterations ({max_iterations}) reached")
        
        # Compile final results
        successful_results = [r for r in all_results if r.status == "success"]
        combined_data = []
        for result in successful_results:
            combined_data.extend(result.results)
        
        execution_time = time.time() - start_time
        
        # Update stats
        self.execution_stats["total_queries"] += len([r for batch in [all_results] for r in batch])
        self.execution_stats["successful_queries"] += len(successful_results)
        
        return {
            "status": "success",
            "results": combined_data,
            "execution_metadata": {
                "total_iterations": iteration,
                "total_queries_executed": len(all_results),
                "successful_queries": len(successful_results),
                "execution_time": round(execution_time, 3),
                "critic_final_assessment": {
                    "is_sufficient": critic_analysis.is_sufficient,
                    "confidence_score": critic_analysis.confidence_score,
                    "reasoning": critic_analysis.reasoning
                }
            },
            "query_details": [
                {
                    "query_id": r.query_id,
                    "status": r.status,
                    "result_count": len(r.results),
                    "execution_time": r.execution_time,
                    "sufficiency_score": r.sufficiency_score
                } for r in all_results
            ]
        }
    
    async def _execute_query_batch(self, adaptive_queries: List[AdaptiveQuery]) -> List[QueryResult]:
        """Execute a batch of adaptive queries with fallback handling"""
        batch_results = []
        
        for i, query in enumerate(adaptive_queries):
            query_id = f"{query.purpose.replace(' ', '_')}_{i}"
            result = await self._execute_single_adaptive_query(query, query_id)
            batch_results.append(result)
        
        return batch_results
    
    async def _execute_single_adaptive_query(self, query: AdaptiveQuery, query_id: str) -> QueryResult:
        """Execute a single adaptive query with validation and fallbacks"""
        start_time = time.time()
        
        # Try main query first
        result = await self._execute_cypher_query(query.cypher, query_id)
        execution_time = time.time() - start_time
        
        # Validate result
        validation_status, sufficiency_score = self._validate_query_result(result, query)
        
        # Try fallbacks if main query failed or insufficient
        if result["status"] != "success" or sufficiency_score < 0.5:
            for i, fallback_query in enumerate(query.fallback_queries):
                logger.info(f"🔄 FALLBACK: Trying fallback {i+1} for {query_id}")
                fallback_result = await self._execute_cypher_query(fallback_query, f"{query_id}_fallback_{i}")
                
                if fallback_result["status"] == "success":
                    result = fallback_result
                    validation_status = "fallback_success"
                    sufficiency_score = 0.6  # Moderate score for fallback success
                    break
        
        # Extract missing requirements and suggestions
        missing_requirements = self._identify_missing_requirements(result, query)
        suggested_expansions = self._suggest_query_expansions(result, query)
        
        return QueryResult(
            query_id=query_id,
            status=result["status"],
            results=result.get("results", []),
            execution_time=execution_time,
            validation_status=validation_status,
            sufficiency_score=sufficiency_score,
            missing_requirements=missing_requirements,
            suggested_expansions=suggested_expansions
        )
    
    async def _execute_cypher_query(self, cypher_query: str, query_id: str) -> Dict[str, Any]:
        """Execute a Cypher query using the graph executor"""
        try:
            from src.core.graph_query_executor import GraphQueryExecutor
            executor = GraphQueryExecutor()
            
            query_info = {
                "cypher": cypher_query,
                "type": "adaptive_query",
                "purpose": query_id
            }
            
            result = await executor._execute_single_query(query_info, self.config_path, query_id)
            return result
            
        except Exception as e:
            logger.error(f"Query execution failed for {query_id}: {e}")
            return {
                "status": "error",
                "error": str(e),
                "results": []
            }
    
    def _validate_query_result(self, result: Dict[str, Any], query: AdaptiveQuery) -> Tuple[str, float]:
        """Validate query result against expectations"""
        if result["status"] != "success":
            return "failed", 0.0
        
        results = result.get("results", [])
        if not results:
            return "empty", 0.0
        
        # Check against validation criteria
        criteria = query.validation_criteria
        min_results = criteria.get("min_results", 1)
        required_types = criteria.get("required_types", [])
        
        if len(results) < min_results:
            return "insufficient", 0.3
        
        # Check for expected properties
        property_score = 0.0
        if query.expected_properties:
            found_properties = set()
            for item in results[:5]:  # Check first 5 results
                found_properties.update(item.keys())
            
            expected_set = set(query.expected_properties)
            found_expected = expected_set.intersection(found_properties)
            property_score = len(found_expected) / len(expected_set)
        
        # Overall sufficiency score
        sufficiency = min(1.0, len(results) / max(min_results, 1)) * 0.7 + property_score * 0.3
        
        if sufficiency >= 0.8:
            return "excellent", sufficiency
        elif sufficiency >= 0.6:
            return "good", sufficiency
        else:
            return "insufficient", sufficiency
    
    def _identify_missing_requirements(self, result: Dict[str, Any], query: AdaptiveQuery) -> List[str]:
        """Identify what requirements are missing from the result"""
        missing = []
        
        if result["status"] != "success":
            missing.append("query_execution_failed")
            return missing
        
        results = result.get("results", [])
        if not results:
            missing.append("no_results")
            return missing
        
        # Check for expected properties
        if query.expected_properties:
            found_properties = set()
            for item in results[:5]:
                found_properties.update(item.keys())
            
            for prop in query.expected_properties:
                if prop not in found_properties:
                    missing.append(f"missing_property_{prop}")
        
        return missing
    
    def _suggest_query_expansions(self, result: Dict[str, Any], query: AdaptiveQuery) -> List[str]:
        """Suggest potential query expansions based on result analysis"""
        suggestions = []
        
        if result["status"] == "success":
            results = result.get("results", [])
            
            # Suggest expanding based on found relationships
            for item in results[:3]:  # Check first 3 results
                if "file_path" in item and "name" in item:
                    suggestions.append(f"expand_file_contents:{item['file_path']}")
                if "relationship_type" in item:
                    suggestions.append(f"expand_relationships:{item['relationship_type']}")
        
        return suggestions
    
    async def _generate_expansion_queries(
        self, 
        missing_aspects: List[str], 
        user_query: str, 
        intent: str
    ) -> List[AdaptiveQuery]:
        """Generate additional queries to address missing aspects"""
        expansion_queries = []
        
        for aspect in missing_aspects:
            if aspect == "files":
                expansion_queries.append(AdaptiveQuery(
                    cypher="MATCH (p:Project)-[:CONTAINS]->(f:File) RETURN f.name, f.file_path ORDER BY f.name",
                    purpose="Get missing file information",
                    expected_properties=["name", "file_path"],
                    fallback_queries=["MATCH (f:File) RETURN f.name LIMIT 10"],
                    validation_criteria={"min_results": 1}
                ))
            
            elif aspect == "types":
                expansion_queries.append(AdaptiveQuery(
                    cypher="MATCH (t:Type) RETURN t.name, t.file_path, t.base_list ORDER BY t.name",
                    purpose="Get missing type information",
                    expected_properties=["name", "file_path", "base_list"],
                    fallback_queries=["MATCH (t:Type) RETURN t.name LIMIT 10"],
                    validation_criteria={"min_results": 1}
                ))
            
            elif aspect == "relationships":
                expansion_queries.append(AdaptiveQuery(
                    cypher="MATCH (a)-[r]->(b) WHERE labels(a)[0] IN ['Type', 'Function'] RETURN labels(a)[0] AS source_type, a.name AS source, type(r) AS relationship, labels(b)[0] AS target_type, b.name AS target LIMIT 20",
                    purpose="Get missing relationship information",
                    expected_properties=["source", "relationship", "target"],
                    fallback_queries=["MATCH ()-[r]->() RETURN DISTINCT type(r) LIMIT 10"],
                    validation_criteria={"min_results": 1}
                ))
        
        return expansion_queries
    
    def get_execution_statistics(self) -> Dict[str, Any]:
        """Get execution statistics"""
        return self.execution_stats.copy()