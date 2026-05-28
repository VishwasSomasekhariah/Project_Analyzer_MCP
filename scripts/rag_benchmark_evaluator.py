#!/usr/bin/env python3
"""
RAGAS-Focused RAG Benchmarking Evaluator

This script produces a comprehensive benchmarking score for RAG retrieval systems
using RAGAS methodology with LLM-based evaluation and evidence-based ground truth.

RAGAS Core Metrics (100 points):
1. Context Precision (25 points): Relevance of retrieved context to query
2. Context Recall (25 points): Completeness of relevant context retrieved  
3. Faithfulness (25 points): Factual consistency with ground truth
4. Answer Relevancy (25 points): How well response addresses query intent

Final Score: 0-100 scale with LLM semantic evaluation against ground truth
"""

import pandas as pd
import numpy as np
import json
import re
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
from datetime import datetime
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import warnings
warnings.filterwarnings('ignore')
import openai
import os

class RAGBenchmarkEvaluator:
    def __init__(self, csv_file_path: str):
        """Initialize the RAG benchmarking evaluator."""
        self.csv_file_path = csv_file_path
        self.df = None
        self.ground_truth = {}
        # RAGAS-focused weights - pure RAG content quality metrics
        self.benchmark_weights = {
            'context_precision': 0.25,    # 25% - Context relevance 
            'context_recall': 0.25,       # 25% - Context completeness
            'faithfulness': 0.25,         # 25% - Factual consistency
            'answer_relevancy': 0.25,     # 25% - Query alignment
        }
        
        # Define actual HelloWorldApp codebase for ground truth
        self.actual_codebase = {
            'classes': ['Program', 'Manager', 'WorkerA', 'WorkerB', 'WorkerC', 'WorkerFactory', 'Helper'],
            'interfaces': ['INotifier', 'IWorker'],
            'methods': ['Main', 'Run', 'Notify', 'Process', 'CreateWorkers', 'FormatMessage'],
            'patterns': ['Factory Pattern', 'Observer Pattern', 'Strategy Pattern', 'Dependency Injection'],
            'architecture': ['Manager', 'Worker', 'Factory', 'Notification System'],
            'files': ['Program.cs', 'Manager.cs', 'WorkerA.cs', 'WorkerB.cs', 'WorkerC.cs', 
                     'WorkerFactory.cs', 'INotifier.cs', 'IWorker.cs', 'Helper.cs'],
            'dependencies': ['System', 'System.Collections.Generic', 'HelloWorldApp.Utilities'],
            'namespaces': ['HelloWorldApp', 'HelloWorldApp.Utilities']
        }
        
        self.load_data()
        # Try to load ground truth from CSV, fallback to hardcoded if needed
        try:
            self.load_ground_truth_from_csv()
        except Exception as e:
            print(f"⚠️  Failed to load ground truth from CSV: {e}")
            print("📋 Using fallback ground truth creation...")
            self.create_ground_truth_fallback()
        
        # Setup LLM client for evaluation
        self.llm_available = self.setup_llm_client()
    
    def load_data(self):
        """Load the comparative analysis data."""
        try:
            self.df = pd.read_csv(self.csv_file_path)
            print(f"✓ Loaded {len(self.df)} scenarios from {self.csv_file_path}")
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            raise
    
    def load_ground_truth_from_csv(self):
        """Load ground truth from CSV file"""
        ground_truth_file = "/opt/Test_Suite_Benchmarking/ground_truths.csv"
        
        if not Path(ground_truth_file).exists():
            raise FileNotFoundError(f"Ground truth file not found: {ground_truth_file}")
        
        # Read the ground truth CSV
        df = pd.read_csv(ground_truth_file)
        
        for _, row in df.iterrows():
            query_id = row['query_id']
            self.ground_truth[query_id] = {
                'expected_elements': [
                    row['user_query'],
                    row['query_category'],
                    row['query_subcategory'],
                    row['scenario_type']
                ],
                'expected_response': row['ground_truth_response'],
                'category': row['query_category'],
                'subcategory': row['query_subcategory'],
                'type': row['scenario_type']
            }
        
        print(f"✓ Loaded ground truth for {len(self.ground_truth)} scenarios from CSV")
        return
    
    def setup_llm_client(self):
        """Setup OpenAI client for LLM-based evaluation."""
        try:
            # Try to get API key from environment
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                print("⚠️  No OPENAI_API_KEY found. Using fallback evaluation methods.")
                return None
            
            # Initialize OpenAI client
            openai.api_key = api_key
            return True
            
        except Exception as e:
            print(f"⚠️  Failed to setup OpenAI client: {e}")
            return None
    
    def llm_judge_score(self, prompt: str, max_retries: int = 2) -> float:
        """Use LLM to judge and return a score between 0-1."""
        try:
            from openai import OpenAI
            client = OpenAI()
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert evaluator. Return only a decimal score between 0.0 and 1.0 based on the evaluation criteria provided."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=50,
                temperature=0.1
            )
            
            # Extract score from response
            score_text = response.choices[0].message.content.strip()
            
            # Try to parse score
            import re
            score_match = re.search(r'(\d+\.?\d*)', score_text)
            if score_match:
                score = float(score_match.group(1))
                # Normalize to 0-1 if it's in 0-100 range
                if score > 1.0:
                    score = score / 100.0
                return min(max(score, 0.0), 1.0)  # Clamp between 0-1
            else:
                return 0.0
                
        except Exception as e:
            print(f"⚠️  LLM evaluation error: {e}")
            return 0.0
    
    def llm_evaluate_all_metrics(self, query: str, retrieved_response: str, ground_truth_response: str) -> Dict[str, float]:
        """Use LLM to evaluate all metrics in a single call for efficiency."""
        
        combined_prompt = f"""
        Query: {query}
        Retrieved Answer: {retrieved_response[:1500]}...
        Ground Truth Reference: {ground_truth_response[:1500]}...
        
        Evaluate the retrieved answer against the ground truth across multiple dimensions:
        
        1. PRECISION: What percentage of information in the retrieved answer is accurate and relevant? (0.0-1.0)
        2. RECALL: What percentage of important ground truth information is covered? (0.0-1.0) 
        3. FAITHFULNESS: How factually consistent is the answer with ground truth? (0.0-1.0)
        4. ANSWER_RELEVANCY: How well does the answer address the query intent? (0.0-1.0)
        
        Return EXACTLY this format:
        PRECISION: 0.XX
        RECALL: 0.XX
        FAITHFULNESS: 0.XX
        ANSWER_RELEVANCY: 0.XX
        """
        
        try:
            from openai import OpenAI
            client = OpenAI()
            
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are an expert evaluator. Return scores in the exact format requested."},
                    {"role": "user", "content": combined_prompt}
                ],
                max_tokens=200,
                temperature=0.1
            )
            
            # Parse the structured response
            response_text = response.choices[0].message.content.strip()
            metrics = {}
            
            for line in response_text.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    try:
                        score = float(value.strip())
                        metrics[key] = min(max(score, 0.0), 1.0)  # Clamp 0-1
                    except ValueError:
                        continue
            
            # Ensure all metrics are present with defaults
            return {
                'precision': metrics.get('precision', 0.0),
                'recall': metrics.get('recall', 0.0), 
                'faithfulness': metrics.get('faithfulness', 0.0),
                'answer_relevancy': metrics.get('answer_relevancy', 0.0)
            }
            
        except Exception as e:
            print(f"⚠️  LLM evaluation error: {e}")
            return {
                'precision': 0.0,
                'recall': 0.0,
                'faithfulness': 0.0, 
                'answer_relevancy': 0.0
            }
    
    def llm_evaluate_faithfulness(self, query: str, retrieved_response: str, ground_truth_response: str) -> float:
        """Use LLM to evaluate faithfulness compared to ground truth."""
        
        faithfulness_prompt = f"""
        Query: {query}
        Retrieved Answer: {retrieved_response[:2000]}...
        Ground Truth Reference: {ground_truth_response[:2000]}...
        
        Evaluate FAITHFULNESS: How factually consistent is the retrieved answer with the ground truth reference?
        
        Consider:
        - Does the retrieved answer contradict any facts in the ground truth?
        - Are the claims and statements aligned with ground truth?
        - Is the technical information accurate according to ground truth?
        
        Return a decimal score between 0.0 (many contradictions) and 1.0 (perfectly faithful to ground truth).
        """
        
        return self.llm_judge_score(faithfulness_prompt)
    
    def llm_evaluate_answer_relevancy(self, query: str, retrieved_response: str, ground_truth_response: str) -> float:
        """Use LLM to evaluate answer relevancy compared to ground truth."""
        
        relevancy_prompt = f"""
        Query: {query}
        Retrieved Answer: {retrieved_response[:2000]}...
        Ground Truth Reference: {ground_truth_response[:2000]}...
        
        Evaluate ANSWER RELEVANCY: How well does the retrieved answer address the specific query compared to the ground truth?
        
        Consider:
        - Does the retrieved answer directly address the query intent?
        - Is the level of detail appropriate for the question?
        - Are there irrelevant tangents or missing focus areas compared to ground truth?
        
        Return a decimal score between 0.0 (completely irrelevant) and 1.0 (perfectly relevant to query).
        """
        
        return self.llm_judge_score(relevancy_prompt)

    def create_ground_truth_fallback(self):
        """Fallback ground truth creation if CSV fails"""
        # Define expected elements for each scenario based on actual codebase
        ground_truth_mapping = {
            # Technical Category
            'T001': self.actual_codebase['classes'] + self.actual_codebase['interfaces'] + self.actual_codebase['architecture'],
            'T002': self.actual_codebase['patterns'] + ['Factory', 'Observer', 'Strategy'],
            'T003': self.actual_codebase['dependencies'] + ['relationships', 'coupling'],
            'T004': self.actual_codebase['interfaces'] + ['inheritance', 'hierarchy'],
            'T005': self.actual_codebase['methods'] + ['complexity', 'cyclomatic'],
            
            # Functional Category  
            'F001': ['Manager', 'Worker', 'Process', 'business logic', 'coordination'],
            'F002': ['Manager', 'WorkerFactory', 'data flow', 'communication'],
            'F003': ['Manager', 'INotifier', 'coordination', 'callback'],
            'F004': ['WorkerFactory', 'CreateWorkers', 'Factory Pattern'],
            'F005': ['INotifier', 'Notify', 'Observer Pattern', 'callback'],
            
            # Non-Functional Category
            'NF001': ['error handling', 'exception', 'try-catch'],
            'NF002': ['code quality', 'maintainability', 'readability'],
            'NF003': ['performance', 'optimization', 'efficiency'],
            'NF004': ['security', 'vulnerabilities', 'safety'],
            'NF005': ['maintainability', 'structure', 'clean code'],
            'NF006': ['testing', 'unit tests', 'test coverage'],
            
            # Additional categories
            'M001': self.actual_codebase['classes'] + ['async', 'await', 'refactoring'],
            'M002': ['error handling', 'try-catch', 'logging'],
            'M003': ['logging', 'structured logging', 'ILogger'],
            'M004': ['configuration', 'appsettings', 'IConfiguration'],
            'M005': ['dependency injection', 'DI container', 'IoC'],
            
            'FA001': ['priority system', 'worker priority', 'queue'],
            'FA002': ['worker status', 'tracking', 'monitoring'],
            'FA003': ['result collection', 'aggregation', 'results'],
            'FA004': ['parallel processing', 'concurrency', 'Task'],
            'FA005': ['worker lifecycle', 'management', 'lifecycle'],
            
            'MOD001': ['async', 'await', 'Task', 'NET 9'],
            'MOD002': ['modern patterns', 'best practices', 'design patterns'],
            'MOD003': ['web API', 'REST', 'HTTP', 'API'],
            'MOD004': ['cloud native', 'microservices', 'containers'],
            'MOD005': ['reactive patterns', 'observable', 'reactive'],
            
            'BUG001': ['null reference', 'NullReferenceException', 'null checks'],
            'BUG002': ['resource leaks', 'dispose', 'IDisposable'],
            'BUG003': ['concurrency', 'thread safety', 'race conditions'],
            
            'INT001': ['database', 'data access', 'persistence'],
            'INT002': ['message queue', 'messaging', 'queue'],
            'INT003': ['external API', 'HTTP', 'REST', 'integration']
        }
        
        # Create ground truth for each scenario
        for _, row in self.df.iterrows():
            query_id = row['query_id']
            if query_id in ground_truth_mapping:
                self.ground_truth[query_id] = {
                    'expected_elements': ground_truth_mapping[query_id],
                    'query': row['user_query'],
                    'category': row['query_category'],
                    'subcategory': row['query_subcategory']
                }
            else:
                # Create generic ground truth based on category
                category = row['query_category']
                if category == 'Technical':
                    elements = self.actual_codebase['classes'] + self.actual_codebase['interfaces']
                elif category == 'Functional':
                    elements = self.actual_codebase['methods'] + ['business logic']
                elif category == 'Non-Functional':
                    elements = ['quality', 'performance', 'security']
                else:
                    elements = self.actual_codebase['classes'] + self.actual_codebase['methods']
                
                self.ground_truth[query_id] = {
                    'expected_elements': elements,
                    'query': row['user_query'],
                    'category': category,
                    'subcategory': row['query_subcategory']
                }
        
        print(f"✓ Created ground truth for {len(self.ground_truth)} scenarios")
    
    def extract_analysis_from_response(self, response: str) -> str:
        """Extract the actual analysis content from JSON response."""
        if pd.isna(response) or not response:
            return ""
        
        try:
            # Try to parse as JSON
            if isinstance(response, str) and response.strip().startswith('{'):
                parsed = json.loads(response)
                
                # Vector approach: Extract ai_analysis field
                if 'ai_analysis' in parsed:
                    return parsed['ai_analysis']
                
                # CPG approach: Extract from results list
                elif 'results' in parsed and isinstance(parsed['results'], list):
                    if parsed['results']:
                        # Concatenate all results into one analysis
                        results_text = []
                        for result in parsed['results']:
                            if isinstance(result, dict):
                                # Extract text from result dict
                                if 'analysis' in result:
                                    results_text.append(result['analysis'])
                                elif 'content' in result:
                                    results_text.append(result['content'])
                                elif 'text' in result:
                                    results_text.append(result['text'])
                                else:
                                    # Convert entire result to string
                                    results_text.append(str(result))
                            else:
                                results_text.append(str(result))
                        return '\n'.join(results_text)
                    else:
                        return "No results found"
                
                # Comprehensive approach: Extract from results dict
                elif 'results' in parsed and isinstance(parsed['results'], dict):
                    results = parsed['results']
                    analysis_parts = []
                    
                    # Common fields that might contain analysis
                    analysis_fields = ['analysis', 'summary', 'ai_analysis', 'content', 'description']
                    for field in analysis_fields:
                        if field in results and results[field]:
                            analysis_parts.append(str(results[field]))
                    
                    # If no specific analysis fields, convert entire results to string
                    if not analysis_parts:
                        analysis_parts.append(str(results))
                    
                    return '\n'.join(analysis_parts)
                
                # Fallback to raw_response if available
                elif 'raw_response' in parsed:
                    return parsed['raw_response']
                
                # Last resort: convert entire JSON to string
                else:
                    return str(parsed)
            
            # If not JSON, return as-is
            return str(response)
            
        except json.JSONDecodeError:
            # If JSON parsing fails, return original response
            return str(response)
    
    def extract_code_elements(self, response: str) -> List[str]:
        """Extract code elements from response using advanced patterns."""
        if pd.isna(response) or not response:
            return []
        
        response_str = str(response).lower()
        extracted = []
        
        # Check for actual codebase elements
        all_elements = []
        for element_type, elements in self.actual_codebase.items():
            all_elements.extend([elem.lower() for elem in elements])
        
        # Find matches in response
        for element in all_elements:
            if element in response_str:
                extracted.append(element)
        
        # Extract code patterns
        code_patterns = [
            r'\b(class|interface|struct|enum)\s+(\w+)',
            r'\b(method|function)\s+(\w+)',
            r'\b(\w+Factory|\w+Manager|\w+Worker)',
            r'\b(I\w+)',  # Interface patterns
            r'`([^`]+)`',  # Code in backticks
            r'\b(public|private|protected|static)\s+\w+\s+(\w+)',
        ]
        
        for pattern in code_patterns:
            matches = re.findall(pattern, response_str, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    extracted.extend([m for m in match if m and len(m) > 2])
                else:
                    extracted.append(match)
        
        # Add important keywords
        important_keywords = [
            'factory', 'observer', 'strategy', 'pattern', 'manager', 'worker',
            'notification', 'callback', 'inheritance', 'interface', 'method',
            'class', 'function', 'dependency', 'architecture', 'component',
            'async', 'await', 'task', 'performance', 'security', 'quality'
        ]
        
        for keyword in important_keywords:
            if keyword in response_str:
                extracted.append(keyword)
        
        return list(set(extracted))
    
    def calculate_precision_recall(self, retrieved_elements: List[str], expected_elements: List[str]) -> Tuple[float, float]:
        """Calculate precision and recall for retrieved elements."""
        if not retrieved_elements:
            return 0.0, 0.0
        
        retrieved_set = set([elem.lower() for elem in retrieved_elements])
        expected_set = set([elem.lower() for elem in expected_elements])
        
        intersection = retrieved_set.intersection(expected_set)
        
        precision = len(intersection) / len(retrieved_set) if retrieved_set else 0.0
        recall = len(intersection) / len(expected_set) if expected_set else 0.0
        
        return precision, recall
    
    def calculate_semantic_similarity(self, query: str, response: str) -> float:
        """Calculate semantic similarity between query and response."""
        if pd.isna(response) or not response:
            return 0.0
        
        try:
            vectorizer = TfidfVectorizer(stop_words='english', max_features=1000)
            texts = [query, str(response)]
            tfidf_matrix = vectorizer.fit_transform(texts)
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return similarity
        except:
            return 0.0
    
    def evaluate_context_precision(self, query: str, response: str, expected_elements: List[str]) -> float:
        """Evaluate context precision - relevance of retrieved context."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response).lower()
        query_str = query.lower()
        
        # Check query keyword overlap
        query_keywords = set(re.findall(r'\b\w+\b', query_str))
        response_keywords = set(re.findall(r'\b\w+\b', response_str))
        
        keyword_overlap = len(query_keywords.intersection(response_keywords))
        keyword_precision = keyword_overlap / len(query_keywords) if query_keywords else 0.0
        
        # Check expected elements mention
        expected_mentions = sum(1 for elem in expected_elements if elem.lower() in response_str)
        expected_precision = expected_mentions / len(expected_elements) if expected_elements else 0.0
        
        return (keyword_precision + expected_precision) / 2
    
    def evaluate_context_recall(self, response: str, expected_elements: List[str]) -> float:
        """Evaluate context recall - completeness of expected content."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response).lower()
        captured_elements = sum(1 for elem in expected_elements if elem.lower() in response_str)
        
        return captured_elements / len(expected_elements) if expected_elements else 0.0
    
    def evaluate_faithfulness(self, response: str) -> float:
        """Evaluate faithfulness - factual accuracy and structure."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response)
        
        # Structure indicators (higher faithfulness)
        structure_indicators = [
            response_str.count('{') + response_str.count('}'),
            response_str.count('```'),
            response_str.count('class ') + response_str.count('interface '),
            response_str.count('\n'),
            len(re.findall(r'MATCH.*RETURN', response_str, re.IGNORECASE))
        ]
        
        structure_score = min(sum(structure_indicators) / 20, 1.0)
        
        # Uncertainty penalty
        uncertainty_phrases = [
            'might', 'could', 'possibly', 'perhaps', 'maybe', 'seems like',
            'appears to', 'likely', 'probably', 'potentially'
        ]
        
        uncertainty_count = sum(1 for phrase in uncertainty_phrases if phrase in response_str.lower())
        uncertainty_penalty = min(uncertainty_count * 0.1, 0.5)
        
        return max(0.0, min(1.0, structure_score - uncertainty_penalty))
    
    def evaluate_structured_output(self, response: str) -> float:
        """Evaluate how well-structured the response is."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response)
        
        # Structure indicators
        structure_score = 0.0
        
        # JSON structure
        if '{' in response_str and '}' in response_str:
            structure_score += 0.3
        
        # Code blocks
        if '```' in response_str:
            structure_score += 0.2
        
        # Lists or bullet points
        if response_str.count('•') + response_str.count('-') + response_str.count('*') > 2:
            structure_score += 0.2
        
        # Multiple paragraphs
        if response_str.count('\n\n') > 1:
            structure_score += 0.1
        
        # Code elements
        if ('class ' in response_str or 'interface ' in response_str or 
            'method ' in response_str or 'function ' in response_str):
            structure_score += 0.2
        
        return min(1.0, structure_score)
    
    def calculate_response_time_score(self, response_time_ms: float) -> float:
        """Calculate response time score (lower is better)."""
        if pd.isna(response_time_ms) or response_time_ms <= 0:
            return 0.0
        
        # Define thresholds (in milliseconds)
        excellent_threshold = 2000    # < 2 seconds = 1.0
        good_threshold = 10000       # < 10 seconds = 0.7
        acceptable_threshold = 30000  # < 30 seconds = 0.3
        
        if response_time_ms <= excellent_threshold:
            return 1.0
        elif response_time_ms <= good_threshold:
            return 0.7
        elif response_time_ms <= acceptable_threshold:
            return 0.3
        else:
            return 0.1
    
    def evaluate_single_scenario(self, row: pd.Series, approach: str) -> Dict[str, float]:
        """Evaluate a single scenario for a specific approach."""
        query_id = row['query_id']
        query = row['user_query']
        
        # Get response and timing data
        response_col = f'{approach}_response'
        status_col = f'{approach}_status'
        time_col = f'{approach}_response_time_ms'
        
        response = row[response_col]
        status = row[status_col]
        response_time = row[time_col]
        
        # Extract actual analysis from JSON response
        actual_response = self.extract_analysis_from_response(response)
        
        # Get ground truth
        if query_id not in self.ground_truth:
            return {}
        
        ground_truth_response = self.ground_truth[query_id]['expected_response']
        
        # Use LLM-based evaluation if available, otherwise fallback to simple methods
        if self.llm_available and actual_response:
            print(f"🤖 Evaluating {query_id} with LLM...")
            
            # Single LLM call for all metrics (much faster)
            llm_metrics = self.llm_evaluate_all_metrics(query, actual_response, ground_truth_response)
            
            precision = llm_metrics['precision']
            recall = llm_metrics['recall']
            faithfulness = llm_metrics['faithfulness']
            answer_relevancy = llm_metrics['answer_relevancy']
            
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            
            # For context precision/recall, use the same precision/recall scores
            context_precision = precision
            context_recall = recall
            
            # Set retrieved_elements for consistency (not used in LLM path but needed for return)
            retrieved_elements = []
            expected_elements = []
            
        else:
            # Fallback to original methods if LLM not available
            expected_elements = self.ground_truth[query_id]['expected_elements']
            retrieved_elements = self.extract_code_elements(actual_response)
            
            precision, recall = self.calculate_precision_recall(retrieved_elements, expected_elements)
            f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
            
            context_precision = self.evaluate_context_precision(query, actual_response, expected_elements)
            context_recall = self.evaluate_context_recall(actual_response, expected_elements)
            faithfulness = self.evaluate_faithfulness(actual_response)
            answer_relevancy = self.calculate_semantic_similarity(query, actual_response)
        # Only return the 4 core RAGAS metrics that actually matter
        return {
            'context_precision': context_precision,
            'context_recall': context_recall,
            'faithfulness': faithfulness,
            'answer_relevancy': answer_relevancy,
            # Keep these for reporting but don't include in weighted score
            'success_rate': 1.0 if status == 'success' else 0.0,
            'response_time_ms': response_time
        }
    
    def calculate_benchmark_score(self, metrics: Dict[str, float]) -> float:
        """Calculate the weighted benchmark score."""
        if not metrics:
            return 0.0
        
        total_score = 0.0
        for metric, weight in self.benchmark_weights.items():
            if metric in metrics:
                total_score += metrics[metric] * weight
        
        return total_score * 100  # Convert to 0-100 scale
    
    def run_comprehensive_evaluation(self) -> Dict[str, Any]:
        """Run comprehensive evaluation across all approaches."""
        approaches = ['vector', 'cpg', 'comprehensive']
        results = {}
        
        for approach in approaches:
            print(f"🔍 Evaluating {approach} approach...")
            
            approach_results = []
            approach_metrics = []
            
            for _, row in self.df.iterrows():
                scenario_metrics = self.evaluate_single_scenario(row, approach)
                if scenario_metrics:
                    scenario_metrics['query_id'] = row['query_id']
                    scenario_metrics['query_category'] = row['query_category']
                    scenario_metrics['approach'] = approach
                    
                    # Calculate benchmark score for this scenario
                    benchmark_score = self.calculate_benchmark_score(scenario_metrics)
                    scenario_metrics['benchmark_score'] = benchmark_score
                    
                    approach_results.append(scenario_metrics)
                    approach_metrics.append(scenario_metrics)
            
            # Calculate aggregate metrics
            if approach_metrics:
                aggregate_metrics = {}
                for metric in self.benchmark_weights.keys():
                    values = [m[metric] for m in approach_metrics if metric in m]
                    if values:
                        aggregate_metrics[metric] = np.mean(values)
                
                # Calculate overall benchmark score
                overall_benchmark_score = self.calculate_benchmark_score(aggregate_metrics)
                
                results[approach] = {
                    'scenarios': approach_results,
                    'aggregate_metrics': aggregate_metrics,
                    'overall_benchmark_score': overall_benchmark_score,
                    'scenario_count': len(approach_results)
                }
            
            print(f"✓ Evaluated {len(approach_results)} scenarios for {approach}")
        
        return results
    
    def analyze_by_category(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze benchmark scores by query category."""
        category_analysis = {}
        
        for approach, approach_data in results.items():
            scenarios = approach_data['scenarios']
            df_scenarios = pd.DataFrame(scenarios)
            
            category_scores = {}
            for category in df_scenarios['query_category'].unique():
                category_data = df_scenarios[df_scenarios['query_category'] == category]
                
                # Calculate average metrics for this category
                category_metrics = {}
                for metric in self.benchmark_weights.keys():
                    if metric in category_data.columns:
                        category_metrics[metric] = category_data[metric].mean()
                
                # Calculate category benchmark score
                category_benchmark_score = self.calculate_benchmark_score(category_metrics)
                
                category_scores[category] = {
                    'benchmark_score': category_benchmark_score,
                    'scenario_count': len(category_data),
                    'metrics': category_metrics
                }
            
            category_analysis[approach] = category_scores
        
        return category_analysis
    
    def create_benchmark_visualizations(self, results: Dict[str, Any], category_analysis: Dict[str, Any], 
                                      output_dir: str = '/opt/genpod/rag_benchmark_charts'):
        """Create comprehensive benchmark visualization charts."""
        Path(output_dir).mkdir(exist_ok=True)
        plt.style.use('seaborn-v0_8')
        
        # Create comprehensive dashboard
        fig, axes = plt.subplots(2, 3, figsize=(20, 12))
        
        # 1. Overall Benchmark Scores
        approaches = list(results.keys())
        benchmark_scores = [results[app]['overall_benchmark_score'] for app in approaches]
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
        bars = axes[0, 0].bar(approaches, benchmark_scores, color=colors, alpha=0.8)
        axes[0, 0].set_title('Overall RAG Benchmark Scores', fontsize=14, fontweight='bold')
        axes[0, 0].set_ylabel('Benchmark Score (0-100)')
        axes[0, 0].set_ylim(0, 100)
        
        # Add score labels on bars
        for bar, score in zip(bars, benchmark_scores):
            height = bar.get_height()
            axes[0, 0].text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{score:.1f}', ha='center', va='bottom', fontweight='bold')
        
        # 2. Metric Breakdown
        metrics = list(self.benchmark_weights.keys())
        x = np.arange(len(approaches))
        width = 0.15
        
        colors_metrics = plt.cm.tab10(np.linspace(0, 1, len(metrics)))
        
        for i, metric in enumerate(metrics):
            metric_scores = []
            for approach in approaches:
                if metric in results[approach]['aggregate_metrics']:
                    metric_scores.append(results[approach]['aggregate_metrics'][metric] * 100)
                else:
                    metric_scores.append(0)
            
            axes[0, 1].bar(x + i * width, metric_scores, width, 
                          label=metric.replace('_', ' ').title(), 
                          color=colors_metrics[i], alpha=0.8)
        
        axes[0, 1].set_title('Metric Breakdown by Approach', fontsize=14, fontweight='bold')
        axes[0, 1].set_ylabel('Score (0-100)')
        axes[0, 1].set_xlabel('Approach')
        axes[0, 1].set_xticks(x + width * len(metrics) / 2)
        axes[0, 1].set_xticklabels(approaches)
        axes[0, 1].legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        # 3. Category-wise Performance
        if category_analysis:
            categories = list(next(iter(category_analysis.values())).keys())
            x_cat = np.arange(len(categories))
            width_cat = 0.25
            
            for i, approach in enumerate(approaches):
                cat_scores = []
                for category in categories:
                    if category in category_analysis[approach]:
                        cat_scores.append(category_analysis[approach][category]['benchmark_score'])
                    else:
                        cat_scores.append(0)
                
                axes[0, 2].bar(x_cat + i * width_cat, cat_scores, width_cat, 
                              label=approach, color=colors[i], alpha=0.8)
            
            axes[0, 2].set_title('Benchmark Scores by Category', fontsize=14, fontweight='bold')
            axes[0, 2].set_ylabel('Benchmark Score (0-100)')
            axes[0, 2].set_xlabel('Query Category')
            axes[0, 2].set_xticks(x_cat + width_cat)
            axes[0, 2].set_xticklabels(categories, rotation=45, ha='right')
            axes[0, 2].legend()
        
        # 4. Response Time Analysis
        all_scenarios = []
        for approach_data in results.values():
            all_scenarios.extend(approach_data['scenarios'])
        
        df_all = pd.DataFrame(all_scenarios)
        
        response_times = []
        approach_labels = []
        for approach in approaches:
            approach_times = [s['response_time_ms'] / 1000 for s in results[approach]['scenarios'] 
                             if 'response_time_ms' in s and not pd.isna(s['response_time_ms'])]
            response_times.append(approach_times)
            approach_labels.append(approach)
        
        axes[1, 0].boxplot(response_times, labels=approach_labels)
        axes[1, 0].set_title('Response Time Distribution', fontsize=14, fontweight='bold')
        axes[1, 0].set_ylabel('Response Time (seconds)')
        
        # 5. Success Rate Comparison
        success_rates = []
        for approach in approaches:
            scenarios = results[approach]['scenarios']
            success_count = sum(1 for s in scenarios if s['success_rate'] == 1.0)
            success_rates.append((success_count / len(scenarios)) * 100)
        
        bars_success = axes[1, 1].bar(approaches, success_rates, color=colors, alpha=0.8)
        axes[1, 1].set_title('Success Rates by Approach', fontsize=14, fontweight='bold')
        axes[1, 1].set_ylabel('Success Rate (%)')
        axes[1, 1].set_ylim(0, 100)
        
        # Add percentage labels
        for bar, rate in zip(bars_success, success_rates):
            height = bar.get_height()
            axes[1, 1].text(bar.get_x() + bar.get_width()/2., height + 1,
                           f'{rate:.1f}%', ha='center', va='bottom', fontweight='bold')
        
        # 6. Precision vs Recall Scatter
        for i, approach in enumerate(approaches):
            scenarios = results[approach]['scenarios']
            precisions = [s['precision'] for s in scenarios if 'precision' in s]
            recalls = [s['recall'] for s in scenarios if 'recall' in s]
            
            axes[1, 2].scatter(precisions, recalls, label=approach, 
                              color=colors[i], alpha=0.6, s=60)
        
        axes[1, 2].set_title('Precision vs Recall', fontsize=14, fontweight='bold')
        axes[1, 2].set_xlabel('Precision')
        axes[1, 2].set_ylabel('Recall')
        axes[1, 2].legend()
        axes[1, 2].grid(True, alpha=0.3)
        axes[1, 2].set_xlim(0, 1)
        axes[1, 2].set_ylim(0, 1)
        
        plt.tight_layout()
        plt.savefig(f'{output_dir}/rag_benchmark_comprehensive.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Benchmark visualization saved to {output_dir}/rag_benchmark_comprehensive.png")
    
    def print_benchmark_summary(self, results: Dict[str, Any], category_analysis: Dict[str, Any]):
        """Print comprehensive benchmark summary."""
        print("\n" + "="*80)
        print("COMPREHENSIVE RAG BENCHMARK EVALUATION REPORT")
        print("="*80)
        
        print(f"\n📊 Benchmark Overview:")
        print(f"   Total scenarios evaluated: {len(self.ground_truth)}")
        print(f"   Approaches benchmarked: {len(results)}")
        print(f"   Benchmark scale: 0-100 (higher is better)")
        
        print(f"\n🏆 OVERALL BENCHMARK SCORES:")
        print(f"{'Approach':<15} {'Score':<10} {'Scenarios':<12} {'Grade':<10}")
        print("-" * 50)
        
        # Sort by benchmark score
        sorted_results = sorted(results.items(), key=lambda x: x[1]['overall_benchmark_score'], reverse=True)
        
        for approach, data in sorted_results:
            score = data['overall_benchmark_score']
            count = data['scenario_count']
            
            # Assign grade
            if score >= 85:
                grade = "Excellent"
            elif score >= 70:
                grade = "Good"
            elif score >= 55:
                grade = "Fair"
            else:
                grade = "Needs Work"
            
            print(f"{approach:<15} {score:<10.1f} {count:<12} {grade:<10}")
        
        print(f"\n📈 DETAILED METRIC BREAKDOWN:")
        for approach, data in sorted_results:
            print(f"\n{approach.upper()} Approach (Score: {data['overall_benchmark_score']:.1f}):")
            
            metrics = data['aggregate_metrics']
            print(f"   Retrieval Quality:")
            print(f"     Precision: {metrics.get('precision', 0)*100:.1f}%")
            print(f"     Recall: {metrics.get('recall', 0)*100:.1f}%")
            print(f"     F1-Score: {metrics.get('f1_score', 0)*100:.1f}%")
            
            print(f"   RAG Performance:")
            print(f"     Context Precision: {metrics.get('context_precision', 0)*100:.1f}%")
            print(f"     Context Recall: {metrics.get('context_recall', 0)*100:.1f}%")
            print(f"     Faithfulness: {metrics.get('faithfulness', 0)*100:.1f}%")
            
            print(f"   System Performance:")
            print(f"     Response Time Score: {metrics.get('response_time_score', 0)*100:.1f}%")
            print(f"     Success Rate: {metrics.get('success_rate', 0)*100:.1f}%")
            
            print(f"   Response Quality:")
            print(f"     Answer Relevancy: {metrics.get('answer_relevancy', 0)*100:.1f}%")
            print(f"     Structured Output: {metrics.get('structured_output', 0)*100:.1f}%")
        
        # Category analysis
        if category_analysis:
            print(f"\n🎯 CATEGORY-WISE PERFORMANCE:")
            
            # Get best approach for each category
            categories = list(next(iter(category_analysis.values())).keys())
            
            for category in categories:
                print(f"\n{category}:")
                category_scores = []
                for approach in results.keys():
                    if category in category_analysis[approach]:
                        score = category_analysis[approach][category]['benchmark_score']
                        count = category_analysis[approach][category]['scenario_count']
                        category_scores.append((approach, score, count))
                
                # Sort by score
                category_scores.sort(key=lambda x: x[1], reverse=True)
                
                for approach, score, count in category_scores:
                    print(f"   {approach}: {score:.1f} ({count} scenarios)")
        
        # Find best overall approach
        best_approach = max(results.keys(), key=lambda x: results[x]['overall_benchmark_score'])
        best_score = results[best_approach]['overall_benchmark_score']
        
        print(f"\n🥇 BEST OVERALL PERFORMER: {best_approach.upper()}")
        print(f"   Benchmark Score: {best_score:.1f}/100")
        
        # Performance insights
        print(f"\n💡 KEY INSIGHTS:")
        
        # Response time analysis
        avg_times = {}
        for approach, data in results.items():
            times = [s['response_time_ms'] for s in data['scenarios'] if 'response_time_ms' in s and not pd.isna(s['response_time_ms'])]
            avg_times[approach] = np.mean(times) if times else 0
        
        fastest_approach = min(avg_times.keys(), key=lambda x: avg_times[x])
        print(f"   Fastest approach: {fastest_approach} ({avg_times[fastest_approach]:.0f}ms avg)")
        
        # Success rate analysis
        success_rates = {}
        for approach, data in results.items():
            scenarios = data['scenarios']
            success_rates[approach] = sum(1 for s in scenarios if s['success_rate'] == 1.0) / len(scenarios) * 100
        
        most_reliable = max(success_rates.keys(), key=lambda x: success_rates[x])
        print(f"   Most reliable: {most_reliable} ({success_rates[most_reliable]:.1f}% success rate)")
        
        # Quality analysis
        quality_scores = {}
        for approach, data in results.items():
            metrics = data['aggregate_metrics']
            quality_scores[approach] = (metrics.get('precision', 0) + metrics.get('recall', 0)) / 2
        
        highest_quality = max(quality_scores.keys(), key=lambda x: quality_scores[x])
        print(f"   Highest quality: {highest_quality} ({quality_scores[highest_quality]*100:.1f}% avg precision+recall)")
    
    def save_benchmark_report(self, results: Dict[str, Any], category_analysis: Dict[str, Any], 
                             output_file: str = '/opt/genpod/rag_benchmark_report.json'):
        """Save comprehensive benchmark report."""
        
        # Calculate summary statistics
        best_approach = max(results.keys(), key=lambda x: results[x]['overall_benchmark_score'])
        
        report = {
            'metadata': {
                'csv_file': self.csv_file_path,
                'evaluation_date': datetime.now().isoformat(),
                'total_scenarios': len(self.ground_truth),
                'approaches_evaluated': list(results.keys()),
                'benchmark_methodology': 'Weighted multi-dimensional scoring (0-100 scale)',
                'best_overall_approach': best_approach,
                'best_overall_score': results[best_approach]['overall_benchmark_score']
            },
            'benchmark_weights': self.benchmark_weights,
            'ground_truth_structure': {
                'total_scenarios': len(self.ground_truth),
                'categories': list(set(gt['category'] for gt in self.ground_truth.values())),
                'codebase_elements': {k: len(v) for k, v in self.actual_codebase.items()}
            },
            'overall_results': results,
            'category_analysis': category_analysis,
            'benchmark_summary': {
                'ranking': sorted([(k, v['overall_benchmark_score']) for k, v in results.items()], 
                                key=lambda x: x[1], reverse=True),
                'score_distribution': {
                    k: {
                        'excellent': len([s for s in v['scenarios'] if s['benchmark_score'] >= 85]),
                        'good': len([s for s in v['scenarios'] if 70 <= s['benchmark_score'] < 85]),
                        'fair': len([s for s in v['scenarios'] if 55 <= s['benchmark_score'] < 70]),
                        'needs_work': len([s for s in v['scenarios'] if s['benchmark_score'] < 55])
                    } for k, v in results.items()
                }
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✓ Comprehensive benchmark report saved to {output_file}")
        
        return report

def main():
    """Main function to run the RAG benchmark evaluation."""
    # Use the latest comparative analysis results
    csv_file = '/opt/Test_Suite_Benchmarking/properly_fixed_comparative_analysis_20250718_172420.csv'
    
    if not Path(csv_file).exists():
        print(f"❌ CSV file not found: {csv_file}")
        print("Available files:")
        for f in Path('/opt/genpod/test_results/').glob('properly_fixed_comparative_analysis_*.csv'):
            print(f"  - {f}")
        return
    
    print("🚀 Starting Comprehensive RAG Benchmark Evaluation...")
    print("   Using weighted multi-dimensional scoring methodology")
    print("   Benchmark scale: 0-100 (higher is better)")
    
    # Initialize evaluator
    evaluator = RAGBenchmarkEvaluator(csv_file)
    
    # Run comprehensive evaluation
    results = evaluator.run_comprehensive_evaluation()
    
    # Analyze by category
    category_analysis = evaluator.analyze_by_category(results)
    
    # Print benchmark summary
    evaluator.print_benchmark_summary(results, category_analysis)
    
    # Create visualizations
    evaluator.create_benchmark_visualizations(results, category_analysis)
    
    # Save comprehensive report
    evaluator.save_benchmark_report(results, category_analysis)
    
    print("\n🎉 RAG Benchmark Evaluation completed!")
    print("   📊 Check /opt/genpod/rag_benchmark_comprehensive.png for visualizations")
    print("   📋 Check /opt/genpod/rag_benchmark_report.json for detailed results")

if __name__ == "__main__":
    main()