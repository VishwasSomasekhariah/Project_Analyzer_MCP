"""
Approach Validation Agent V2 - Multi-turn reasoning with incremental APOC cache access.

This agent uses a multi-step reasoning process:
1. Analyze approach → Determine validation needs
2. Query APOC cache for relevant CATEGORIES (names only)
3. Select specific procedures from those categories
4. Get signatures for selected procedures
5. Generate validation queries
6. Execute and enhance approach packet

Uses incremental cache access to avoid overwhelming the LLM with all procedures at once.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from .apoc_cache_tool import APOCCacheTool, format_category_summary_for_prompt

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Multi-Turn Reasoning
# =============================================================================

class ValidationNeedAnalysis(BaseModel):
    """Step 1: Analyze what needs validation."""
    validation_needs: List[str] = Field(..., description="List of validation needs (e.g., 'Check if Function nodes exist')", max_items=3)
    reasoning: str = Field(..., description="Overall reasoning for these validations")


class CategorySelection(BaseModel):
    """Step 2: Select relevant APOC categories."""
    selected_categories: List[str] = Field(..., description="List of category names (e.g., ['apoc.meta', 'apoc.schema'])", max_items=3)
    reasoning: str = Field(..., description="Why these categories are relevant")


class ProcedureSelection(BaseModel):
    """Step 3: Select specific procedures from categories."""
    selected_procedures: List[str] = Field(..., description="List of procedure names (e.g., ['apoc.meta.schema', 'apoc.meta.type'])", max_items=3)
    reasoning: str = Field(..., description="Why these procedures are appropriate")


class ValidationQuery(BaseModel):
    """Step 4: Generated validation query."""
    query: str = Field(..., description="Cypher query for validation")
    purpose: str = Field(..., description="What this query validates")


# =============================================================================
# Approach Validation Agent V2
# =============================================================================

class ApproachValidationAgentV2:
    """
    Multi-turn reasoning agent with incremental APOC cache access.
    """

    def __init__(
        self,
        llm_service,
        cypher_server,
        apoc_cache_tool: Optional[APOCCacheTool] = None,
        max_queries_per_approach: int = 3
    ):
        self.llm_service = llm_service
        self.cypher_server = cypher_server
        self.cache_tool = apoc_cache_tool or APOCCacheTool()
        self.max_queries_per_approach = max_queries_per_approach

    async def validate_and_enhance_approach(
        self,
        approach: Dict[str, Any],
        user_query: str,
        project_name: str,
        approach_index: int
    ) -> Dict[str, Any]:
        """
        Validate and enhance approach using multi-turn reasoning.
        """
        approach_name = approach.get('approach_name', f'Approach {approach_index}')
        logger.info(f"🔍 Validating approach {approach_index}: {approach_name}")

        try:
            # Step 1: Analyze validation needs
            validation_needs = await self._step1_analyze_validation_needs(approach, user_query)
            if not validation_needs or not validation_needs.validation_needs:
                logger.info(f"  ℹ️ No validation needed for approach {approach_index}")
                return approach

            # Step 2: Select relevant APOC categories (incremental - just names)
            selected_categories = await self._step2_select_categories(approach, validation_needs)
            if not selected_categories or not selected_categories.selected_categories:
                logger.warning(f"  ⚠️ No relevant categories found")
                return approach

            # Step 3: Get procedures from selected categories and choose specific ones
            selected_procedures = await self._step3_select_procedures(
                approach, validation_needs, selected_categories
            )
            if not selected_procedures or not selected_procedures.selected_procedures:
                logger.warning(f"  ⚠️ No procedures selected")
                return approach

            # Step 4: Get signatures and generate queries
            validation_queries = await self._step4_generate_queries(
                approach, selected_procedures
            )
            if not validation_queries:
                logger.warning(f"  ⚠️ No validation queries generated")
                return approach

            # Step 5: Execute queries
            validation_results = await self._step5_execute_queries(validation_queries)

            # Step 6: Enhance approach packet
            enhanced_approach = self._step6_enhance_approach(
                approach, validation_needs, validation_results
            )

            logger.info(f"  ✅ Approach {approach_index} validated and enhanced")
            return enhanced_approach

        except Exception as e:
            logger.error(f"  ❌ Validation failed for approach {approach_index}: {e}")
            return approach

    async def _step1_analyze_validation_needs(
        self,
        approach: Dict[str, Any],
        user_query: str
    ) -> Optional[ValidationNeedAnalysis]:
        """
        Step 1: Analyze what validation is needed (no APOC cache access yet).
        """
        logger.info(f"  📋 Step 1: Analyzing validation needs...")

        prompt = f"""Analyze this approach and determine MINIMAL validation needs. Return your response as JSON.

