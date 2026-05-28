"""
Intent Classification Framework for Advanced Graph RAG
Generalized intent recognition system using pattern matching with LLM fallback
"""

from typing import Dict, List, Any, Optional
import re


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
    
    def __init__(self, llm_service=None):
        self.llm_service = llm_service
        
        # Additional pattern matching for more precise classification
        self.advanced_patterns = {
            "quantitative": [
                r'\bhow many\b.*\b(?:lines?|methods?|functions?|classes?|variables?)\b',
                r'\bcount\b.*\b(?:of|the)\b',
                r'\bnumber of\b',
                r'\btotal\b.*\b(?:lines?|methods?|functions?)\b'
            ],
            "structural": [
                r'\bwhat (?:methods?|functions?)\b.*\b(?:does|has|contains?)\b',
                r'\blist\b.*\b(?:all|the)\b.*\b(?:methods?|functions?|classes?)\b',
                r'\bshow me\b.*\b(?:methods?|functions?|structure)\b',
                r'\bwhich (?:methods?|functions?)\b'
            ],
            "relational": [
                r'\b(?:what|which)\b.*\b(?:calls?|uses?|depends? on|implements?|inherits?)\b',
                r'\b(?:calls?|calling|invokes?|invoking)\b',
                r'\bimplements?\b.*\binterface\b',
                r'\binherits? from\b'
            ],
            "locational": [
                r'\bwhere is\b',
                r'\bin which (?:file|class|method)\b',
                r'\bfind\b.*\b(?:in|within)\b',
                r'\blocate\b.*\b(?:in|within)\b'
            ]
        }
    
    async def classify_intent(self, user_query: str) -> Dict[str, Any]:
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
        # Primary: Advanced pattern matching
        advanced_match = self._advanced_pattern_matching(user_query)
        if advanced_match and advanced_match["confidence"] >= 0.7:
            return advanced_match
        
        # Secondary: Basic keyword matching
        basic_match = self._basic_keyword_matching(user_query)
        
        # Choose best match or use LLM fallback
        best_match = advanced_match if advanced_match and advanced_match["confidence"] > basic_match["confidence"] else basic_match
        
        # Fallback: LLM classification for novel patterns
        if not best_match or best_match["confidence"] < 0.3:
            if self.llm_service:
                try:
                    llm_match = await self._llm_classify_intent(user_query)
                    if llm_match and llm_match.get("confidence", 0) > best_match.get("confidence", 0):
                        best_match = llm_match
                except Exception as e:
                    # LLM classification failed, use best available match
                    pass
        
        # Ensure minimum structure
        if not best_match:
            best_match = {
                "type": "unknown",
                "confidence": 0.1,
                "analysis_type": "general_analysis",
                "response_format": "general_response",
                "instructions": "Provide a general analysis of the code query."
            }
        
        return best_match
    
    def _advanced_pattern_matching(self, user_query: str) -> Optional[Dict[str, Any]]:
        """Advanced regex-based pattern matching for higher precision"""
        query_lower = user_query.lower()
        best_match = None
        max_score = 0
        
        for intent_type, patterns in self.advanced_patterns.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, query_lower)
                score += len(matches) * 2  # Weight regex matches higher
            
            if score > max_score:
                max_score = score
                config = self.INTENT_PATTERNS[intent_type]
                confidence = min(score / len(patterns), 1.0)  # Normalize confidence
                
                best_match = {
                    "type": intent_type,
                    "confidence": confidence,
                    "analysis_type": config["analysis_type"],
                    "response_format": config["response_format"],
                    "instructions": config["instructions"],
                    "matching_method": "advanced_patterns"
                }
        
        return best_match
    
    def _basic_keyword_matching(self, user_query: str) -> Dict[str, Any]:
        """Basic keyword matching as implemented in the original pattern"""
        query_lower = user_query.lower()
        best_match = None
        max_score = 0
        
        for intent_type, config in self.INTENT_PATTERNS.items():
            score = sum(1 for keyword in config["keywords"] if keyword in query_lower)
            if score > max_score:
                max_score = score
                confidence = score / len(config["keywords"])
                best_match = {
                    "type": intent_type,
                    "confidence": confidence,
                    "analysis_type": config["analysis_type"],
                    "response_format": config["response_format"],
                    "instructions": config["instructions"],
                    "matching_method": "basic_keywords"
                }
        
        return best_match or {
            "type": "unknown",
            "confidence": 0.0,
            "analysis_type": "general_analysis",
            "response_format": "general_response",
            "instructions": "Provide a general analysis of the code query.",
            "matching_method": "fallback"
        }
    
    async def _llm_classify_intent(self, user_query: str) -> Optional[Dict[str, Any]]:
        """LLM-based intent classification for novel queries"""
        if not self.llm_service:
            return None
        
        system_prompt = f"""You are an expert at classifying code analysis queries by intent.

AVAILABLE INTENT TYPES:
{self._format_intent_types_for_llm()}

Classify this query: "{user_query}"

Return JSON with:
- type: One of [quantitative, structural, relational, comparative, locational, behavioral, unknown]
- confidence: Float 0.0-1.0 indicating classification confidence
- analysis_type: The specific analysis approach needed
- response_format: Expected response format
- instructions: Specific instructions for handling this intent
- reasoning: Brief explanation of classification decision

Focus on the specific action or information the user is requesting."""
        
        try:
            response = await self.llm_service.generate_response(system_prompt)
            content = response.content.strip()
            
            # Extract JSON from LLM response
            import json
            if content.startswith("```json"):
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
            elif content.startswith("```"):
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                if json_end != -1:
                    content = content[json_start:json_end].strip()
            
            llm_result = json.loads(content)
            
            # Validate and normalize LLM result
            intent_type = llm_result.get("type", "unknown")
            if intent_type in self.INTENT_PATTERNS:
                config = self.INTENT_PATTERNS[intent_type]
                return {
                    "type": intent_type,
                    "confidence": min(max(llm_result.get("confidence", 0.5), 0.0), 1.0),
                    "analysis_type": llm_result.get("analysis_type", config["analysis_type"]),
                    "response_format": llm_result.get("response_format", config["response_format"]),
                    "instructions": llm_result.get("instructions", config["instructions"]),
                    "matching_method": "llm_enhanced",
                    "llm_reasoning": llm_result.get("reasoning", "")
                }
            else:
                return {
                    "type": "unknown",
                    "confidence": 0.5,
                    "analysis_type": "general_analysis",
                    "response_format": "general_response",
                    "instructions": "Provide a general analysis of the code query.",
                    "matching_method": "llm_fallback",
                    "llm_reasoning": llm_result.get("reasoning", "")
                }
                
        except Exception as e:
            # LLM classification failed
            return None
    
    def _format_intent_types_for_llm(self) -> str:
        """Format intent types for LLM prompt"""
        formatted = ""
        for intent_type, config in self.INTENT_PATTERNS.items():
            formatted += f"\n{intent_type.upper()}:\n"
            formatted += f"  - Keywords: {', '.join(config['keywords'][:3])}...\n"
            formatted += f"  - Analysis: {config['analysis_type']}\n"
            formatted += f"  - Format: {config['response_format']}\n"
        return formatted
    
    def get_intent_statistics(self) -> Dict[str, Any]:
        """Get statistics about available intent types"""
        return {
            "total_intent_types": len(self.INTENT_PATTERNS),
            "intent_types": list(self.INTENT_PATTERNS.keys()),
            "total_keywords": sum(len(config["keywords"]) for config in self.INTENT_PATTERNS.values()),
            "advanced_patterns": sum(len(patterns) for patterns in self.advanced_patterns.values()),
            "classification_methods": ["advanced_patterns", "basic_keywords", "llm_enhanced", "fallback"]
        }
    
    def validate_intent_result(self, intent_result: Dict[str, Any]) -> bool:
        """Validate that intent classification result has required fields"""
        required_fields = ["type", "confidence", "analysis_type", "response_format", "instructions"]
        return all(field in intent_result for field in required_fields)
    
    def enhance_intent_with_context(self, intent_result: Dict[str, Any], entities: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance intent classification with entity context"""
        enhanced = intent_result.copy()
        
        # Adjust confidence based on entity extraction quality
        entity_count = sum(len(v) if isinstance(v, list) else 1 for v in entities.values() if v)
        if entity_count > 0:
            enhanced["confidence"] = min(enhanced["confidence"] + (entity_count * 0.05), 1.0)
        
        # Add entity-specific instructions
        if entities.get("files") and enhanced["analysis_type"] == "parse_and_count":
            enhanced["instructions"] += f" Focus on the file: {entities['files'][0]}."
        
        if entities.get("concepts"):
            concept_text = ", ".join(entities["concepts"])
            enhanced["instructions"] += f" Pay attention to: {concept_text}."
        
        enhanced["entity_enhanced"] = True
        enhanced["entity_count"] = entity_count
        
        return enhanced