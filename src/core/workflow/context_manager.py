"""
Context Management for the Adaptive CPG Agent Workflow.

This module handles data organization, synthesis preparation, context compression,
and all data processing tasks that support the LangGraph workflow nodes.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
import json

logger = logging.getLogger(__name__)


class ContextManager:
    """
    Context management for CPG workflow data.
    
    Handles:
    - Data organization from raw CPG results
    - Context preparation for synthesis
    - Data sampling and compression
    - Architectural summary generation
    """
    
    def __init__(self, llm_service):
        self.llm_service = llm_service

    def organize_discovered_data(self, raw_data: List[Dict], state) -> Dict[str, Any]:
        """
        Organize raw CPG data into structured categories for analysis.
        
        Returns organized data with categories like functions, types, relationships, etc.
        """
        logger.info(f"📊 Organizing {len(raw_data)} raw data items")
        
        organized = {
            "functions": [],
            "types": [],
            "variables": [],
            "files": [],
            "relationships": [],
            "other_nodes": [],
            "query_summaries": [],
            "total_items": len(raw_data)
        }
        
        # Process each raw data item
        for item in raw_data:
            self._categorize_discovered_item(item, organized)
        
        # Generate summary statistics
        organized["summary"] = {
            "functions_count": len(organized["functions"]),
            "types_count": len(organized["types"]),
            "variables_count": len(organized["variables"]),
            "files_count": len(organized["files"]),
            "relationships_count": len(organized["relationships"]),
            "other_nodes_count": len(organized["other_nodes"])
        }
        
        logger.info(f"✅ Data organized: {organized['summary']}")
        return organized

    def _categorize_discovered_item(self, item: Dict, organized: Dict):
        """
        Categorize a single discovered item into the appropriate category.
        """
        if not item:
            return
            
        # Handle different item structures
        item_type = item.get('type_kind') or item.get('type') or 'unknown'
        
        # Categorize based on type_kind or other identifying fields
        if any(keyword in item_type.lower() for keyword in ['function', 'method', 'constructor']):
            organized["functions"].append(item)
        elif any(keyword in item_type.lower() for keyword in ['class', 'struct', 'enum', 'interface', 'type']):
            organized["types"].append(item)
        elif any(keyword in item_type.lower() for keyword in ['variable', 'field', 'parameter', 'property']):
            organized["variables"].append(item)
        elif any(keyword in item_type.lower() for keyword in ['file']):
            organized["files"].append(item)
        elif 'relationship' in str(item).lower() or any(rel_key in item for rel_key in ['source', 'target', 'relationship_type']):
            organized["relationships"].append(item)
        else:
            organized["other_nodes"].append(item)

    async def generate_architectural_summary(self, organized_data: Dict[str, Any], state) -> Dict[str, Any]:
        """
        Generate architectural summary from organized data using LLM analysis.
        """
        logger.info("🏗️ Generating architectural summary")
        
        try:
            # Prepare structural context for analysis
            structural_context = self._prepare_structural_context(organized_data)
            
            summary_prompt = f"""
            Analyze this organized CPG data to create an architectural summary:
            
            **USER QUERY**: {state['user_query']}
            **INTENT**: {state['intent']}
            
            **ORGANIZED DATA SUMMARY**:
            - Functions: {len(organized_data.get('functions', []))}
            - Types: {len(organized_data.get('types', []))}
            - Variables: {len(organized_data.get('variables', []))}
            - Files: {len(organized_data.get('files', []))}
            - Relationships: {len(organized_data.get('relationships', []))}
            
            **STRUCTURAL CONTEXT**:
            {json.dumps(structural_context, indent=2)}
            
            **SAMPLE DATA** (first few items from each category):
            Functions: {json.dumps(organized_data.get('functions', [])[:3], indent=2)}
            Types: {json.dumps(organized_data.get('types', [])[:3], indent=2)}
            Variables: {json.dumps(organized_data.get('variables', [])[:3], indent=2)}
            
            Generate an architectural summary focusing on:
            1. Key components and their relationships
            2. Architectural patterns identified
            3. Important structural information
            4. Relevant insights for the user's query
            
            Keep the summary concise but informative.
            """
            
            result = await self.llm_service.generate_response(summary_prompt)
            
            if result and not result.error:
                architectural_summary = result.content
            else:
                architectural_summary = self._generate_basic_structural_summary(organized_data)
            
            logger.info("✅ Architectural summary generated")
            return {
                **organized_data,
                "architectural_summary": architectural_summary,
                "structural_context": structural_context
            }
            
        except Exception as e:
            logger.error(f"❌ Architectural summary generation failed: {e}")
            return {
                **organized_data,
                "architectural_summary": self._generate_basic_structural_summary(organized_data),
                "structural_context": self._prepare_structural_context(organized_data)
            }

    def _prepare_structural_context(self, organized_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare structural context information for analysis.
        """
        context = {
            "component_counts": organized_data.get('summary', {}),
            "key_functions": [],
            "key_types": [],
            "file_distribution": {},
            "relationship_patterns": []
        }
        
        # Extract key function information
        for func in organized_data.get('functions', [])[:5]:
            if func.get('name'):
                context["key_functions"].append({
                    "name": func.get('name'),
                    "file": func.get('file_path', 'unknown'),
                    "type": func.get('type_kind', 'function')
                })
        
        # Extract key type information  
        for type_item in organized_data.get('types', [])[:5]:
            if type_item.get('name'):
                context["key_types"].append({
                    "name": type_item.get('name'),
                    "kind": type_item.get('type_kind', 'type'),
                    "file": type_item.get('file_path', 'unknown')
                })
        
        # Analyze file distribution
        all_items = (organized_data.get('functions', []) + 
                    organized_data.get('types', []) + 
                    organized_data.get('variables', []))
        
        for item in all_items:
            file_path = item.get('file_path', 'unknown')
            if file_path not in context["file_distribution"]:
                context["file_distribution"][file_path] = 0
            context["file_distribution"][file_path] += 1
        
        return context

    def _generate_basic_structural_summary(self, organized_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate basic structural summary when LLM analysis fails.
        """
        summary = organized_data.get('summary', {})
        
        return {
            "overview": f"Analyzed CPG data containing {summary.get('functions_count', 0)} functions, "
                       f"{summary.get('types_count', 0)} types, and {summary.get('variables_count', 0)} variables",
            "key_components": {
                "functions": summary.get('functions_count', 0),
                "types": summary.get('types_count', 0),
                "variables": summary.get('variables_count', 0),
                "files": summary.get('files_count', 0)
            },
            "analysis_status": "Basic structural analysis completed"
        }

    def prepare_synthesis_context(self, state) -> Dict[str, Any]:
        """
        Prepare context for response synthesis with appropriate data sampling.
        """
        logger.info("📋 Preparing synthesis context")
        
        raw_data = state.get('discovered_data', [])
        intent = state.get('intent', 'unknown')
        
        # Sample raw data based on intent and size
        sampled_data = self._sample_raw_data(raw_data, intent, max_samples=25)
        
        # Prepare context structure
        context_data = {
            'sampled_raw_data': sampled_data,
            'total_raw_count': len(raw_data),
            'context_size': len(json.dumps(sampled_data))
        }
        
        # Compress context if too large
        if context_data['context_size'] > 50000:  # 50KB threshold
            context_data = self._compress_context(context_data, intent)
        
        logger.info(f"✅ Synthesis context prepared: {context_data['context_size']} chars, "
                   f"{len(context_data['sampled_raw_data'])} items")
        
        return context_data

    def _sample_raw_data(self, raw_data: List[Dict], intent: str, max_samples: int = 25) -> List[Dict]:
        """
        Sample raw data intelligently based on intent and data characteristics.
        """
        if len(raw_data) <= max_samples:
            return raw_data
        
        logger.info(f"📊 Sampling {len(raw_data)} items down to {max_samples} for {intent} intent")
        
        # Intent-based sampling strategy
        if intent == 'lookup':
            # For lookup queries, prioritize exact matches and relevant content
            sampled = []
            
            # First priority: Items with content/body
            items_with_content = [item for item in raw_data if item.get('body') or item.get('value') or item.get('documentation')]
            sampled.extend(items_with_content[:max_samples // 2])
            
            # Second priority: Items with names matching query terms
            remaining_slots = max_samples - len(sampled)
            if remaining_slots > 0:
                remaining_items = [item for item in raw_data if item not in sampled]
                sampled.extend(remaining_items[:remaining_slots])
                
        elif intent == 'architectural':
            # For architectural queries, prioritize structural information
            sampled = []
            
            # Prioritize different node types
            functions = [item for item in raw_data if 'function' in str(item.get('type_kind', '')).lower()]
            types = [item for item in raw_data if any(t in str(item.get('type_kind', '')).lower() for t in ['class', 'struct', 'type'])]
            relationships = [item for item in raw_data if 'relationship' in str(item).lower()]
            
            # Distribute samples across categories
            samples_per_category = max_samples // 3
            sampled.extend(functions[:samples_per_category])
            sampled.extend(types[:samples_per_category])
            sampled.extend(relationships[:samples_per_category])
            
            # Fill remaining slots
            remaining_slots = max_samples - len(sampled)
            if remaining_slots > 0:
                remaining_items = [item for item in raw_data if item not in sampled]
                sampled.extend(remaining_items[:remaining_slots])
                
        else:
            # Default: Take first N items and some from the end for variety
            mid_point = len(raw_data) // 2
            sampled = raw_data[:max_samples // 2] + raw_data[mid_point:mid_point + max_samples // 4] + raw_data[-max_samples // 4:]
        
        return sampled[:max_samples]

    def _compress_context(self, context: Dict[str, Any], intent: str) -> Dict[str, Any]:
        """
        Compress context data when it exceeds size limits.
        """
        logger.warning(f"⚠️ Compressing context (was {context['context_size']} chars)")
        
        # More aggressive sampling
        max_items = 15 if intent == 'lookup' else 20
        compressed_data = context['sampled_raw_data'][:max_items]
        
        # Remove verbose fields from each item
        for item in compressed_data:
            # Keep essential fields, remove verbose ones
            verbose_fields = ['body', 'full_text', 'raw_content', 'documentation']
            for field in verbose_fields:
                if field in item and len(str(item[field])) > 200:
                    item[field] = str(item[field])[:200] + "...[truncated]"
        
        compressed_context = {
            'sampled_raw_data': compressed_data,
            'total_raw_count': context['total_raw_count'],
            'context_size': len(json.dumps(compressed_data)),
            'compression_applied': True
        }
        
        logger.info(f"✅ Context compressed to {compressed_context['context_size']} chars")
        return compressed_context

    def format_discovery_research_for_query_generation(self, discovery_research) -> str:
        """
        Format discovery research insights for query generation guidance.
        """
        if not discovery_research:
            return "No discovery research available - this is initial exploration."
        
        guidance_parts = []
        
        # Schema analysis insights
        schema_analysis = discovery_research.get('schema_analysis')
        if schema_analysis:
            relevant_nodes = schema_analysis.relevant_node_types if hasattr(schema_analysis, 'relevant_node_types') else schema_analysis.get('relevant_node_types', [])
            if relevant_nodes:
                guidance_parts.append(f"**RESEARCH IDENTIFIED RELEVANT NODES**: {', '.join(relevant_nodes)}")
            
            data_candidates = schema_analysis.data_storage_candidates if hasattr(schema_analysis, 'data_storage_candidates') else schema_analysis.get('data_storage_candidates', {})
            if data_candidates:
                content_attrs = data_candidates.get('content_attributes', [])
                if content_attrs:
                    guidance_parts.append(f"**CONTENT LIKELY STORED IN**: {', '.join(content_attrs)} attributes")
        
        # Hypothesis insights
        hypotheses = discovery_research.get('hypotheses', [])
        if hypotheses:
            high_likelihood = []
            for h in hypotheses:
                likelihood = h.likelihood if hasattr(h, 'likelihood') else h.get('likelihood')
                if likelihood == 'high':
                    high_likelihood.append(h)
            
            if high_likelihood:
                guidance_parts.append("**HIGH-LIKELIHOOD HYPOTHESES**:")
                for h in high_likelihood:
                    hypothesis_text = h.hypothesis if hasattr(h, 'hypothesis') else h.get('hypothesis', 'Unknown')
                    guidance_parts.append(f"- {hypothesis_text}")
        
        # Execution plan insights
        execution_plan = discovery_research.get('execution_plan')
        if execution_plan:
            fallbacks = execution_plan.fallback_strategies if hasattr(execution_plan, 'fallback_strategies') else execution_plan.get('fallback_strategies', [])
            if fallbacks:
                guidance_parts.append(f"**AVAILABLE FALLBACK STRATEGIES**: {', '.join(fallbacks[:2])}")
            
            termination = execution_plan.termination_criteria if hasattr(execution_plan, 'termination_criteria') else execution_plan.get('termination_criteria', [])
            if termination:
                guidance_parts.append(f"**RESEARCH TERMINATION CRITERIA**: {termination[0] if termination else 'None'}")
        
        return '\n'.join(guidance_parts) if guidance_parts else "Discovery research completed - use insights to guide targeted queries."

    def format_discovery_research_for_evaluation(self, discovery_research) -> str:
        """
        Format discovery research insights for sufficiency evaluation guidance.
        """
        if not discovery_research:
            return "No discovery research available - standard evaluation applies."
        
        guidance_parts = []
        
        # Check termination criteria from execution plan
        execution_plan = discovery_research.get('execution_plan')
        if execution_plan:
            termination_criteria = execution_plan.termination_criteria if hasattr(execution_plan, 'termination_criteria') else execution_plan.get('termination_criteria', [])
            if termination_criteria:
                guidance_parts.append("**RESEARCH-DEFINED TERMINATION CRITERIA**:")
                for criterion in termination_criteria:
                    guidance_parts.append(f"- {criterion}")
                
                guidance_parts.append("\n**EVALUATION GUIDANCE**: Check if any of the above criteria are met by current query results.")
        
        # Include research expectations for comparison
        hypotheses = discovery_research.get('hypotheses', [])
        if hypotheses:
            high_likelihood = []
            for h in hypotheses:
                likelihood = h.likelihood if hasattr(h, 'likelihood') else h.get('likelihood')
                if likelihood == 'high':
                    high_likelihood.append(h)
            
            if high_likelihood:
                guidance_parts.append("\n**RESEARCH EXPECTATIONS TO VALIDATE**:")
                for h in high_likelihood:
                    hypothesis_text = h.hypothesis if hasattr(h, 'hypothesis') else h.get('hypothesis', 'Unknown')
                    reasoning_text = h.reasoning if hasattr(h, 'reasoning') else h.get('reasoning', 'No reasoning provided')
                    guidance_parts.append(f"- Expected: {hypothesis_text}")
                    guidance_parts.append(f"  Reason: {reasoning_text}")
        
        # Add strategy-specific guidance
        strategies = discovery_research.get('strategies', [])
        if strategies:
            primary_strategy = strategies[0] if strategies else {}
            expected_queries = primary_strategy.expected_query_count if hasattr(primary_strategy, 'expected_query_count') else primary_strategy.get('expected_query_count', 0)
            if expected_queries > 0:
                guidance_parts.append(f"\n**RESEARCH EXPECTED ~{expected_queries} QUERIES** - consider this when evaluating if exploration is complete.")
        
        return '\n'.join(guidance_parts) if guidance_parts else "Discovery research completed - standard sufficiency evaluation applies."