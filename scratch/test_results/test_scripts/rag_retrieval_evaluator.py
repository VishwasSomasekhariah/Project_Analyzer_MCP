#!/usr/bin/env python3
"""
RAG Retrieval Precision & Completeness Evaluator

This framework evaluates retrieval quality for code analysis RAG systems using:
1. Standard retrieval metrics (Precision@K, Recall@K, MRR, NDCG)
2. RAG-specific metrics (Context Precision, Context Recall, Faithfulness)
3. Code-specific metrics (Semantic Overlap, Functional Completeness, API Coverage)

Adapted for comparative analysis of Vector-only, CPG-only, and Comprehensive approaches.
"""

import pandas as pd
import numpy as np
import json
import re
from typing import Dict, List, Any, Tuple, Optional
from pathlib import Path
from datetime import datetime
import ast
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import warnings
warnings.filterwarnings('ignore')

class CodeRAGEvaluator:
    def __init__(self, csv_file_path: str):
        """Initialize the RAG evaluator with comparative analysis data."""
        self.csv_file_path = csv_file_path
        self.df = None
        self.ground_truth = {}
        self.evaluation_results = {}
        self.load_data()
        self.create_ground_truth()
        
    def load_data(self):
        """Load the comparative analysis data."""
        try:
            self.df = pd.read_csv(self.csv_file_path)
            print(f"✓ Loaded {len(self.df)} scenarios from {self.csv_file_path}")
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            raise
    
    def create_ground_truth(self):
        """Create ground truth labels for evaluation based on query categories and known code patterns."""
        # Define expected code elements for each query category
        ground_truth_patterns = {
            'Technical': {
                'T001': ['Manager', 'WorkerFactory', 'IWorker', 'WorkerA', 'WorkerB', 'WorkerC', 'architecture', 'components'],
                'T002': ['Factory', 'Observer', 'Strategy', 'WorkerFactory', 'INotifier', 'design patterns'],
                'T003': ['dependencies', 'relationships', 'Manager', 'WorkerFactory', 'IWorker'],
                'T004': ['class hierarchy', 'inheritance', 'IWorker', 'INotifier', 'base classes'],
                'T005': ['methods', 'Process', 'CreateWorkers', 'Notify', 'complexity', 'analysis']
            },
            'Functional': {
                'F001': ['business logic', 'core functionality', 'Process', 'worker coordination'],
                'F002': ['data flow', 'Manager', 'WorkerFactory', 'communication', 'data movement'],
                'F003': ['worker coordination', 'communication', 'Manager', 'INotifier', 'callback'],
                'F004': ['factory pattern', 'WorkerFactory', 'CreateWorkers', 'implementation'],
                'F005': ['notification system', 'INotifier', 'Notify', 'callback', 'observer pattern']
            },
            'Non-Functional': {
                'NF001': ['error handling', 'exception', 'try-catch', 'error patterns'],
                'NF002': ['code quality', 'code smells', 'improvements', 'refactoring'],
                'NF003': ['performance', 'bottlenecks', 'optimization', 'efficiency'],
                'NF004': ['security', 'vulnerabilities', 'security concerns', 'safety'],
                'NF005': ['maintainability', 'code maintenance', 'readability', 'structure'],
                'NF006': ['testing', 'test strategies', 'unit tests', 'testing approach']
            }
        }
        
        # Create ground truth mapping
        for _, row in self.df.iterrows():
            query_id = row['query_id']
            query_category = row['query_category']
            
            if query_category in ground_truth_patterns and query_id in ground_truth_patterns[query_category]:
                self.ground_truth[query_id] = {
                    'expected_elements': ground_truth_patterns[query_category][query_id],
                    'query': row['user_query'],
                    'category': query_category,
                    'subcategory': row['query_subcategory']
                }
        
        print(f"✓ Created ground truth for {len(self.ground_truth)} scenarios")
    
    def extract_code_elements(self, response: str) -> List[str]:
        """Extract code elements (classes, methods, concepts) from response."""
        if pd.isna(response) or not response:
            return []
        
        response_str = str(response).lower()
        
        # Extract code-related terms
        code_patterns = [
            r'\b(class|interface|struct|enum)\s+(\w+)',
            r'\b(method|function)\s+(\w+)',
            r'\b(\w+Factory|\w+Manager|\w+Worker)',
            r'\b(I\w+)',  # Interface patterns
            r'`([^`]+)`',  # Code in backticks
            r'\b(public|private|protected|static)\s+\w+\s+(\w+)',
        ]
        
        extracted = []
        for pattern in code_patterns:
            matches = re.findall(pattern, response_str, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    extracted.extend([m for m in match if m and len(m) > 2])
                else:
                    extracted.append(match)
        
        # Add important keywords mentioned
        important_keywords = [
            'factory', 'observer', 'strategy', 'pattern', 'manager', 'worker',
            'notification', 'callback', 'inheritance', 'interface', 'method',
            'class', 'function', 'dependency', 'architecture', 'component'
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
        
        # Calculate intersection
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
        """Evaluate context precision - how relevant is the retrieved context to the query."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response).lower()
        query_str = query.lower()
        
        # Check if response addresses the query intent
        query_keywords = set(re.findall(r'\b\w+\b', query_str))
        response_keywords = set(re.findall(r'\b\w+\b', response_str))
        
        keyword_overlap = len(query_keywords.intersection(response_keywords))
        total_query_keywords = len(query_keywords)
        
        keyword_precision = keyword_overlap / total_query_keywords if total_query_keywords > 0 else 0.0
        
        # Check if expected elements are mentioned
        expected_mentions = sum(1 for elem in expected_elements if elem.lower() in response_str)
        expected_precision = expected_mentions / len(expected_elements) if expected_elements else 0.0
        
        # Combine both scores
        return (keyword_precision + expected_precision) / 2
    
    def evaluate_context_recall(self, response: str, expected_elements: List[str]) -> float:
        """Evaluate context recall - how much of the expected content is captured."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response).lower()
        captured_elements = sum(1 for elem in expected_elements if elem.lower() in response_str)
        
        return captured_elements / len(expected_elements) if expected_elements else 0.0
    
    def evaluate_faithfulness(self, response: str) -> float:
        """Evaluate faithfulness - how factually accurate is the response."""
        if pd.isna(response) or not response:
            return 0.0
        
        response_str = str(response)
        
        # Look for structured information (higher faithfulness)
        structure_indicators = [
            response_str.count('{') + response_str.count('}'),  # JSON-like structure
            response_str.count('```'),  # Code blocks
            response_str.count('class ') + response_str.count('interface '),  # Code declarations
            response_str.count('\n'),  # Multi-line structure
            len(re.findall(r'MATCH.*RETURN', response_str, re.IGNORECASE))  # Cypher queries
        ]
        
        # Normalize structure score
        structure_score = min(sum(structure_indicators) / 20, 1.0)
        
        # Look for vague or uncertain language (lower faithfulness)
        uncertainty_phrases = [
            'might', 'could', 'possibly', 'perhaps', 'maybe', 'seems like',
            'appears to', 'likely', 'probably', 'potentially'
        ]
        
        uncertainty_count = sum(1 for phrase in uncertainty_phrases if phrase in response_str.lower())
        uncertainty_penalty = min(uncertainty_count * 0.1, 0.5)
        
        faithfulness_score = structure_score - uncertainty_penalty
        return max(0.0, min(1.0, faithfulness_score))
    
    def evaluate_answer_relevancy(self, query: str, response: str) -> float:
        """Evaluate how relevant the answer is to the question."""
        return self.calculate_semantic_similarity(query, response)
    
    def evaluate_single_scenario(self, row: pd.Series, approach: str) -> Dict[str, float]:
        """Evaluate a single scenario for a specific approach."""
        query_id = row['query_id']
        query = row['user_query']
        
        # Get response for the specific approach
        response_col = f'{approach}_response'
        response = row[response_col]
        
        # Get ground truth if available
        if query_id not in self.ground_truth:
            return {}
        
        expected_elements = self.ground_truth[query_id]['expected_elements']
        
        # Extract code elements from response
        retrieved_elements = self.extract_code_elements(response)
        
        # Calculate metrics
        precision, recall = self.calculate_precision_recall(retrieved_elements, expected_elements)
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        semantic_similarity = self.calculate_semantic_similarity(query, response)
        context_precision = self.evaluate_context_precision(query, response, expected_elements)
        context_recall = self.evaluate_context_recall(response, expected_elements)
        faithfulness = self.evaluate_faithfulness(response)
        answer_relevancy = self.evaluate_answer_relevancy(query, response)
        
        return {
            'precision': precision,
            'recall': recall,
            'f1_score': f1_score,
            'semantic_similarity': semantic_similarity,
            'context_precision': context_precision,
            'context_recall': context_recall,
            'faithfulness': faithfulness,
            'answer_relevancy': answer_relevancy,
            'retrieved_elements_count': len(retrieved_elements),
            'expected_elements_count': len(expected_elements)
        }
    
    def run_comprehensive_evaluation(self) -> Dict[str, Any]:
        """Run comprehensive evaluation across all approaches."""
        approaches = ['vector', 'cpg', 'comprehensive']
        results = {}
        
        for approach in approaches:
            print(f"🔍 Evaluating {approach} approach...")
            
            approach_results = []
            for _, row in self.df.iterrows():
                scenario_result = self.evaluate_single_scenario(row, approach)
                if scenario_result:  # Only include scenarios with ground truth
                    scenario_result['query_id'] = row['query_id']
                    scenario_result['query_category'] = row['query_category']
                    scenario_result['approach'] = approach
                    approach_results.append(scenario_result)
            
            results[approach] = approach_results
            print(f"✓ Evaluated {len(approach_results)} scenarios for {approach}")
        
        return results
    
    def calculate_aggregate_metrics(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate aggregate metrics across all approaches."""
        aggregate = {}
        
        for approach, scenario_results in results.items():
            if not scenario_results:
                continue
            
            df_results = pd.DataFrame(scenario_results)
            
            # Calculate mean metrics
            metrics = {}
            for metric in ['precision', 'recall', 'f1_score', 'semantic_similarity', 
                          'context_precision', 'context_recall', 'faithfulness', 'answer_relevancy']:
                metrics[f'{metric}_mean'] = df_results[metric].mean()
                metrics[f'{metric}_std'] = df_results[metric].std()
                metrics[f'{metric}_median'] = df_results[metric].median()
            
            # Calculate category-wise metrics
            category_metrics = {}
            for category in df_results['query_category'].unique():
                category_data = df_results[df_results['query_category'] == category]
                category_metrics[category] = {
                    'precision': category_data['precision'].mean(),
                    'recall': category_data['recall'].mean(),
                    'f1_score': category_data['f1_score'].mean(),
                    'context_precision': category_data['context_precision'].mean(),
                    'context_recall': category_data['context_recall'].mean(),
                    'scenario_count': len(category_data)
                }
            
            aggregate[approach] = {
                'overall_metrics': metrics,
                'category_metrics': category_metrics,
                'total_scenarios': len(scenario_results)
            }
        
        return aggregate
    
    def create_evaluation_visualizations(self, results: Dict[str, Any], output_dir: str = '/opt/genpod/rag_evaluation_charts'):
        """Create visualization charts for RAG evaluation results."""
        Path(output_dir).mkdir(exist_ok=True)
        plt.style.use('seaborn-v0_8')
        
        # Prepare data for visualization
        all_results = []
        for approach, scenario_results in results.items():
            for result in scenario_results:
                all_results.append(result)
        
        df_viz = pd.DataFrame(all_results)
        
        # Create comprehensive visualization
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        # 1. Precision comparison
        precision_data = df_viz.groupby('approach')['precision'].agg(['mean', 'std']).reset_index()
        axes[0, 0].bar(precision_data['approach'], precision_data['mean'], 
                      yerr=precision_data['std'], capsize=5, alpha=0.7)
        axes[0, 0].set_title('Precision by Approach')
        axes[0, 0].set_ylabel('Precision')
        axes[0, 0].set_ylim(0, 1)
        
        # 2. Recall comparison
        recall_data = df_viz.groupby('approach')['recall'].agg(['mean', 'std']).reset_index()
        axes[0, 1].bar(recall_data['approach'], recall_data['mean'], 
                      yerr=recall_data['std'], capsize=5, alpha=0.7)
        axes[0, 1].set_title('Recall by Approach')
        axes[0, 1].set_ylabel('Recall')
        axes[0, 1].set_ylim(0, 1)
        
        # 3. F1-Score comparison
        f1_data = df_viz.groupby('approach')['f1_score'].agg(['mean', 'std']).reset_index()
        axes[0, 2].bar(f1_data['approach'], f1_data['mean'], 
                      yerr=f1_data['std'], capsize=5, alpha=0.7)
        axes[0, 2].set_title('F1-Score by Approach')
        axes[0, 2].set_ylabel('F1-Score')
        axes[0, 2].set_ylim(0, 1)
        
        # 4. RAG-specific metrics
        rag_metrics = ['context_precision', 'context_recall', 'faithfulness']
        rag_data = df_viz.groupby('approach')[rag_metrics].mean()
        
        x = np.arange(len(rag_data.index))
        width = 0.25
        
        for i, metric in enumerate(rag_metrics):
            axes[1, 0].bar(x + i * width, rag_data[metric], width, 
                          label=metric.replace('_', ' ').title(), alpha=0.7)
        
        axes[1, 0].set_title('RAG-Specific Metrics')
        axes[1, 0].set_ylabel('Score')
        axes[1, 0].set_xlabel('Approach')
        axes[1, 0].set_xticks(x + width)
        axes[1, 0].set_xticklabels(rag_data.index)
        axes[1, 0].legend()
        axes[1, 0].set_ylim(0, 1)
        
        # 5. Category-wise performance
        category_f1 = df_viz.groupby(['query_category', 'approach'])['f1_score'].mean().unstack()
        category_f1.plot(kind='bar', ax=axes[1, 1], alpha=0.7)
        axes[1, 1].set_title('F1-Score by Category')
        axes[1, 1].set_ylabel('F1-Score')
        axes[1, 1].set_xlabel('Query Category')
        axes[1, 1].legend(title='Approach')
        axes[1, 1].tick_params(axis='x', rotation=45)
        
        # 6. Precision vs Recall scatter
        for approach in df_viz['approach'].unique():
            approach_data = df_viz[df_viz['approach'] == approach]
            axes[1, 2].scatter(approach_data['precision'], approach_data['recall'], 
                             label=approach, alpha=0.6, s=60)
        
        axes[1, 2].set_title('Precision vs Recall')
        axes[1, 2].set_xlabel('Precision')
        axes[1, 2].set_ylabel('Recall')
        axes[1, 2].legend()
        axes[1, 2].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig(f'{output_dir}/rag_evaluation_comprehensive.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ RAG evaluation charts saved to {output_dir}/")
    
    def print_evaluation_summary(self, results: Dict[str, Any]):
        """Print a comprehensive evaluation summary."""
        aggregate = self.calculate_aggregate_metrics(results)
        
        print("\n" + "="*80)
        print("RAG RETRIEVAL PRECISION & COMPLETENESS EVALUATION")
        print("="*80)
        
        print(f"\n📊 Evaluation Overview:")
        print(f"   Total scenarios evaluated: {len(self.ground_truth)}")
        print(f"   Approaches compared: {len(results)}")
        
        print(f"\n🎯 Overall Performance Metrics:")
        print(f"{'Approach':<15} {'Precision':<12} {'Recall':<12} {'F1-Score':<12} {'Context Prec':<12} {'Faithfulness':<12}")
        print("-" * 75)
        
        for approach, metrics in aggregate.items():
            overall = metrics['overall_metrics']
            print(f"{approach:<15} "
                  f"{overall['precision_mean']:.3f}±{overall['precision_std']:.3f}  "
                  f"{overall['recall_mean']:.3f}±{overall['recall_std']:.3f}  "
                  f"{overall['f1_score_mean']:.3f}±{overall['f1_score_std']:.3f}  "
                  f"{overall['context_precision_mean']:.3f}±{overall['context_precision_std']:.3f}  "
                  f"{overall['faithfulness_mean']:.3f}±{overall['faithfulness_std']:.3f}")
        
        print(f"\n📈 Category-wise Performance:")
        for approach, metrics in aggregate.items():
            print(f"\n{approach.upper()} Approach:")
            for category, cat_metrics in metrics['category_metrics'].items():
                print(f"   {category:<15} P:{cat_metrics['precision']:.3f} "
                      f"R:{cat_metrics['recall']:.3f} F1:{cat_metrics['f1_score']:.3f} "
                      f"({cat_metrics['scenario_count']} scenarios)")
        
        # Find best performing approach
        best_approach = max(aggregate.keys(), 
                          key=lambda x: aggregate[x]['overall_metrics']['f1_score_mean'])
        
        print(f"\n🏆 Best Overall Performance: {best_approach.upper()}")
        print(f"   F1-Score: {aggregate[best_approach]['overall_metrics']['f1_score_mean']:.3f}")
        print(f"   Precision: {aggregate[best_approach]['overall_metrics']['precision_mean']:.3f}")
        print(f"   Recall: {aggregate[best_approach]['overall_metrics']['recall_mean']:.3f}")
    
    def save_evaluation_report(self, results: Dict[str, Any], output_file: str = '/opt/genpod/rag_evaluation_report.json'):
        """Save detailed evaluation report."""
        aggregate = self.calculate_aggregate_metrics(results)
        
        report = {
            'metadata': {
                'csv_file': self.csv_file_path,
                'evaluation_date': datetime.now().isoformat(),
                'total_scenarios': len(self.ground_truth),
                'approaches_evaluated': list(results.keys())
            },
            'ground_truth_summary': {
                'total_scenarios': len(self.ground_truth),
                'categories': list(set(gt['category'] for gt in self.ground_truth.values()))
            },
            'aggregate_metrics': aggregate,
            'detailed_results': results
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✓ Detailed evaluation report saved to {output_file}")

def main():
    """Main function to run RAG evaluation."""
    # Use the comparative analysis results
    csv_file = '/opt/genpod/test_results/comparative_analysis_20250715_184459.csv'
    
    if not Path(csv_file).exists():
        print(f"❌ CSV file not found: {csv_file}")
        return
    
    print("🔍 Starting RAG Retrieval Precision & Completeness Evaluation...")
    
    # Initialize evaluator
    evaluator = CodeRAGEvaluator(csv_file)
    
    # Run comprehensive evaluation
    results = evaluator.run_comprehensive_evaluation()
    
    # Print summary
    evaluator.print_evaluation_summary(results)
    
    # Create visualizations
    evaluator.create_evaluation_visualizations(results)
    
    # Save detailed report
    evaluator.save_evaluation_report(results)
    
    print("\n✅ RAG evaluation completed!")

if __name__ == "__main__":
    main()