USER QUERY: {user_query}

APPROACH:
- Name: {approach.get('approach_name', 'Unknown')}
- Target Nodes: {', '.join(approach.get('target_nodes', []))}
- Relationships: {', '.join(approach.get('relationships', []))}
- Strategy: {approach.get('strategy', 'N/A')}

YOUR TASK:
Identify 1-3 CRITICAL validation needs to prevent query failures.

Examples:
- "Check if Function nodes exist in the database"
- "Verify CALLS relationship exists between Function and Method"
- "Count Type nodes to ensure data is present"

Focus on:
- Entity existence (do target nodes exist?)
- Relationship existence (do target relationships exist?)
- Basic counts (is there data?)

Keep it MINIMAL - only what's essential to prevent failures.

Return JSON with validation_needs and reasoning.
"""

        try:
            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are a CPG validation expert focused on preventing query failures. Respond in JSON format.",
                user_prompt=prompt,
                response_model=ValidationNeedAnalysis,
                model_name="gpt-4o",  # Stronger model for reasoning
                temperature=0.0,  # Deterministic output for structured validation
                call_type="validation_needs_analysis",
                call_purpose=f"Analyze validation needs"
            )
            return result.data

        except Exception as e:
            logger.error(f"  ❌ Step 1 failed: {e}")
            return None

    async def _step2_select_categories(
        self,
        approach: Dict[str, Any],
        validation_needs: ValidationNeedAnalysis
    ) -> Optional[CategorySelection]:
        """
        Step 2: Select relevant APOC categories (incremental - just category names).
        """
        logger.info(f"  🏷️ Step 2: Selecting APOC categories...")

        # Get category summary from cache (compact format)
        category_summary = format_category_summary_for_prompt(self.cache_tool)

        prompt = f"""Select relevant APOC categories for validation. Return your response as JSON.

VALIDATION NEEDS:
{chr(10).join(f"- {need}" for need in validation_needs.validation_needs)}

{category_summary}

YOUR TASK:
Select 1-3 categories that are most relevant for these validation needs.

Guidelines:
- apoc.meta: Schema introspection, node/relationship existence
- apoc.schema: Schema information, constraints
- apoc.node/apoc.nodes: Node operations, existence checks
- apoc.path: Path traversal (only if relationships need validation)

Return JSON with selected_categories and reasoning.
"""

        try:
            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are selecting APOC categories for validation tasks. Respond in JSON format.",
                user_prompt=prompt,
                response_model=CategorySelection,
                model_name="gpt-4o",  # Stronger model for reasoning
                temperature=0.0,  # Deterministic output
                call_type="category_selection",
                call_purpose="Select APOC categories"
            )
            return result.data

        except Exception as e:
            logger.error(f"  ❌ Step 2 failed: {e}")
            return None

    async def _step3_select_procedures(
        self,
        approach: Dict[str, Any],
        validation_needs: ValidationNeedAnalysis,
        selected_categories: CategorySelection
    ) -> Optional[ProcedureSelection]:
        """
        Step 3: Get procedures from selected categories and choose specific ones.
        """
        logger.info(f"  🔧 Step 3: Selecting specific procedures...")

        # Get procedures for selected categories (incremental - only selected categories)
        procedures_info = []
        for category in selected_categories.selected_categories:
            procs = self.cache_tool.get_procedures_summary_in_category(category)
            procedures_info.append({
                'category': category,
                'procedures': procs
            })

        # Format for prompt
        procedures_text = []
        for cat_info in procedures_info:
            procedures_text.append(f"\n{cat_info['category']}:")
            for proc in cat_info['procedures']:
                procedures_text.append(f"  • {proc['name']}")
                procedures_text.append(f"    {proc['description']}")

        prompt = f"""Select specific APOC procedures for validation. Return your response as JSON.

