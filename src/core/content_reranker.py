"""
Content Reranker for Advanced Graph RAG
Rank retrieved nodes by relevance and content richness using weighted scoring
"""

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
        
        node_name = node.get("name", node.get("t.name", "")).lower()
        node_file_path = node.get("file_path", node.get("t.file_path", "")).lower()
        
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
        body = node.get("body", node.get("t.body", ""))
        if isinstance(body, str) and len(body) > self.CONTENT_THRESHOLDS["rich_content_min_chars"]:
            score += self.CONTENT_THRESHOLDS["body_content_weight"] * 0.6
        
        # Symbols location scoring  
        symbols_location = node.get("symbols_location", node.get("t.symbols_location", ""))
        if symbols_location and len(str(symbols_location)) > 10:  # Non-empty symbols data
            score += self.CONTENT_THRESHOLDS["symbols_location_weight"] * 0.3
        
        # Structural properties scoring
        structural_props = ["start_point", "end_point", "parameters", "return_type", "fields", "base_list"]
        has_structural = sum(1 for prop in structural_props if node.get(prop) or node.get(f"t.{prop}"))
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
        node_name = node.get("name", node.get("t.name", "")).lower()
        node_file = node.get("file_path", node.get("t.file_path", "")).lower()
        
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
        
        # Check source annotation for proximity hints
        source = node.get("_source", "")
        if source == "seed":
            return 0.9  # Direct from seed query
        elif source == "expansion":
            hops = node.get("_hops", 3)
            if hops == 1:
                return 0.7
            elif hops == 2:
                return 0.4
            else:
                return 0.2
        
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
            body = node.get("body", node.get("t.body", ""))
            if isinstance(body, str) and len(body) > 50:  # Has parseable content
                return 1.0
            else:
                return 0.3
        
        # Structural intent alignment  
        elif analysis_type == "extract_elements":
            if (node.get("symbols_location") or node.get("t.symbols_location") or 
                node.get("fields") or node.get("t.fields") or 
                node.get("parameters") or node.get("t.parameters")):
                return 1.0
            else:
                return 0.3
        
        # Relational intent alignment
        elif analysis_type == "traverse_relationships":
            if (node.get("base_list") or node.get("t.base_list") or 
                node.get("type_kind") in ["class", "interface"]):
                return 1.0
            else:
                return 0.3
        
        # Locational intent alignment
        elif analysis_type == "entity_location":
            if (node.get("file_path") or node.get("t.file_path") or
                node.get("start_point") or node.get("t.start_point")):
                return 1.0
            else:
                return 0.3
        
        # Comparative intent alignment
        elif analysis_type == "multi_entity_analysis":
            if (node.get("body") or node.get("t.body") or
                node.get("base_list") or node.get("t.base_list")):
                return 0.8
            else:
                return 0.4
        
        # Behavioral intent alignment
        elif analysis_type == "execution_flow":
            if (node.get("body") or node.get("t.body") or
                node.get("parameters") or node.get("t.parameters")):
                return 0.9
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