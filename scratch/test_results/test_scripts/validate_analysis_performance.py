#!/usr/bin/env python3
"""
Analysis Performance Validation Tool

This script analyzes the comparative results from the three different approaches:
1. Vector-only search (codebase-vector-rag)
2. CPG-only search (dynamic Cypher generation)
3. Comprehensive analysis (combined approach)

It evaluates performance metrics, response quality, and provides insights
for improving the code analysis workflow.
"""

import pandas as pd
import numpy as np
import json
import re
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Tuple
import warnings
warnings.filterwarnings('ignore')

class AnalysisPerformanceValidator:
    def __init__(self, csv_file_path: str):
        """Initialize the validator with the comparative analysis CSV file."""
        self.csv_file_path = csv_file_path
        self.df = None
        self.load_data()
        
    def load_data(self):
        """Load the comparative analysis data."""
        try:
            self.df = pd.read_csv(self.csv_file_path)
            print(f"✓ Loaded {len(self.df)} scenarios from {self.csv_file_path}")
        except Exception as e:
            print(f"❌ Error loading data: {e}")
            raise
    
    def analyze_response_times(self) -> Dict[str, Any]:
        """Analyze response times across all three approaches."""
        time_metrics = {}
        
        # Extract response times for each approach
        vector_times = self.df['vector_response_time_ms'].dropna()
        cpg_times = self.df['cpg_response_time_ms'].dropna()
        comprehensive_times = self.df['comprehensive_response_time_ms'].dropna()
        
        approaches = {
            'Vector-only': vector_times,
            'CPG-only': cpg_times,
            'Comprehensive': comprehensive_times
        }
        
        for approach, times in approaches.items():
            time_metrics[approach] = {
                'mean': times.mean(),
                'median': times.median(),
                'std': times.std(),
                'min': times.min(),
                'max': times.max(),
                'p95': times.quantile(0.95),
                'count': len(times)
            }
        
        return time_metrics
    
    def analyze_success_rates(self) -> Dict[str, Any]:
        """Analyze success rates for each approach."""
        success_metrics = {}
        
        approaches = {
            'Vector-only': 'vector_status',
            'CPG-only': 'cpg_status', 
            'Comprehensive': 'comprehensive_status'
        }
        
        for approach, status_col in approaches.items():
            total = len(self.df)
            success = len(self.df[self.df[status_col] == 'success'])
            success_rate = (success / total) * 100
            
            success_metrics[approach] = {
                'total_scenarios': total,
                'successful': success,
                'success_rate': success_rate,
                'failed': total - success
            }
        
        return success_metrics
    
    def analyze_response_quality(self) -> Dict[str, Any]:
        """Analyze response quality metrics."""
        quality_metrics = {}
        
        approaches = {
            'Vector-only': 'vector_response',
            'CPG-only': 'cpg_response',
            'Comprehensive': 'comprehensive_response'
        }
        
        for approach, response_col in approaches.items():
            responses = self.df[response_col].dropna()
            
            # Calculate basic metrics
            avg_length = responses.str.len().mean()
            median_length = responses.str.len().median()
            
            # Count structured responses (JSON-like)
            structured_count = sum(1 for r in responses if self._is_structured_response(r))
            structured_rate = (structured_count / len(responses)) * 100
            
            # Count empty or very short responses
            short_responses = sum(1 for r in responses if len(str(r)) < 50)
            short_rate = (short_responses / len(responses)) * 100
            
            quality_metrics[approach] = {
                'avg_response_length': avg_length,
                'median_response_length': median_length,
                'structured_responses': structured_count,
                'structured_rate': structured_rate,
                'short_responses': short_responses,
                'short_response_rate': short_rate,
                'total_responses': len(responses)
            }
        
        return quality_metrics
    
    def _is_structured_response(self, response: str) -> bool:
        """Check if response appears to be structured (JSON, code, etc.)."""
        response_str = str(response)
        # Look for JSON-like structure, code blocks, or organized content
        indicators = [
            '{' in response_str and '}' in response_str,
            '[' in response_str and ']' in response_str,
            '```' in response_str,
            response_str.count('\n') > 5,  # Multi-line structured content
            'class ' in response_str or 'function ' in response_str,
            'MATCH' in response_str or 'RETURN' in response_str  # Cypher queries
        ]
        return any(indicators)
    
    def analyze_by_category(self) -> Dict[str, Any]:
        """Analyze performance by query category."""
        category_metrics = {}
        
        for category in self.df['query_category'].unique():
            category_df = self.df[self.df['query_category'] == category]
            
            # Response times by category
            vector_times = category_df['vector_response_time_ms'].mean()
            cpg_times = category_df['cpg_response_time_ms'].mean()
            comprehensive_times = category_df['comprehensive_response_time_ms'].mean()
            
            # Success rates by category
            vector_success = (category_df['vector_status'] == 'success').mean() * 100
            cpg_success = (category_df['cpg_status'] == 'success').mean() * 100
            comprehensive_success = (category_df['comprehensive_status'] == 'success').mean() * 100
            
            category_metrics[category] = {
                'scenario_count': len(category_df),
                'avg_response_times': {
                    'vector': vector_times,
                    'cpg': cpg_times,
                    'comprehensive': comprehensive_times
                },
                'success_rates': {
                    'vector': vector_success,
                    'cpg': cpg_success,
                    'comprehensive': comprehensive_success
                }
            }
        
        return category_metrics
    
    def identify_performance_patterns(self) -> Dict[str, Any]:
        """Identify patterns in performance across approaches."""
        patterns = {}
        
        # Find scenarios where comprehensive is significantly slower
        self.df['comprehensive_overhead'] = (
            self.df['comprehensive_response_time_ms'] - 
            self.df[['vector_response_time_ms', 'cpg_response_time_ms']].max(axis=1)
        )
        
        high_overhead = self.df[self.df['comprehensive_overhead'] > 10000]  # > 10 seconds
        
        # Find scenarios where vector is much faster than CPG
        self.df['vector_vs_cpg_diff'] = (
            self.df['cpg_response_time_ms'] - self.df['vector_response_time_ms']
        )
        
        vector_advantage = self.df[self.df['vector_vs_cpg_diff'] > 5000]  # > 5 seconds
        
        # Find scenarios where CPG is much faster than vector
        cpg_advantage = self.df[self.df['vector_vs_cpg_diff'] < -5000]  # < -5 seconds
        
        patterns = {
            'high_comprehensive_overhead': {
                'count': len(high_overhead),
                'scenarios': high_overhead[['query_id', 'query_category', 'comprehensive_overhead']].to_dict('records')
            },
            'vector_advantage_scenarios': {
                'count': len(vector_advantage),
                'scenarios': vector_advantage[['query_id', 'query_category', 'vector_vs_cpg_diff']].to_dict('records')
            },
            'cpg_advantage_scenarios': {
                'count': len(cpg_advantage),
                'scenarios': cpg_advantage[['query_id', 'query_category', 'vector_vs_cpg_diff']].to_dict('records')
            }
        }
        
        return patterns
    
    def generate_performance_report(self) -> Dict[str, Any]:
        """Generate a comprehensive performance report."""
        report = {
            'metadata': {
                'csv_file': self.csv_file_path,
                'total_scenarios': len(self.df),
                'analysis_date': datetime.now().isoformat(),
                'unique_categories': list(self.df['query_category'].unique())
            },
            'response_times': self.analyze_response_times(),
            'success_rates': self.analyze_success_rates(),
            'response_quality': self.analyze_response_quality(),
            'category_analysis': self.analyze_by_category(),
            'performance_patterns': self.identify_performance_patterns()
        }
        
        return report
    
    def create_visualizations(self, output_dir: str = '/opt/genpod/analysis_charts'):
        """Create performance visualization charts."""
        Path(output_dir).mkdir(exist_ok=True)
        
        # Set up the plotting style
        plt.style.use('seaborn-v0_8')
        
        # 1. Response Time Comparison
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # Box plot of response times
        time_data = [
            self.df['vector_response_time_ms'].dropna() / 1000,
            self.df['cpg_response_time_ms'].dropna() / 1000,
            self.df['comprehensive_response_time_ms'].dropna() / 1000
        ]
        
        axes[0, 0].boxplot(time_data, labels=['Vector', 'CPG', 'Comprehensive'])
        axes[0, 0].set_title('Response Time Distribution (seconds)')
        axes[0, 0].set_ylabel('Response Time (s)')
        
        # Success rate bar chart
        success_data = self.analyze_success_rates()
        approaches = list(success_data.keys())
        success_rates = [success_data[app]['success_rate'] for app in approaches]
        
        axes[0, 1].bar(approaches, success_rates)
        axes[0, 1].set_title('Success Rates by Approach')
        axes[0, 1].set_ylabel('Success Rate (%)')
        axes[0, 1].set_ylim(0, 100)
        
        # Response time by category
        category_data = self.analyze_by_category()
        categories = list(category_data.keys())
        vector_times = [category_data[cat]['avg_response_times']['vector'] / 1000 for cat in categories]
        cpg_times = [category_data[cat]['avg_response_times']['cpg'] / 1000 for cat in categories]
        comprehensive_times = [category_data[cat]['avg_response_times']['comprehensive'] / 1000 for cat in categories]
        
        x = np.arange(len(categories))
        width = 0.25
        
        axes[1, 0].bar(x - width, vector_times, width, label='Vector', alpha=0.8)
        axes[1, 0].bar(x, cpg_times, width, label='CPG', alpha=0.8)
        axes[1, 0].bar(x + width, comprehensive_times, width, label='Comprehensive', alpha=0.8)
        
        axes[1, 0].set_title('Average Response Time by Category')
        axes[1, 0].set_ylabel('Response Time (s)')
        axes[1, 0].set_xticks(x)
        axes[1, 0].set_xticklabels(categories, rotation=45, ha='right')
        axes[1, 0].legend()
        
        # Response quality comparison
        quality_data = self.analyze_response_quality()
        approaches = list(quality_data.keys())
        avg_lengths = [quality_data[app]['avg_response_length'] for app in approaches]
        
        axes[1, 1].bar(approaches, avg_lengths)
        axes[1, 1].set_title('Average Response Length')
        axes[1, 1].set_ylabel('Characters')
        
        plt.tight_layout()
        plt.savefig(f'{output_dir}/performance_overview.png', dpi=300, bbox_inches='tight')
        plt.close()
        
        print(f"✓ Performance charts saved to {output_dir}/")
    
    def print_summary(self):
        """Print a summary of the analysis results."""
        report = self.generate_performance_report()
        
        print("\n" + "="*80)
        print("COMPARATIVE ANALYSIS PERFORMANCE REPORT")
        print("="*80)
        
        print(f"\n📊 Dataset Overview:")
        print(f"   Total scenarios: {report['metadata']['total_scenarios']}")
        print(f"   Categories: {', '.join(report['metadata']['unique_categories'])}")
        
        print(f"\n⏱️  Response Time Analysis:")
        for approach, metrics in report['response_times'].items():
            print(f"   {approach}:")
            print(f"     Average: {metrics['mean']:.0f}ms")
            print(f"     Median: {metrics['median']:.0f}ms")
            print(f"     95th percentile: {metrics['p95']:.0f}ms")
        
        print(f"\n✅ Success Rate Analysis:")
        for approach, metrics in report['success_rates'].items():
            print(f"   {approach}: {metrics['success_rate']:.1f}% ({metrics['successful']}/{metrics['total_scenarios']})")
        
        print(f"\n📝 Response Quality Analysis:")
        for approach, metrics in report['response_quality'].items():
            print(f"   {approach}:")
            print(f"     Average length: {metrics['avg_response_length']:.0f} chars")
            print(f"     Structured responses: {metrics['structured_rate']:.1f}%")
            print(f"     Short responses: {metrics['short_response_rate']:.1f}%")
        
        print(f"\n🎯 Performance Patterns:")
        patterns = report['performance_patterns']
        print(f"   High comprehensive overhead: {patterns['high_comprehensive_overhead']['count']} scenarios")
        print(f"   Vector advantage: {patterns['vector_advantage_scenarios']['count']} scenarios")
        print(f"   CPG advantage: {patterns['cpg_advantage_scenarios']['count']} scenarios")
        
        print(f"\n📈 Category Performance:")
        for category, metrics in report['category_analysis'].items():
            print(f"   {category} ({metrics['scenario_count']} scenarios):")
            print(f"     Avg times: V:{metrics['avg_response_times']['vector']:.0f}ms, "
                  f"C:{metrics['avg_response_times']['cpg']:.0f}ms, "
                  f"X:{metrics['avg_response_times']['comprehensive']:.0f}ms")
    
    def save_detailed_report(self, output_file: str = '/opt/genpod/performance_validation_report.json'):
        """Save a detailed JSON report."""
        report = self.generate_performance_report()
        
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✓ Detailed report saved to {output_file}")

def main():
    """Main function to run the performance validation."""
    # Use the most recent CSV file
    csv_file = '/opt/genpod/test_results/comparative_analysis_20250715_184459.csv'
    
    if not Path(csv_file).exists():
        print(f"❌ CSV file not found: {csv_file}")
        return
    
    print("🔍 Starting Analysis Performance Validation...")
    
    # Initialize validator
    validator = AnalysisPerformanceValidator(csv_file)
    
    # Print summary
    validator.print_summary()
    
    # Create visualizations
    validator.create_visualizations()
    
    # Save detailed report
    validator.save_detailed_report()
    
    print("\n✅ Performance validation completed!")

if __name__ == "__main__":
    main()