VALIDATION NEEDS:
{chr(10).join(f"- {need}" for need in validation_needs.validation_needs)}

AVAILABLE PROCEDURES:
{''.join(procedures_text)}

YOUR TASK:
Select 1-3 specific procedures that match the validation needs.

Choose procedures that:
- Directly address the validation needs
- Are lightweight (counts, existence checks)
- Work on large graphs (avoid expensive traversals)

Return JSON with selected_procedures and reasoning (full procedure names like 'apoc.meta.schema').
"""

        try:
            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are selecting specific APOC procedures for validation. Respond in JSON format.",
                user_prompt=prompt,
                response_model=ProcedureSelection,
                model_name="gpt-4o",  # Stronger model for reasoning
                temperature=0.0,  # Deterministic output
                call_type="procedure_selection",
                call_purpose="Select specific procedures"
            )
            return result.data

        except Exception as e:
            logger.error(f"  ❌ Step 3 failed: {e}")
            return None

    async def _step4_generate_queries(
        self,
        approach: Dict[str, Any],
        selected_procedures: ProcedureSelection
    ) -> List[ValidationQuery]:
        """
        Step 4: Get signatures for selected procedures and generate queries.
        """
        logger.info(f"  📝 Step 4: Generating validation queries...")

        validation_queries = []

        for proc_name in selected_procedures.selected_procedures:
            # Get signature from cache (incremental - only for selected procedure)
            signature_info = self.cache_tool.get_procedure_signature(proc_name)
            if not signature_info:
                logger.warning(f"  ⚠️ Procedure {proc_name} not found in cache")
                continue

            # Generate query using signature
            query = await self._generate_query_for_procedure(
                approach, proc_name, signature_info
            )
            if query:
                validation_queries.append(query)

        return validation_queries

    async def _generate_query_for_procedure(
        self,
        approach: Dict[str, Any],
        proc_name: str,
        signature_info: Dict[str, str]
    ) -> Optional[ValidationQuery]:
        """Generate a validation query for a specific procedure."""

        prompt = f"""Generate a lightweight validation query using this APOC procedure.

PROCEDURE: {proc_name}
SIGNATURE: {signature_info['signature']}
DESCRIPTION: {signature_info['description']}

APPROACH CONTEXT:
- Target Nodes: {', '.join(approach.get('target_nodes', []))}
- Target Relationships: {', '.join(approach.get('relationships', []))}

REQUIREMENTS:
1. Generate a LIGHTWEIGHT query (efficient on large graphs)
2. Use LIMIT to restrict results
3. Return counts or existence checks (not full data)
4. Follow the procedure signature exactly

EXAMPLES:
- For checking nodes: MATCH (n:Function) RETURN count(n) as count LIMIT 1
- For schema info: CALL apoc.meta.schema() YIELD value RETURN value

