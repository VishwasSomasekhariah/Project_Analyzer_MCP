#!/usr/bin/env python3
"""
Improved RAG Retrieval Precision & Completeness Evaluator

This framework creates proper ground truth based on actual HelloWorldApp codebase analysis
and evaluates retrieval quality for all 37 scenarios across the three approaches.
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

class ImprovedRAGEvaluator:
    def __init__(self, csv_file_path: str):
        """Initialize the improved RAG evaluator with actual codebase ground truth."""
        self.csv_file_path = csv_file_path
        self.df = None
        self.ground_truth = {}
        self.actual_codebase = self._define_actual_codebase()
        self.load_data()
        self.create_comprehensive_ground_truth()
        
    def _define_actual_codebase(self) -> Dict[str, List[str]]:
        """Define actual HelloWorldApp codebase structure based on analysis."""
        return {
            # Core Classes
            'classes': [
                'Program', 'Manager', 'WorkerA', 'WorkerB', 'WorkerC', 'WorkerFactory', 'Helper'
            ],
            # Interfaces
            'interfaces': [
                'INotifier', 'IWorker'
            ],
            # Methods
            'methods': [
                'Main', 'Run', 'Notify', 'Process', 'CreateWorkers', 'FormatMessage'
            ],
            # Design Patterns
            'patterns': [
                'Factory Pattern', 'Observer Pattern', 'Strategy Pattern', 'Dependency Injection'
            ],
            # Architectural Components
            'architecture': [
                'Manager', 'Worker', 'Factory', 'Notification System', 'Dependency Injection'
            ],
            # Dependencies
            'dependencies': [
                'System', 'System.Collections.Generic', 'HelloWorldApp.Utilities'
            ],
            # Files
            'files': [
                'Program.cs', 'Manager.cs', 'WorkerA.cs', 'WorkerB.cs', 'WorkerC.cs', 
                'WorkerFactory.cs', 'INotifier.cs', 'IWorker.cs', 'Helper.cs'
            ],
            # Namespaces
            'namespaces': [
                'HelloWorldApp', 'HelloWorldApp.Utilities'
            ],
            # Security Elements
            'security': [
                'no authentication', 'no authorization', 'no input validation', 'console output'
            ],
            # Performance Elements
            'performance': [
                'sequential processing', 'no async', 'no caching', 'minimal resource usage'
            ],
            # Quality Elements
            'quality': [
                'SOLID principles', 'separation of concerns', 'clean code', 'interface-based design'
            ],
            # Testing Elements
            'testing': [
                'no unit tests', 'no integration tests', 'no test coverage'
            ],
            # Error Handling
            'error_handling': [
                'no try-catch', 'no exception handling', 'no error logging'
            ]
        }
    
    def load_data(self):
        """Load the comparative analysis data."""
        try:
            self.df = pd.read_csv(self.csv_file_path)
            print(f"✓ Loaded {len(self.df)} scenarios from {self.csv_file_path}")
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            raise
    
    def create_comprehensive_ground_truth(self):
        """Create comprehensive ground truth for all 37 scenarios based on actual codebase."""
        
        # Define ground truth patterns for each query type
        ground_truth_mapping = {
            # Technical Category
            'T001': {  # Architecture analysis
                'expected_elements': self.actual_codebase['classes'] + self.actual_codebase['interfaces'] + 
                                   self.actual_codebase['architecture'] + ['interaction', 'components'],
                'category': 'Technical',
                'focus': 'architecture'
            },
            'T002': {  # Design patterns
                'expected_elements': self.actual_codebase['patterns'] + ['Factory', 'Observer', 'Strategy'],
                'category': 'Technical', 
                'focus': 'patterns'
            },
            'T003': {  # Dependencies
                'expected_elements': self.actual_codebase['dependencies'] + ['relationships', 'coupling'],
                'category': 'Technical',
                'focus': 'dependencies'
            },
            'T004': {  # Class hierarchy
                'expected_elements': self.actual_codebase['interfaces'] + ['inheritance', 'hierarchy', 'base classes'],
                'category': 'Technical',
                'focus': 'hierarchy'
            },
            'T005': {  # Methods and complexity
                'expected_elements': self.actual_codebase['methods'] + ['complexity', 'cyclomatic'],
                'category': 'Technical',
                'focus': 'complexity'
            },
            
            # Functional Category
            'F001': {  # Business logic
                'expected_elements': ['Manager', 'Worker', 'Process', 'business logic', 'coordination'],
                'category': 'Functional',
                'focus': 'business_logic'
            },
            'F002': {  # Data flow
                'expected_elements': ['Manager', 'WorkerFactory', 'data flow', 'communication'],
                'category': 'Functional',
                'focus': 'data_flow'
            },
            'F003': {  # Worker coordination
                'expected_elements': ['Manager', 'INotifier', 'coordination', 'callback'],
                'category': 'Functional',
                'focus': 'coordination'
            },
            'F004': {  # Factory implementation
                'expected_elements': ['WorkerFactory', 'CreateWorkers', 'Factory Pattern'],
                'category': 'Functional',
                'focus': 'factory'
            },
            'F005': {  # Notification system
                'expected_elements': ['INotifier', 'Notify', 'Observer Pattern', 'callback'],
                'category': 'Functional',
                'focus': 'notification'
            },
            
            # Non-Functional Category
            'NF001': {  # Error handling
                'expected_elements': self.actual_codebase['error_handling'] + ['exception handling'],
                'category': 'Non-Functional',
                'focus': 'error_handling'
            },
            'NF002': {  # Code quality
                'expected_elements': self.actual_codebase['quality'] + ['maintainability', 'readability'],
                'category': 'Non-Functional',
                'focus': 'quality'
            },
            'NF003': {  # Performance
                'expected_elements': self.actual_codebase['performance'] + ['optimization', 'efficiency'],
                'category': 'Non-Functional',
                'focus': 'performance'
            },
            'NF004': {  # Security
                'expected_elements': self.actual_codebase['security'] + ['vulnerabilities', 'security concerns'],
                'category': 'Non-Functional',
                'focus': 'security'
            },
            'NF005': {  # Maintainability
                'expected_elements': self.actual_codebase['quality'] + ['maintenance', 'structure'],
                'category': 'Non-Functional',
                'focus': 'maintainability'
            },
            'NF006': {  # Testing
                'expected_elements': self.actual_codebase['testing'] + ['unit tests', 'testing strategy'],
                'category': 'Non-Functional',
                'focus': 'testing'
            },
            
            # Additional categories based on actual test suite
            'M001': {  # Modifications
                'expected_elements': self.actual_codebase['classes'] + ['refactoring', 'changes'],
                'category': 'Modification',
                'focus': 'code_changes'
            },
            'M002': {  # Code refactoring
                'expected_elements': self.actual_codebase['quality'] + ['refactoring', 'improvements'],
                'category': 'Modification',
                'focus': 'refactoring'
            },
            'M003': {  # Interface changes
                'expected_elements': self.actual_codebase['interfaces'] + ['modifications', 'changes'],
                'category': 'Modification',
                'focus': 'interface_changes'
            },
            'M004': {  # Method modifications
                'expected_elements': self.actual_codebase['methods'] + ['modifications', 'changes'],
                'category': 'Modification',
                'focus': 'method_changes'
            },
            'M005': {  # Design pattern changes
                'expected_elements': self.actual_codebase['patterns'] + ['modifications', 'changes'],
                'category': 'Modification',
                'focus': 'pattern_changes'
            },
            
            # Feature Addition
            'FA001': {  # New features
                'expected_elements': self.actual_codebase['classes'] + ['new features', 'additions'],
                'category': 'Feature Addition',
                'focus': 'new_features'
            },
            'FA002': {  # Extension points
                'expected_elements': self.actual_codebase['interfaces'] + ['extension', 'extensibility'],
                'category': 'Feature Addition',
                'focus': 'extensions'
            },
            'FA003': {  # New patterns
                'expected_elements': self.actual_codebase['patterns'] + ['new patterns', 'additions'],
                'category': 'Feature Addition',
                'focus': 'new_patterns'
            },
            'FA004': {  # Additional workers
                'expected_elements': ['WorkerFactory', 'IWorker', 'new workers'],
                'category': 'Feature Addition',
                'focus': 'worker_additions'
            },
            'FA005': {  # Enhanced functionality
                'expected_elements': self.actual_codebase['methods'] + ['enhancements', 'improvements'],
                'category': 'Feature Addition',
                'focus': 'enhancements'
            },
            
            # Modernization
            'MOD001': {  # Async/await
                'expected_elements': self.actual_codebase['methods'] + ['async', 'await', 'Task'],
                'category': 'Modernization',
                'focus': 'async'
            },
            'MOD002': {  # Dependency injection
                'expected_elements': ['dependency injection', 'DI container', 'IoC'],
                'category': 'Modernization',
                'focus': 'dependency_injection'
            },
            'MOD003': {  # Logging
                'expected_elements': ['logging', 'ILogger', 'structured logging'],
                'category': 'Modernization',
                'focus': 'logging'
            },
            'MOD004': {  # Configuration
                'expected_elements': ['configuration', 'appsettings', 'IConfiguration'],
                'category': 'Modernization',
                'focus': 'configuration'
            },
            'MOD005': {  # Modern patterns
                'expected_elements': self.actual_codebase['patterns'] + ['modern patterns', 'best practices'],
                'category': 'Modernization',
                'focus': 'modern_patterns'
            },
            
            # Bug Analysis
            'BA001': {  # Bug detection
                'expected_elements': self.actual_codebase['error_handling'] + ['bugs', 'issues'],
                'category': 'Bug Analysis',
                'focus': 'bug_detection'
            },
            'BA002': {  # Memory leaks
                'expected_elements': ['memory', 'dispose', 'garbage collection'],
                'category': 'Bug Analysis',
                'focus': 'memory_issues'
            },
            'BA003': {  # Concurrency issues
                'expected_elements': ['thread safety', 'concurrency', 'race conditions'],
                'category': 'Bug Analysis',
                'focus': 'concurrency'
            },
            
            # Integration
            'INT001': {  # External integrations
                'expected_elements': self.actual_codebase['dependencies'] + ['integration', 'external'],
                'category': 'Integration',
                'focus': 'external_integration'
            },
            'INT002': {  # API integration
                'expected_elements': ['API', 'HTTP', 'REST', 'integration'],
                'category': 'Integration',
                'focus': 'api_integration'
            },
            'INT003': {  # Database integration
                'expected_elements': ['database', 'data access', 'persistence'],
                'category': 'Integration',
                'focus': 'database_integration'
            }
        }
        
        # Create ground truth for each scenario in the dataset
        for _, row in self.df.iterrows():
            query_id = row['query_id']
            query_category = row['query_category']
            
            # Find matching ground truth pattern
            if query_id in ground_truth_mapping:
                self.ground_truth[query_id] = {
                    'expected_elements': ground_truth_mapping[query_id]['expected_elements'],
                    'query': row['user_query'],
                    'category': query_category,
                    'subcategory': row['query_subcategory'],
                    'focus': ground_truth_mapping[query_id]['focus']
                }
            else:
                # Create generic ground truth based on category
                if query_category == 'Technical':
                    elements = self.actual_codebase['classes'] + self.actual_codebase['interfaces']
                elif query_category == 'Functional':
                    elements = self.actual_codebase['methods'] + ['business logic']
                elif query_category == 'Non-Functional':
                    elements = self.actual_codebase['quality'] + self.actual_codebase['security']
                else:
                    elements = self.actual_codebase['classes'] + self.actual_codebase['methods']
                
                self.ground_truth[query_id] = {
                    'expected_elements': elements,
                    'query': row['user_query'],
                    'category': query_category,
                    'subcategory': row['query_subcategory'],
                    'focus': 'generic'
                }
        
        print(f"✓ Created comprehensive ground truth for {len(self.ground_truth)} scenarios")
    
    def extract_code_elements(self, response: str) -> List[str]:
        """Extract code elements from response with improved patterns."""
        if pd.isna(response) or not response:
            return []
        
        response_str = str(response).lower()
        
        # Extract specific code elements
        extracted = []
        
        # Check for actual codebase elements
        all_elements = []
        for element_type, elements in self.actual_codebase.items():
            all_elements.extend([elem.lower() for elem in elements])
        
        # Find matches in response
        for element in all_elements:
            if element in response_str:
                extracted.append(element)
        
        # Extract additional patterns
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
    
    def evaluate_single_scenario(self, row: pd.Series, approach: str) -> Dict[str, float]:
        """Evaluate a single scenario for a specific approach."""
        query_id = row['query_id']
        query = row['user_query']
        
        # Get response for the specific approach
        response_col = f'{approach}_response'
        response = row[response_col]
        
        # Get ground truth
        if query_id not in self.ground_truth:
            return {}
        
        expected_elements = self.ground_truth[query_id]['expected_elements']
        
        # Extract code elements from response
        retrieved_elements = self.extract_code_elements(response)
        
        # Calculate metrics
        precision, recall = self.calculate_precision_recall(retrieved_elements, expected_elements)
        f1_score = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return {
            'precision': precision,
            'recall': recall,
            'f1_score': f1_score,
            'retrieved_elements_count': len(retrieved_elements),
            'expected_elements_count': len(expected_elements),
            'intersection_count': len(set([elem.lower() for elem in retrieved_elements]).intersection(
                set([elem.lower() for elem in expected_elements])
            ))
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
                    scenario_result['focus'] = self.ground_truth[row['query_id']]['focus']
                    approach_results.append(scenario_result)
            
            results[approach] = approach_results
            print(f"✓ Evaluated {len(approach_results)} scenarios for {approach}")
        
        return results
    
    def print_evaluation_summary(self, results: Dict[str, Any]):
        """Print a comprehensive evaluation summary."""
        print("\n" + "="*80)
        print("IMPROVED RAG RETRIEVAL PRECISION & COMPLETENESS EVALUATION")
        print("="*80)
        
        print(f"\n📊 Evaluation Overview:")
        print(f"   Total scenarios evaluated: {len(self.ground_truth)}")
        print(f"   Approaches compared: {len(results)}")
        
        print(f"\n🎯 Overall Performance Metrics:")
        print(f"{'Approach':<15} {'Precision':<12} {'Recall':<12} {'F1-Score':<12} {'Scenarios':<10}")
        print("-" * 65)
        
        for approach, scenario_results in results.items():
            if not scenario_results:
                continue
            
            df_results = pd.DataFrame(scenario_results)
            precision_mean = df_results['precision'].mean()
            recall_mean = df_results['recall'].mean()
            f1_mean = df_results['f1_score'].mean()
            
            print(f"{approach:<15} {precision_mean:.3f}        {recall_mean:.3f}        {f1_mean:.3f}        {len(scenario_results)}")
        
        print(f"\n📈 Category-wise Performance:")
        for approach, scenario_results in results.items():
            if not scenario_results:
                continue
            
            df_results = pd.DataFrame(scenario_results)
            print(f"\n{approach.upper()} Approach:")
            
            category_stats = df_results.groupby('query_category').agg({
                'precision': 'mean',
                'recall': 'mean', 
                'f1_score': 'mean'
            }).round(3)
            
            for category, stats in category_stats.iterrows():
                count = len(df_results[df_results['query_category'] == category])
                print(f"   {category:<15} P:{stats['precision']:.3f} R:{stats['recall']:.3f} F1:{stats['f1_score']:.3f} ({count} scenarios)")
        
        # Find best performing approach
        best_f1 = 0
        best_approach = None
        for approach, scenario_results in results.items():
            if scenario_results:
                df_results = pd.DataFrame(scenario_results)
                f1_mean = df_results['f1_score'].mean()
                if f1_mean > best_f1:
                    best_f1 = f1_mean
                    best_approach = approach
        
        if best_approach:
            print(f"\n🏆 Best Overall Performance: {best_approach.upper()}")
            print(f"   F1-Score: {best_f1:.3f}")
    
    def save_evaluation_report(self, results: Dict[str, Any], output_file: str = '/opt/genpod/improved_rag_evaluation_report.json'):
        """Save detailed evaluation report."""
        report = {
            'metadata': {
                'csv_file': self.csv_file_path,
                'evaluation_date': datetime.now().isoformat(),
                'total_scenarios': len(self.ground_truth),
                'approaches_evaluated': list(results.keys()),
                'ground_truth_source': 'actual_codebase_analysis'
            },
            'codebase_structure': self.actual_codebase,
            'ground_truth_summary': {
                'total_scenarios': len(self.ground_truth),
                'categories': list(set(gt['category'] for gt in self.ground_truth.values())),
                'focus_areas': list(set(gt['focus'] for gt in self.ground_truth.values()))
            },
            'detailed_results': results
        }
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✓ Detailed evaluation report saved to {output_file}")

def main():
    """Main function to run improved RAG evaluation."""
    # Use the comparative analysis results
    csv_file = '/opt/genpod/test_results/comparative_analysis_20250715_184459.csv'
    
    if not Path(csv_file).exists():
        print(f"❌ CSV file not found: {csv_file}")
        return
    
    print("🔍 Starting Improved RAG Retrieval Precision & Completeness Evaluation...")
    
    # Initialize evaluator
    evaluator = ImprovedRAGEvaluator(csv_file)
    
    # Run comprehensive evaluation
    results = evaluator.run_comprehensive_evaluation()
    
    # Print summary
    evaluator.print_evaluation_summary(results)
    
    # Save detailed report
    evaluator.save_evaluation_report(results)
    
    print("\n✅ Improved RAG evaluation completed!")

if __name__ == "__main__":
    main()