Generate an efficient validation query.
"""

        try:
            result = await self.llm_service.generate_with_pydantic(
                system_prompt="You are generating efficient Neo4j validation queries. Respond in JSON format.",
                user_prompt=prompt,
                response_model=ValidationQuery,
                model_name="gpt-4o-mini",
                temperature=0.0,  # Deterministic output
                call_type="query_generation",
                call_purpose=f"Generate query for {proc_name}"
            )
            return result.data

        except Exception as e:
            logger.error(f"  ❌ Query generation failed for {proc_name}: {e}")
            return None

    async def _step5_execute_queries(
        self,
        validation_queries: List[ValidationQuery]
    ) -> List[Dict[str, Any]]:
        """Step 5: Execute validation queries."""
        logger.info(f"  ⚙️ Step 5: Executing {len(validation_queries)} validation queries...")

        results = []
        for i, val_query in enumerate(validation_queries):
            try:
                result = await self.cypher_server.execute_query(
                    val_query.query,
                    limit=10
                )

                results.append({
                    'query': val_query.query,
                    'purpose': val_query.purpose,
                    'success': True,
                    'data': result.get('data', []),
                    'row_count': len(result.get('data', []))
                })

            except Exception as e:
                logger.error(f"  ❌ Query {i+1} failed: {e}")
                results.append({
                    'query': val_query.query,
                    'purpose': val_query.purpose,
                    'success': False,
                    'error': str(e)
                })

        return results

    def _step6_enhance_approach(
        self,
        approach: Dict[str, Any],
        validation_needs: ValidationNeedAnalysis,
        validation_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Step 6: Enhance approach packet with validation context."""
        logger.info(f"  ✨ Step 6: Enhancing approach packet...")

        validation_context = {
            'validation_performed': True,
            'validation_needs': validation_needs.validation_needs,
            'validation_results': [],
            'warnings': [],
            'ready_for_execution': True
        }

        for result in validation_results:
            finding = self._interpret_result(result)
            validation_context['validation_results'].append({
                'purpose': result['purpose'],
                'success': result['success'],
                'finding': finding
            })

            # Check for warnings
            if result['success'] and result['row_count'] == 0:
                validation_context['warnings'].append(
                    f"⚠️ {result['purpose']}: No data found"
                )
                validation_context['ready_for_execution'] = False

        validation_summary = self._format_summary(validation_context)

        return {
            **approach,
            'validation_context': validation_context,
            'validation_summary': validation_summary
        }

    def _interpret_result(self, result: Dict[str, Any]) -> str:
        """Interpret validation result."""
        if not result['success']:
            return f"❌ Failed: {result.get('error', 'Unknown error')}"

        if result['row_count'] == 0:
            return "❌ No data found"

        data = result['data']
        if data and 'count' in data[0]:
            count = data[0]['count']
            return f"✅ Found {count} instances" if count > 0 else "❌ Count is 0"

        return f"✅ Data exists ({result['row_count']} results)"

    def _format_summary(self, validation_context: Dict[str, Any]) -> str:
        """Format validation summary for prompts."""
        lines = [
            "=== APPROACH VALIDATION RESULTS ===",
            ""
        ]

        for result in validation_context['validation_results']:
            lines.append(f"• {result['purpose']}: {result['finding']}")

        if validation_context['warnings']:
            lines.append("")
            lines.append("⚠️ WARNINGS:")
            for warning in validation_context['warnings']:
                lines.append(f"  {warning}")

        lines.append("")
        status = "✅ Ready for execution" if validation_context['ready_for_execution'] else "❌ Has validation issues"
        lines.append(status)
        lines.append("=" * 40)

        return "\n".join(lines)


# =============================================================================
# Convenience Function
# =============================================================================

async def validate_and_enhance_approaches(
    approaches: List[Dict[str, Any]],
    user_query: str,
    project_name: str,
    llm_service,
    cypher_server
) -> List[Dict[str, Any]]:
    """
    Validate and enhance approaches using V2 agent (multi-turn reasoning).
    """
    logger.info(f"🔍 Validating {len(approaches)} approaches...")

    agent = ApproachValidationAgentV2(llm_service, cypher_server)

    enhanced_approaches = []
    for i, approach in enumerate(approaches):
        enhanced = await agent.validate_and_enhance_approach(
            approach, user_query, project_name, i
        )
        enhanced_approaches.append(enhanced)

    logger.info(f"✅ Validated {len(enhanced_approaches)} approaches")
    return enhanced_approaches
