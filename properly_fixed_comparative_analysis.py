#!/usr/bin/env python3
"""
Properly Fixed Comparative Analysis Suite

This version fixes all the identified issues:
1. Uses JSON output format for vector-RAG (--output-format json)
2. Properly extracts final AI response from vector-RAG output
3. Fixes CPG query generation with proper fallbacks
4. Handles all 90 scenarios by default
5. Provides proper configuration options
"""

import asyncio
import json
import logging
import time
import os
import pandas as pd
import pickle
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

from mcp_use import MCPClient, MCPSession
from mcp_use.connectors.http import HttpConnector

# Import OpenAI for direct LLM calls
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class ProperlyFixedComparativeAnalyzer:
    def __init__(self, test_scenario_filter=None, vector_db="qdrant", retriever_combination="pageindex_vector_graph", tool="hybrid"):
        """
        Initialize the properly fixed comparative analyzer.

        Args:
            test_scenario_filter: Can be:
                - None: Run all 90 scenarios (DEFAULT)
                - int: Run first N scenarios (e.g., 5)
                - list: Run specific scenario IDs (e.g., ['T001', 'T002', 'F001'])
                - str: Run scenarios matching category (e.g., 'Technical')
            vector_db: Vector database to use ("qdrant" or "weaviate")
        """
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.neo4j_config = "/opt/genpod/neo4j_config.json"
        self.test_scenario_filter = test_scenario_filter
        self.retriever_combination = retriever_combination
        self.tool = tool  # "hybrid" | "vector" | "pageindex" | "cpg"

        # Configure vector database settings
        self.vector_db = vector_db
        if vector_db == "qdrant":
            self.collection_name = "HelloWorldApp_pageindex_v3"
            self.vector_config = "/opt/genpod/qdrant_config.json"
        elif vector_db == "weaviate":
            self.collection_name = "HelloWorldApp_Final_Test"
            self.vector_config = "/opt/genpod/weaviate_config.json"
        else:
            raise ValueError(f"Unsupported vector database: {vector_db}. Use 'qdrant' or 'weaviate'.")
        
        # Note: Schema is now handled by Enhanced Graph RAG system, not hardcoded
        # self.graph_schema_prompt = self.get_comprehensive_schema_prompt()  # Removed - using Enhanced Graph RAG
        
        # Define category-specific fallback queries with WORKING examples
        # self.fallback_queries = {
        #     "Technical": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
        #             "purpose": "Find all classes and interfaces for technical analysis"
        #         },
        #         {
        #             "query": "MATCH (t1:Type)-[r:IMPLEMENTS]->(t2:Type) RETURN t1.name, t2.name, t1.file_path LIMIT 10",
        #             "purpose": "Find implementation relationships"
        #         }
        #     ],
        #     "Functional": [
        #         {
        #             "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
        #             "purpose": "Find all functions for functional analysis"
        #         },
        #         {
        #             "query": "MATCH (f1:Function)-[r:CALLS]->(f2:Function) RETURN f1.name, f2.name, f1.file_path LIMIT 10",
        #             "purpose": "Find function call relationships"
        #         }
        #     ],
        #     "Non-Functional": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
        #             "purpose": "Find all classes for quality analysis"
        #         },
        #         {
        #             "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
        #             "purpose": "Find all functions for performance analysis"
        #         }
        #     ],
        #     "Modification": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
        #             "purpose": "Find classes for modification analysis"
        #         },
        #         {
        #             "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
        #             "purpose": "Find functions for modification analysis"
        #         }
        #     ],
        #     "Feature Addition": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.name CONTAINS 'Factory' OR t.name CONTAINS 'Worker' RETURN t.name, t.file_path LIMIT 15",
        #             "purpose": "Find worker-related types for feature addition"
        #         },
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind = 'interface' RETURN t.name, t.file_path LIMIT 10",
        #             "purpose": "Find interfaces for extension"
        #         }
        #     ],
        #     "Modernization": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
        #             "purpose": "Find classes for modernization"
        #         },
        #         {
        #             "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
        #             "purpose": "Find functions for async conversion"
        #         }
        #     ],
        #     "Bug Analysis": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind = 'class' RETURN t.name, t.file_path LIMIT 15",
        #             "purpose": "Find classes for bug analysis"
        #         },
        #         {
        #             "query": "MATCH (f:Function) RETURN f.name, f.file_path LIMIT 15",
        #             "purpose": "Find functions for bug detection"
        #         }
        #     ],
        #     "Integration": [
        #         {
        #             "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
        #             "purpose": "Find types for integration analysis"
        #         },
        #         {
        #             "query": "MATCH (t1:Type)-[r:REFERENCES]->(t2:Type) RETURN t1.name, t2.name, t1.file_path LIMIT 10",
        #             "purpose": "Find type dependencies"
        #         }
        #     ]
        # }
        
        # Test scenarios - ALL 90 SCENARIOS
        self.test_scenarios = [
            # Technical Category
            {"id": "T001", "category": "Technical", "subcategory": "Architecture", "query": "Analyze the overall architecture of the HelloWorldApp. What are the main components and how do they interact?", "scenario_type": "analysis"},
            {"id": "T002", "category": "Technical", "subcategory": "Design Patterns", "query": "Find all classes in the HelloWorldApp that implement specific design patterns like Factory, Observer, or Strategy patterns.", "scenario_type": "analysis"},
            {"id": "T003", "category": "Technical", "subcategory": "Dependencies", "query": "What are the dependencies and relationships between different classes in the HelloWorldApp?", "scenario_type": "analysis"},
            {"id": "T004", "category": "Technical", "subcategory": "Class Hierarchy", "query": "Analyze the class hierarchy and inheritance structure in the HelloWorldApp.", "scenario_type": "analysis"},
            {"id": "T005", "category": "Technical", "subcategory": "Method Analysis", "query": "What are the key methods in the HelloWorldApp and their cyclomatic complexity?", "scenario_type": "analysis"},
            
            # Functional Category
            {"id": "F001", "category": "Functional", "subcategory": "Business Logic", "query": "What is the core business logic of the HelloWorldApp? How do the workers coordinate?", "scenario_type": "analysis"},
            {"id": "F002", "category": "Functional", "subcategory": "Data Flow", "query": "Trace the data flow through the HelloWorldApp from Manager to Workers.", "scenario_type": "analysis"},
            {"id": "F003", "category": "Functional", "subcategory": "Worker Coordination", "query": "How do the workers communicate with the Manager in the HelloWorldApp?", "scenario_type": "analysis"},
            {"id": "F004", "category": "Functional", "subcategory": "Factory Usage", "query": "How is the WorkerFactory used in the HelloWorldApp and what does it create?", "scenario_type": "analysis"},
            {"id": "F005", "category": "Functional", "subcategory": "Notification System", "query": "How does the notification system work in the HelloWorldApp?", "scenario_type": "analysis"},
            
            # Non-Functional Category
            # {"id": "NF001", "category": "Non-Functional", "subcategory": "Error Handling", "query": "What error handling mechanisms are present in the HelloWorldApp?", "scenario_type": "analysis"},I
            # {"id": "NF002", "category": "Non-Functional", "subcategory": "Code Quality", "query": "Assess the code quality of the HelloWorldApp. What are the main issues?", "scenario_type": "analysis"},
            # {"id": "NF003", "category": "Non-Functional", "subcategory": "Performance", "query": "What are the performance characteristics and potential bottlenecks in the HelloWorldApp?", "scenario_type": "analysis"},
            # {"id": "NF004", "category": "Non-Functional", "subcategory": "Security", "query": "What security vulnerabilities or concerns exist in the HelloWorldApp?", "scenario_type": "analysis"},
            # {"id": "NF005", "category": "Non-Functional", "subcategory": "Maintainability", "query": "How maintainable is the HelloWorldApp code? What would make it easier to maintain?", "scenario_type": "analysis"},
            # {"id": "NF006", "category": "Non-Functional", "subcategory": "Testing", "query": "What testing strategies would be appropriate for the HelloWorldApp? Where should tests be added?", "scenario_type": "analysis"},
            
            # Modification Scenarios
            # {"id": "M001", "category": "Modification", "subcategory": "Async Refactoring", "query": "How would you refactor the HelloWorldApp to use async/await patterns for better performance?", "scenario_type": "modification"},
            # {"id": "M002", "category": "Modification", "subcategory": "Error Handling", "query": "How would you improve error handling in the HelloWorldApp with try-catch blocks and logging?", "scenario_type": "modification"},
            # {"id": "M003", "category": "Modification", "subcategory": "Logging Integration", "query": "How would you integrate comprehensive logging throughout the HelloWorldApp?", "scenario_type": "modification"},
            # {"id": "M004", "category": "Modification", "subcategory": "Configuration", "query": "How would you add configuration management to the HelloWorldApp?", "scenario_type": "modification"},
            # {"id": "M005", "category": "Modification", "subcategory": "Dependency Injection", "query": "How would you implement dependency injection in the HelloWorldApp?", "scenario_type": "modification"},
            
            # Feature Addition Scenarios
            # {"id": "FA001", "category": "Feature Addition", "subcategory": "Worker Priority", "query": "How would you add a priority system to the workers in the HelloWorldApp?", "scenario_type": "feature_addition"},
            # {"id": "FA002", "category": "Feature Addition", "subcategory": "Worker Status", "query": "How would you add worker status tracking to the HelloWorldApp?", "scenario_type": "feature_addition"},
            # {"id": "FA003", "category": "Feature Addition", "subcategory": "Result Collection", "query": "How would you add result collection and aggregation to the HelloWorldApp?", "scenario_type": "feature_addition"},
            # {"id": "FA004", "category": "Feature Addition", "subcategory": "Parallel Processing", "query": "How would you add parallel processing capabilities to the HelloWorldApp?", "scenario_type": "feature_addition"},
            # {"id": "FA005", "category": "Feature Addition", "subcategory": "Worker Lifecycle", "query": "How would you add worker lifecycle management to the HelloWorldApp?", "scenario_type": "feature_addition"},
            
            # Modernization Scenarios
            # {"id": "MOD001", "category": "Modernization", "subcategory": "NET 9 Features", "query": "How would you modernize the HelloWorldApp to use .NET 9 features?", "scenario_type": "modernization"},
            # {"id": "MOD002", "category": "Modernization", "subcategory": "Modern Patterns", "query": "How would you update the HelloWorldApp to use modern design patterns?", "scenario_type": "modernization"},
            # {"id": "MOD003", "category": "Modernization", "subcategory": "API Conversion", "query": "How would you convert the HelloWorldApp to a web API?", "scenario_type": "modernization"},
            # {"id": "MOD004", "category": "Modernization", "subcategory": "Cloud Native", "query": "How would you make the HelloWorldApp cloud-native?", "scenario_type": "modernization"},
            # {"id": "MOD005", "category": "Modernization", "subcategory": "Reactive Patterns", "query": "How would you implement reactive programming patterns in the HelloWorldApp?", "scenario_type": "modernization"},
            
            # Bug Analysis Scenarios
            # {"id": "BUG001", "category": "Bug Analysis", "subcategory": "Null Reference", "query": "What potential null reference issues exist in the HelloWorldApp?", "scenario_type": "bug_analysis"},
            # {"id": "BUG002", "category": "Bug Analysis", "subcategory": "Resource Leaks", "query": "Are there any resource leaks or disposal issues in the HelloWorldApp?", "scenario_type": "bug_analysis"},
            # {"id": "BUG003", "category": "Bug Analysis", "subcategory": "Concurrency Issues", "query": "What potential concurrency issues exist in the HelloWorldApp?", "scenario_type": "bug_analysis"},
            
            # Integration Scenarios
            # {"id": "INT001", "category": "Integration", "subcategory": "Database Integration", "query": "How would you integrate the HelloWorldApp with a database?", "scenario_type": "integration"},
            # {"id": "INT002", "category": "Integration", "subcategory": "Message Queue", "query": "How would you integrate the HelloWorldApp with a message queue system?", "scenario_type": "integration"},
            # {"id": "INT003", "category": "Integration", "subcategory": "External API", "query": "How would you integrate the HelloWorldApp with external APIs?", "scenario_type": "integration"},
            
            # Deterministic Reference-Based Scenarios (T038-T060)
            # Exact Code Structure & Signatures
            {"id": "T038", "category": "Technical", "subcategory": "Method Signatures", "query": "What is the exact method signature of the CreateWorkers method in the WorkerFactory class?", "scenario_type": "factual"},
            {"id": "T039", "category": "Technical", "subcategory": "Factory Pattern", "query": "Which specific classes are instantiated and returned by the WorkerFactory.CreateWorkers() method?", "scenario_type": "factual"},
            {"id": "T040", "category": "Technical", "subcategory": "Namespace Declaration", "query": "What is the exact namespace used by all classes in the HelloWorldApp project?", "scenario_type": "factual"},
            {"id": "T041", "category": "Technical", "subcategory": "Helper Methods", "query": "What is the exact method signature of the FormatMessage method in the Helper class?", "scenario_type": "factual"},
            {"id": "T042", "category": "Technical", "subcategory": "Interface Implementation", "query": "What interface does the Manager class implement?", "scenario_type": "factual"},
            {"id": "T043", "category": "Technical", "subcategory": "Return Statements", "query": "What is the exact return statement in the Helper.FormatMessage method?", "scenario_type": "factual"},
            
            # Specific Values & Literals
            {"id": "T044", "category": "Functional", "subcategory": "Notification Messages", "query": "What exact message does WorkerA send when calling the Notify method?", "scenario_type": "factual"},
            {"id": "T045", "category": "Functional", "subcategory": "Method Parameters", "query": "What are the exact two parameters passed to Helper.FormatMessage by WorkerB?", "scenario_type": "factual"},
            {"id": "T046", "category": "Functional", "subcategory": "String Literals", "query": "What exact text does WorkerC pass as the second parameter to Helper.FormatMessage?", "scenario_type": "factual"},
            {"id": "T047", "category": "Functional", "subcategory": "Console Output", "query": "What is the exact console output message in Program.Main after manager.Run() completes?", "scenario_type": "factual"},
            {"id": "T048", "category": "Functional", "subcategory": "Manager Messages", "query": "What exact message does the Manager output when starting work?", "scenario_type": "factual"},
            
            # Interface & Inheritance Facts
            {"id": "T049", "category": "Technical", "subcategory": "Interface Definition", "query": "How many methods does the IWorker interface define and what are their exact signatures?", "scenario_type": "factual"},
            {"id": "T050", "category": "Technical", "subcategory": "Interface Methods", "query": "How many methods does the INotifier interface define and what are their exact signatures?", "scenario_type": "factual"},
            {"id": "T051", "category": "Technical", "subcategory": "Field Declarations", "query": "What is the exact field type and access modifier for the notifier field in WorkerA?", "scenario_type": "factual"},
            {"id": "T052", "category": "Technical", "subcategory": "Interface Implementations", "query": "Which classes in the project implement the IWorker interface?", "scenario_type": "factual"},
            
            # Project Configuration & Structure
            {"id": "T053", "category": "Technical", "subcategory": "Project Configuration", "query": "What is the exact TargetFramework specified in the HelloWorldApp.csproj file?", "scenario_type": "factual"},
            {"id": "T054", "category": "Technical", "subcategory": "Build Configuration", "query": "What is the exact OutputType specified in the project file?", "scenario_type": "factual"},
            {"id": "T055", "category": "Technical", "subcategory": "File Structure", "query": "How many .cs files are in the main directory (excluding subdirectories)?", "scenario_type": "factual"},
            {"id": "T056", "category": "Technical", "subcategory": "Utility Namespace", "query": "What is the exact namespace of the Helper class?", "scenario_type": "factual"},
            
            # Method Call Dependencies
            {"id": "T057", "category": "Functional", "subcategory": "Method Invocation", "query": "In the Manager.Run() method, what exact method is called on each worker in the foreach loop?", "scenario_type": "factual"},
            {"id": "T058", "category": "Functional", "subcategory": "Static Method Calls", "query": "What static method does WorkerA call to format its message?", "scenario_type": "factual"},
            {"id": "T059", "category": "Functional", "subcategory": "Program Flow", "query": "In Program.Main, what exact method is called on the manager instance?", "scenario_type": "factual"},
            {"id": "T060", "category": "Functional", "subcategory": "Message Formatting", "query": "Which class method formats the notification message that gets printed to console in each worker?", "scenario_type": "factual"},
            
            # Constructor & Field Analysis (T061-T070)
            {"id": "T061", "category": "Technical", "subcategory": "Constructor Analysis", "query": "How many parameters does the WorkerA constructor accept?", "scenario_type": "factual"},
            {"id": "T062", "category": "Technical", "subcategory": "Constructor Signatures", "query": "What is the exact constructor signature of WorkerB?", "scenario_type": "factual"},
            {"id": "T063", "category": "Technical", "subcategory": "Constructor Patterns", "query": "Which worker classes have identical constructor patterns?", "scenario_type": "factual"},
            {"id": "T064", "category": "Technical", "subcategory": "Access Modifiers", "query": "What access modifier is used for all worker constructors?", "scenario_type": "factual"},
            {"id": "T065", "category": "Technical", "subcategory": "Field Count", "query": "How many private fields does the Manager class have?", "scenario_type": "factual"},
            
            # Using Statements & Dependencies (T066-T070)
            {"id": "T066", "category": "Technical", "subcategory": "Using Statements", "query": "What using statements are present in Program.cs?", "scenario_type": "factual"},
            {"id": "T067", "category": "Technical", "subcategory": "Import Dependencies", "query": "Which files contain System.Collections.Generic using statements?", "scenario_type": "factual"},
            {"id": "T068", "category": "Technical", "subcategory": "Import Order", "query": "What is the first using statement in Manager.cs?", "scenario_type": "factual"},
            {"id": "T069", "category": "Technical", "subcategory": "Import Count", "query": "How many using statements are in WorkerFactory.cs?", "scenario_type": "factual"},
            {"id": "T070", "category": "Technical", "subcategory": "System Imports", "query": "Which class files import the System namespace explicitly?", "scenario_type": "factual"},
            
            # Comments & Documentation (T071-T075)
            {"id": "T071", "category": "Technical", "subcategory": "Code Comments", "query": "What is the exact text of the first WATCHER TEST comment in WorkerA.cs?", "scenario_type": "factual"},
            {"id": "T072", "category": "Technical", "subcategory": "Comment Count", "query": "How many comment lines are in WorkerA.cs?", "scenario_type": "factual"},
            {"id": "T073", "category": "Technical", "subcategory": "Redis Comments", "query": "What Redis-related comments appear in WorkerB.cs?", "scenario_type": "factual"},
            {"id": "T074", "category": "Technical", "subcategory": "Timestamp Comments", "query": "Which files contain timestamp comments?", "scenario_type": "factual"},
            {"id": "T075", "category": "Technical", "subcategory": "Last Comment", "query": "What is the last comment line in WorkerA.cs?", "scenario_type": "factual"},
            
            # Code Patterns & Structure (T076-T080)
            {"id": "T076", "category": "Technical", "subcategory": "Static Classes", "query": "How many classes are declared as public static?", "scenario_type": "factual"},
            {"id": "T077", "category": "Technical", "subcategory": "String Interpolation", "query": "Which methods use string interpolation ($\"...\")?", "scenario_type": "factual"},
            {"id": "T078", "category": "Technical", "subcategory": "Console Calls", "query": "How many methods call Console.WriteLine directly?", "scenario_type": "factual"},
            {"id": "T079", "category": "Technical", "subcategory": "Readonly Usage", "query": "Which classes use the readonly keyword?", "scenario_type": "factual"},
            {"id": "T080", "category": "Technical", "subcategory": "Naming Patterns", "query": "What variable naming pattern is used for private fields?", "scenario_type": "factual"},
            
            # Project File Details (T081-T085)
            {"id": "T081", "category": "Technical", "subcategory": "Project SDK", "query": "What SDK is specified in the project file?", "scenario_type": "factual"},
            {"id": "T082", "category": "Technical", "subcategory": "Project Settings", "query": "Is ImplicitUsings enabled in the project configuration?", "scenario_type": "factual"},
            {"id": "T083", "category": "Technical", "subcategory": "Root Namespace", "query": "What is the exact RootNamespace value in the project file?", "scenario_type": "factual"},
            {"id": "T084", "category": "Technical", "subcategory": "Project Structure", "query": "How many project properties are defined in the HelloWorldApp.csproj file?", "scenario_type": "factual"},
            # {"id": "T085", "category": "Technical", "subcategory": "Framework Version", "query": "What .NET version number does net9.0 represent?", "scenario_type": "factual"},
            
            # Method Implementation Details (T086-T090)
            {"id": "T086", "category": "Functional", "subcategory": "Statement Count", "query": "How many assignment statements are in Helper.FormatMessage?", "scenario_type": "factual"},
            {"id": "T087", "category": "Functional", "subcategory": "Variable Names", "query": "What variable name stores the formatted message in WorkerA?", "scenario_type": "factual"},
            {"id": "T088", "category": "Functional", "subcategory": "Control Flow", "query": "Which methods contain foreach loops?", "scenario_type": "factual"},
            {"id": "T089", "category": "Functional", "subcategory": "Method Calls", "query": "How many method calls are in Manager.Run()?", "scenario_type": "factual"},
            # {"id": "T090", "category": "Functional", "subcategory": "Parameter Length", "query": "Which worker method has the longest message parameter passed to Helper.FormatMessage?", "scenario_type": "factual"}
        ]
        
        # Filter test scenarios based on the filter
        self.filtered_scenarios = self.filter_test_scenarios()
        
    def filter_test_scenarios(self) -> List[Dict]:
        """Filter test scenarios based on the filter criteria."""
        if self.test_scenario_filter is None:
            return self.test_scenarios
        
        if isinstance(self.test_scenario_filter, int):
            return self.test_scenarios[:self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, list):
            return [s for s in self.test_scenarios if s["id"] in self.test_scenario_filter]
        
        if isinstance(self.test_scenario_filter, str):
            # Check if it's a single scenario ID first
            single_match = [s for s in self.test_scenarios if s["id"] == self.test_scenario_filter]
            if single_match:
                return single_match
            # Otherwise treat as category filter
            return [s for s in self.test_scenarios if s["category"] == self.test_scenario_filter]
        
        return self.test_scenarios

    async def create_mcp_session_with_timeout(self) -> MCPSession:
        """Create MCP session with custom timeouts for long-running workflows."""
        # Load config to get server details
        with open(self.config_file) as f:
            config = json.load(f)

        server_config = config['mcpServers']['mcp-analysis-server']

        # Create connector with custom timeouts
        # Default: timeout=5, sse_read_timeout=300 (5 minutes)
        # Custom: timeout=10, sse_read_timeout=3600 (1 hour for long workflows)
        connector = HttpConnector(
            base_url=server_config['url'],
            headers=server_config.get('headers'),
            auth_token=server_config.get('auth_token'),
            timeout=10,  # HTTP operation timeout
            sse_read_timeout=3600,  # SSE read timeout: 1 hour (for long workflows)
        )

        # Create session with custom connector
        session = MCPSession(connector)
        await session.initialize()

        logger.info("📡 MCP session created with custom SSE timeout: 3600s (1 hour)")
        return session

    # DEPRECATED: Old hardcoded schema approach - replaced with Enhanced Graph RAG
    # def get_comprehensive_schema_prompt(self) -> str:
    #     """Return comprehensive schema prompt based on actual database structure."""
    #     return """
    # Neo4j Code Property Graph Schema for HelloWorldApp (.NET):
    # 
    # ACTUAL NODE TYPES (verified):
    # - Project: Root project node
    # - File: Source files (name, file_path)
    # - Type: Classes, interfaces (name, type_kind, file_path)
    # - Variable: Local variables, fields (name, type_kind, file_path)
    # - Function: Methods, constructors (name, file_path)
    # - Namespace: Code organization (name, file_path)
    # 
    # ACTUAL RELATIONSHIPS (verified):
    # - CONTAINS: (Project|File|Type|Namespace)-[:CONTAINS]->(File|Type|Function|Variable)
    # - IMPLEMENTS: (Type)-[:IMPLEMENTS]->(Type) // class implements interface
    # - REFERENCES: (Type)-[:REFERENCES]->(Type) // type references
    # - CALLS: (Function)-[:CALLS]->(Function) // method calls
    # 
    # ACTUAL HELLOWORLDAPP DATA (verified):
    # Classes: Manager, Program, WorkerA, WorkerB, WorkerC, WorkerFactory
    # Interfaces: INotifier, IWorker
    # Functions: Run, Notify, Main, Process, CreateWorkers
    # Files: Manager.cs, Program.cs, WorkerA.cs, WorkerB.cs, WorkerC.cs, WorkerFactory.cs, INotifier.cs, IWorker.cs, Helper.cs
    # """

    # DEPRECATED: Old hardcoded LLM query generation - replaced with Enhanced Graph RAG
    # async def generate_cypher_queries_with_llm(self, user_query: str, category: str = "Technical") -> list:
    #     """Generate Cypher queries using GPT-4o with proper fallbacks."""
    #     
    #     # Try LLM generation first
    #     if OpenAI:
    #         try:
    #             client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    #             
    #             system_prompt = f"""You are an expert Neo4j Cypher query generator for code analysis.
    # 
    # {self.graph_schema_prompt}
    # 
    # Generate 1-2 Cypher queries that:
    # 1. Are syntactically correct Neo4j Cypher
    # 2. Use the ACTUAL node types and relationships listed above
    # 3. Return meaningful results for the user's question
    # 4. Include appropriate LIMIT clauses (10-15 results)
    # 5. Use relevant WHERE clauses for filtering
    # 6. Focus on the HelloWorldApp codebase
    # 
    # Return ONLY a JSON array: [{{"query": "MATCH...", "purpose": "description"}}]"""
    # 
    #             response = client.chat.completions.create(
    #                 model="gpt-4o-2024-08-06",
    #                 messages=[
    #                     {"role": "system", "content": system_prompt},
    #                     {"role": "user", "content": f"User Query: {user_query}"}
    #                 ],
    #                 temperature=0.1,
    #                 max_tokens=1000
    #             )
    #             
    #             response_text = response.choices[0].message.content.strip()
    #             
    #             # Clean up response to extract JSON
    #             if "```json" in response_text:
    #                 response_text = response_text.split("```json")[1].split("```")[0].strip()
    #             elif "```" in response_text:
    #                 response_text = response_text.split("```")[1].split("```")[0].strip()
    #             
    #             try:
    #                 queries = json.loads(response_text)
    #                 if isinstance(queries, list) and len(queries) > 0:
    #                     logger.info(f"✅ LLM generated {len(queries)} queries for category: {category}")
    #                     return queries
    #             except json.JSONDecodeError:
    #                 logger.warning(f"❌ LLM response not valid JSON: {response_text[:200]}...")
    #                 
    #         except Exception as e:
    #             logger.error(f"❌ LLM call failed: {e}")
    #     
    #     # Fall back to category-specific queries
    #     if category in self.fallback_queries:
    #         fallback = self.fallback_queries[category]
    #         logger.info(f"🔄 Using fallback queries for category: {category}")
    #         return fallback
    #     else:
    #         # Default fallback
    #         logger.warning(f"⚠️  Using default fallback for unknown category: {category}")
    #         return [
    #             {
    #                 "query": "MATCH (t:Type) WHERE t.type_kind IN ['class', 'interface'] RETURN t.name, t.type_kind, t.file_path LIMIT 15",
    #                 "purpose": "Find all classes and interfaces"
    #             }
    #         ]

    async def run_vector_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using query_vector_only MCP tool with vector database support."""
        start_time = time.time()
        session = None

        try:
            # Create session with custom timeouts for long-running workflows
            session = await self.create_mcp_session_with_timeout()

            result = await session.call_tool(
                "query_vector_only",
                {
                    "query": query,
                    "collection_name": self.collection_name,
                    "max_results": 5,
                    "output_format": "json",
                    "vector_db": self.vector_db,
                    "config": self.vector_config,
                    "enable_reasoning": True,
                    "max_branches": 2
                }
            )
            
            # PICKLE DUMP: Save raw MCP result for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            pickle_file = pickle_dir / f"vector_raw_response_{timestamp_str}.pkl"
            
            with open(pickle_file, 'wb') as f:
                pickle.dump(result, f)
            print(f"🐍 SAVED VECTOR RAW MCP RESULT: {pickle_file}")
            
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Parse the enhanced vector response structure
            try:
                parsed_result = json.loads(content_text)

                if isinstance(parsed_result, dict) and parsed_result.get("status") == "success":
                    return {
                        "status": "success",
                        "ai_response": parsed_result.get("ai_response", ""),
                        "raw_results": parsed_result.get("raw_results", []),
                        "response": parsed_result.get("ai_response", ""),  # For backward compatibility
                        "response_time_ms": response_time_ms,
                        "error": "",
                        "metadata": {
                            "vector_total_results": parsed_result.get("metadata", {}).get("total_results", 0),
                            "vector_processing_time": parsed_result.get("metadata", {}).get("processing_time", 0),
                            "vector_confidence_score": parsed_result.get("metadata", {}).get("confidence_score"),
                            "has_diagram": parsed_result.get("metadata", {}).get("has_diagram", False),
                            "reasoning_used": parsed_result.get("metadata", {}).get("reasoning_used", False),
                            "reasoning_metrics": parsed_result.get("metadata", {}).get("reasoning_metrics"),
                        },
                        "reasoning_trace": parsed_result.get("reasoning_trace"),
                        "full_response": content_text
                    }
                else:
                    # Fallback for old format or errors
                    return {
                        "status": parsed_result.get("status", "error"),
                        "ai_response": content_text,
                        "raw_results": [],
                        "response": content_text,
                        "response_time_ms": response_time_ms,
                        "error": parsed_result.get("error", "Unknown error"),
                        "metadata": {},
                        "full_response": content_text
                    }
                    
            except json.JSONDecodeError:
                # Fallback to treating as raw text (old behavior)
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
                    "response": content_text,
                    "response_time_ms": response_time_ms,
                    "error": "JSON parsing failed, using raw output",
                    "metadata": {},
                    "full_response": content_text
                }
                
        except Exception as e:
            logger.error(f"Vector query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
        finally:
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Session cleanup warning: {cleanup_error}")

    async def run_pageindex_only_query(self, query: str) -> Dict[str, Any]:
        """Run query using query_pageindex_only MCP tool (MCTS-based file tree navigation)."""
        start_time = time.time()

        try:
            session = await self.create_mcp_session_with_timeout()

            result = await session.call_tool(
                "query_pageindex_only",
                {
                    "query": query,
                    "project_path": self.project_path,
                    "mcts_iterations": 20,
                    "config": self.vector_config,
                    "output_format": "json"
                }
            )

            # PICKLE DUMP: Save raw MCP result for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)

            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            pickle_file = pickle_dir / f"pageindex_raw_response_{timestamp_str}.pkl"

            with open(pickle_file, 'wb') as f:
                pickle.dump(result, f)
            print(f"🐍 SAVED PAGEINDEX RAW MCP RESULT: {pickle_file}")

            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)

            response_time_ms = int((time.time() - start_time) * 1000)

            try:
                parsed_result = json.loads(content_text)

                if isinstance(parsed_result, dict) and parsed_result.get("status") == "success":
                    return {
                        "status": "success",
                        "ai_response": parsed_result.get("ai_response", ""),
                        "raw_results": parsed_result.get("raw_results", []),
                        "response": parsed_result.get("ai_response", ""),
                        "response_time_ms": response_time_ms,
                        "error": "",
                        "metadata": {
                            "pageindex_total_results": parsed_result.get("metadata", {}).get("total_results", 0),
                            "pageindex_processing_time": parsed_result.get("metadata", {}).get("processing_time", 0),
                            "pageindex_confidence_score": parsed_result.get("metadata", {}).get("confidence_score"),
                            "mcts_iterations": parsed_result.get("metadata", {}).get("mcts_iterations", 20),
                        },
                        "full_response": content_text
                    }
                else:
                    return {
                        "status": parsed_result.get("status", "error"),
                        "ai_response": content_text,
                        "raw_results": [],
                        "response": content_text,
                        "response_time_ms": response_time_ms,
                        "error": parsed_result.get("error", "Unknown error"),
                        "metadata": {},
                        "full_response": content_text
                    }

            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
                    "response": content_text,
                    "response_time_ms": response_time_ms,
                    "error": "JSON parsing failed, using raw output",
                    "metadata": {},
                    "full_response": content_text
                }

        except Exception as e:
            logger.error(f"PageIndex query failed: {e}")
            return {
                "status": "error",
                "ai_response": "",
                "raw_results": [],
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e),
                "metadata": {}
            }
        finally:
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Session cleanup warning: {cleanup_error}")

    async def run_cpg_only_query(self, query: str, category: str = "Technical") -> Dict[str, Any]:
        """Run query using Enhanced Graph RAG with sophisticated retrieval."""
        start_time = time.time()
        session = None

        try:
            # Create session with custom timeouts for long-running workflows
            session = await self.create_mcp_session_with_timeout()

            result = await session.call_tool(
                "query_cpg_rag",
                {
                    "user_query": query,
                    "project_name": "HelloWorldApp",
                    "config_path": self.neo4j_config,
                    "project_path": self.project_path,
                    "mappings_path": "/opt/genpod/project_analyzer_cli/project_analyzer/parsing_utils/mappings.yaml",
                    "queries_path": "/opt/genpod/project_analyzer_cli/project_analyzer/final_queries",
                    "max_results": 100,
                    "max_agent_iterations": 25,  # Increased from 10 to 25 for complex queries
                    "parallel_agents": False,  # Sequential execution for deterministic results
                    # Note: max_parallel_workers not used - 4-agent team runs all sub-queries in parallel without worker limits
                    "use_4_agent_team": True,  # Enable sophisticated 4-agent team workflow
                    "four_agent_max_iterations": 3  # Limit iterations per 4-agent cycle
                }
            )
            
            # PICKLE DUMP: Save raw MCP result for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            pickle_file = pickle_dir / f"cpg_raw_response_{timestamp_str}.pkl"
            
            with open(pickle_file, 'wb') as f:
                pickle.dump(result, f)
            print(f"🐍 SAVED CPG RAW MCP RESULT: {pickle_file}")
            
            # Parse result - extract content text first
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            try:
                result_data = json.loads(content_text)
                
                # DEBUG: Print full CPG response structure
                print(f"🔍 CPG DEBUG - Full result_data keys: {list(result_data.keys()) if isinstance(result_data, dict) else 'Not dict'}")
                if isinstance(result_data, dict):
                    raw_results_from_response = result_data.get("raw_results", [])
                    print(f"🔍 CPG DEBUG - raw_results type: {type(raw_results_from_response)}")
                    print(f"🔍 CPG DEBUG - raw_results length: {len(raw_results_from_response) if isinstance(raw_results_from_response, list) else 'Not list'}")
                    if isinstance(raw_results_from_response, list) and len(raw_results_from_response) > 0:
                        print(f"🔍 CPG DEBUG - First raw result keys: {list(raw_results_from_response[0].keys()) if isinstance(raw_results_from_response[0], dict) else 'Not dict'}")
                    else:
                        print(f"🔍 CPG DEBUG - raw_results is empty or not list!")
                        # Check for alternative locations
                        print(f"🔍 CPG DEBUG - Checking for 'results' key: {'results' in result_data}")
                        print(f"🔍 CPG DEBUG - Checking for 'graph_results' key: {'graph_results' in result_data}")
                        print(f"🔍 CPG DEBUG - All available keys: {list(result_data.keys())}")
                
                # Extract key components for benchmarking compatibility - Based on pickle analysis
                # CPG has response as a DICT with keys: ['answer', 'details', 'confidence', 'status', 'suggestions']
                response_data = result_data.get("response", {})
                
                # Raw results are directly available 
                raw_results = result_data.get("raw_results", [])
                
                return {
                    "status": result_data.get("status", "success"),
                    "ai_response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),  # CPG response.answer
                    "raw_results": raw_results,  # CPG raw results 
                    "response": response_data.get("answer", "") if isinstance(response_data, dict) else str(response_data),  # CPG response.answer
                    "response_time_ms": response_time_ms,
                    "error": "",
                    "workflow": result_data.get("workflow_type", "langgraph_agent_rag"),
                    "analysis_type": result_data.get("analysis_type", "cpg_rag"),
                    "synthesis": response_data if isinstance(response_data, dict) else {"answer": str(response_data)},  # CPG response object
                    "metadata": {
                        "cpg_execution_time": result_data.get("cpg_execution_time", 0),
                        "total_execution_time": result_data.get("total_execution_time", 0),
                        "confidence": response_data.get("confidence", 0.0) if isinstance(response_data, dict) else 0.0,
                        "status": response_data.get("status", "success") if isinstance(response_data, dict) else "success"
                    },
                    "full_response": content_text
                }
                
            except json.JSONDecodeError:
                # Fallback to treating as raw text
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
                    "response": content_text,
                    "response_time_ms": response_time_ms,
                    "error": "JSON parsing failed, using raw output",
                    "workflow": "enhanced_graph_rag",
                    "entities_extracted": {},
                    "analysis_type": "enhanced_rag",
                    "retrieval_plan": {},
                    "full_response": content_text
                }
                
        except Exception as e:
            logger.error(f"CPG query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
        finally:
            # CRITICAL: Always disconnect session to prevent connection leaks
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Session cleanup warning: {cleanup_error}")

    async def run_comprehensive_query(self, query: str, category: str = "Technical") -> Dict[str, Any]:
        """Run comprehensive query using both vector and CPG approaches."""
        start_time = time.time()
        session = None

        try:
            # Use query_comprehensive_rag MCP tool (updated to match test script)
            client = MCPClient.from_config_file(self.config_file)
            session = await client.create_session("mcp-analysis-server")
            
            result = await session.call_tool(
                "query_comprehensive_rag",
                {
                    "user_query": query,
                    "project_name": "HelloWorldApp",
                    "collection_name": self.collection_name,
                    "max_agent_iterations": 10,  # Add parameter that the test script uses
                    "project_path": self.project_path,
                    "max_results": 100,
                    "neo4j_config": self.neo4j_config  # Neo4j config
                }
            )
            
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            # Try to parse the response to extract metadata and raw results from NEW format
            metadata = {}
            parsed_response = content_text
            raw_results = []
            
            try:
                import json
                parsed_data = json.loads(content_text)
                
                # DEBUG: Print comprehensive tool response structure
                print(f"🔍 COMPREHENSIVE DEBUG - Full response keys: {list(parsed_data.keys()) if isinstance(parsed_data, dict) else 'Not dict'}")
                if isinstance(parsed_data, dict):
                    print(f"🔍 COMPREHENSIVE DEBUG - analysis_type: {parsed_data.get('analysis_type')}")
                    print(f"🔍 COMPREHENSIVE DEBUG - Has synthesis: {'synthesis' in parsed_data}")
                    print(f"🔍 COMPREHENSIVE DEBUG - Has synthesis_metadata: {'synthesis_metadata' in parsed_data}")
                    print(f"🔍 COMPREHENSIVE DEBUG - Has vector_raw_results: {'vector_raw_results' in parsed_data}")
                    print(f"🔍 COMPREHENSIVE DEBUG - Has cpg_raw_results: {'cpg_raw_results' in parsed_data}")
                    print(f"🔍 COMPREHENSIVE DEBUG - Has hybrid_results: {'hybrid_results' in parsed_data}")
                
                if isinstance(parsed_data, dict):
                    # CURRENT FORMAT: Standard comprehensive analysis with vector + cpg results
                    if "vector_rag_results" in parsed_data and "cpg_rag_results" in parsed_data:
                        # Extract the main response (AI synthesis)
                        response = parsed_data.get("response", "")
                        if response:
                            parsed_response = response
                        
                        # Extract vector and CPG results
                        vector_rag_results = parsed_data.get("vector_rag_results", [])
                        cpg_rag_results = parsed_data.get("cpg_rag_results", [])
                        all_raw_results = parsed_data.get("raw_results", [])
                        
                        # If raw_results is missing or incomplete, combine vector + cpg results
                        if len(all_raw_results) < len(vector_rag_results) + len(cpg_rag_results):
                            # Combine both vector and CPG results for comprehensive coverage
                            combined_results = []
                            
                            # Add vector results
                            if vector_rag_results:
                                combined_results.extend(vector_rag_results)
                            
                            # Add CPG results  
                            if cpg_rag_results:
                                combined_results.extend(cpg_rag_results)
                            
                            # Use combined if we have more results than raw_results
                            if len(combined_results) > len(all_raw_results):
                                all_raw_results = combined_results
                        
                        # Extract validation metadata
                        validation_meta = parsed_data.get("validation_metadata", {})
                        agent_meta = parsed_data.get("agent_metadata", {})
                        data_sources = parsed_data.get("data_sources", {})
                        
                        # Compile metadata for benchmarking
                        metadata.update({
                            "synthesis_status": "success" if response else "unknown",
                            "analysis_type": "comprehensive_analysis",
                            "workflow": "vector_plus_cpg",
                            "vector_sources": len(vector_rag_results),
                            "cpg_queries": len(cpg_rag_results),
                            "successful_cpg_queries": len(cpg_rag_results),  # All returned results are successful
                            "total_results": len(all_raw_results),
                            "data_sources": data_sources,
                            "validation_metadata": validation_meta,
                            "agent_metadata": agent_meta,
                            
                            # Use all raw results as main results
                            "vector_raw_results": vector_rag_results,
                            "cpg_raw_results": cpg_rag_results
                        })
                        
                        # Use combined raw results
                        raw_results = all_raw_results
                        
                    # NEW HYBRID FORMAT (if implemented later)
                    elif parsed_data.get("analysis_type") == "hybrid_comprehensive_analysis":
                        # Extract synthesis (the actual AI response)
                        synthesis = parsed_data.get("synthesis", "")
                        if synthesis:
                            parsed_response = synthesis
                        
                        # Extract raw results arrays
                        vector_raw_results = parsed_data.get("vector_raw_results", [])
                        cpg_raw_results = parsed_data.get("cpg_raw_results", [])
                        hybrid_results = parsed_data.get("hybrid_results", [])
                        
                        # Generate synthesis metadata from actual data
                        vector_sources = len(vector_raw_results)
                        cpg_queries = len(cpg_raw_results)
                        total_hybrid_results = len(hybrid_results)
                        
                        # Compile metadata for benchmarking
                        metadata.update({
                            "synthesis_status": "success",
                            "analysis_type": parsed_data.get("analysis_type", "unknown"),
                            "workflow": parsed_data.get("workflow", "enhanced_graph_rag"),
                            "vector_sources": vector_sources,
                            "cpg_queries": cpg_queries,
                            "successful_cpg_queries": cpg_queries,
                            "total_hybrid_results": total_hybrid_results,
                            "entities_extracted": parsed_data.get("entities_extracted", {}),
                            
                            "vector_raw_results": vector_raw_results,
                            "cpg_raw_results": cpg_raw_results
                        })
                        
                        raw_results = hybrid_results
                    
                    # FALLBACK: OLD FORMAT (for backward compatibility)
                    elif "results" in parsed_data and isinstance(parsed_data["results"], dict):
                        steps = parsed_data["results"].get("steps", {})
                        if "5_synthesis" in steps:
                            synthesis_step = steps["5_synthesis"]
                            metadata.update({
                                "synthesis_metadata": synthesis_step.get("synthesis_metadata", {}),
                                "synthesis_status": synthesis_step.get("summary", {}).get("synthesis_status", "unknown"),
                                "vector_sources": synthesis_step.get("summary", {}).get("vector_search_results", 0),
                                "cpg_queries": synthesis_step.get("summary", {}).get("cypher_queries_generated", 0),
                                "successful_cpg_queries": synthesis_step.get("summary", {}).get("successful_cpg_queries", 0),
                                "analysis_type": "legacy_comprehensive",
                                "workflow": "legacy",
                                "actor_critic_enabled": False
                            })
                        
                        # Extract raw results from old format
                        if "1_vector_search" in steps:
                            vector_step = steps["1_vector_search"]
                            if "raw_output" in vector_step:
                                if isinstance(vector_step["raw_output"], list):
                                    raw_results.extend(vector_step["raw_output"])
                        
                        # Use synthesis response if available
                        if "5_synthesis" in steps:
                            synthesis_response = steps["5_synthesis"].get("comprehensive_response", "")
                            if synthesis_response:
                                parsed_response = synthesis_response
                                
            except (json.JSONDecodeError, KeyError, AttributeError):
                # If parsing fails, use original content and empty metadata
                pass
            
            return {
                "status": "success",
                "response": parsed_response,
                "raw_results": raw_results,  # Add raw results extraction
                "response_time_ms": response_time_ms,
                "error": "",
                "metadata": metadata
            }
                
        except Exception as e:
            logger.error(f"Comprehensive query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
        finally:
            # CRITICAL: Always disconnect session to prevent connection leaks
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Session cleanup warning: {cleanup_error}")

    async def run_hybrid_query(self, query: str, category: str = "Technical", retriever_combination: str = "pageindex_vector_graph") -> Dict[str, Any]:
        """Run hybrid query using the new query_hybrid_rag MCP tool."""
        start_time = time.time()
        session = None

        try:
            # Create session with custom timeouts for long-running workflows
            session = await self.create_mcp_session_with_timeout()

            result = await session.call_tool(
                "query_hybrid_rag",
                {
                    "user_query": query,
                    "project_name": "HelloWorldApp",
                    "collection_name": self.collection_name,
                    "vector_config_path": "/opt/genpod/qdrant_config.json",
                    "config_path": self.neo4j_config,
                    "project_path": self.project_path,
                    "vector_db": self.vector_db,
                    "enable_reasoning": True,
                    "max_branches": 2,
                    "max_results": 5,
                    "batch_size": 5,
                    "max_context_limit": 100000,
                    "parallel_agents": False,
                    "use_4_agent_team": True,
                    "four_agent_max_iterations": 3,
                    "retriever_combination": retriever_combination,
                }
            )
            
            # PICKLE DUMP: Save raw MCP result for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            pickle_file = pickle_dir / f"hybrid_raw_response_{timestamp_str}.pkl"
            
            with open(pickle_file, 'wb') as f:
                pickle.dump(result, f)
            print(f"🐍 SAVED HYBRID RAW MCP RESULT: {pickle_file}")
            
            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, 'text') else str(result_content)
            
            response_time_ms = int((time.time() - start_time) * 1000)
            
            try:
                result_data = json.loads(content_text)
                
                # DEBUG: Print hybrid tool response structure
                print(f"🔍 HYBRID DEBUG - Full response keys: {list(result_data.keys()) if isinstance(result_data, dict) else 'Not dict'}")
                if isinstance(result_data, dict):
                    print(f"🔍 HYBRID DEBUG - analysis_type: {result_data.get('analysis_type')}")
                    print(f"🔍 HYBRID DEBUG - Has synthesis: {'synthesis' in result_data}")
                    print(f"🔍 HYBRID DEBUG - Has vector_raw_results: {'vector_raw_results' in result_data}")
                    print(f"🔍 HYBRID DEBUG - Has cpg_raw_results: {'cpg_raw_results' in result_data}")
                    print(f"🔍 HYBRID DEBUG - Has intent_analysis: {'intent_analysis' in result_data}")
                    print(f"🔍 HYBRID DEBUG - Has critic_validation: {'critic_validation' in result_data}")
                
                # Extract key components for benchmarking compatibility - New Hybrid format
                # Handle synthesis as string or dict - based on actual response structure
                synthesis = result_data.get("synthesis", "")
                synthesis_dict = synthesis if isinstance(synthesis, dict) else {"answer": synthesis}
                
                # Handle intent_analysis and critic_validation - may not exist in simple responses
                intent_analysis = result_data.get("intent_analysis", {})
                critic_validation = result_data.get("critic_validation", {})
                
                # Raw results are directly in the response, not nested
                raw_results = result_data.get("raw_results", [])

                # Extract reasoning metadata from retrieval results (hybrid uses vector retrieval internally)
                retrieval_results = result_data.get("retrieval_results", {})
                vector_metadata = retrieval_results.get("vector", {})
                reasoning_used = vector_metadata.get("reasoning_used", False)
                reasoning_metrics = vector_metadata.get("reasoning_metrics")
                reasoning_trace = vector_metadata.get("reasoning_trace")

                return {
                    "status": result_data.get("status", "success"),
                    "ai_response": result_data.get("response", synthesis if isinstance(synthesis, str) else synthesis_dict.get("answer", "")),  # Direct response field
                    "raw_results": raw_results,  # Direct raw results
                    "response": result_data.get("response", synthesis if isinstance(synthesis, str) else synthesis_dict.get("answer", "")),  # Direct response field
                    "response_time_ms": response_time_ms,
                    "error": "",
                    "workflow": "hybrid_rag",
                    "analysis_type": result_data.get("analysis_type", "hybrid_rag"),
                    "synthesis": synthesis_dict,  # Normalized synthesis object
                    "intent_analysis": intent_analysis,  # Intent analysis results (may be empty)
                    "critic_validation": critic_validation,  # Critic validation results (may be empty)
                    "cross_validation": synthesis_dict.get("cross_validation", {}),  # Cross-validation results
                    "metadata": {
                        "hybrid_execution_time": result_data.get("total_execution_time", 0),
                        "vector_execution_time": result_data.get("vector_execution_time", 0),
                        "cpg_execution_time": result_data.get("cpg_execution_time", 0),
                        "synthesis_confidence": synthesis_dict.get("confidence", 0.0),
                        "synthesis_status": result_data.get("synthesis_status", "success" if synthesis else "unknown"),
                        "synthesis_strategy": synthesis_dict.get("strategy_used", "unknown"),
                        "intent": intent_analysis.get("intent", "unknown"),
                        "vector_weight": intent_analysis.get("vector_weight", 0.5),
                        "cpg_weight": intent_analysis.get("cpg_weight", 0.5),
                        "critic_overall_score": critic_validation.get("overall_score", 0.0),
                        "vector_results_count": len(result_data.get("vector_raw_results", [])),
                        "cpg_results_count": len(result_data.get("cpg_raw_results", [])),
                        "reasoning_used": reasoning_used,
                        "reasoning_metrics": reasoning_metrics,
                    },
                    "reasoning_trace": reasoning_trace,
                    "vector_raw_results": result_data.get("vector_raw_results", []),
                    "cpg_raw_results": result_data.get("cpg_raw_results", []),
                    # Full individual RAG responses for hybrid-only mode
                    "pageindex_full_response": result_data.get("pageindex_full_response", {}),
                    "vector_full_response": result_data.get("vector_full_response", {}),
                    "cpg_full_response": result_data.get("cpg_full_response", {}),
                    "full_response": content_text
                }
                
            except json.JSONDecodeError:
                # Fallback to treating as raw text
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
                    "response": content_text,
                    "response_time_ms": response_time_ms,
                    "error": "JSON parsing failed, using raw output",
                    "workflow": "hybrid_rag",
                    "analysis_type": "hybrid_rag",
                    "full_response": content_text
                }
                
        except Exception as e:
            logger.error(f"Hybrid query failed: {e}")
            return {
                "status": "error",
                "response": "",
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e)
            }
        finally:
            # CRITICAL: Always disconnect session to prevent connection leaks
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected successfully")
                except Exception as cleanup_error:
                    logger.warning(f"Session cleanup warning: {cleanup_error}")

    async def run_comparative_analysis(self) -> tuple[List[Dict[str, Any]], str]:
        """Run comparative analysis across all filtered scenarios with incremental saving and resume capability."""
        # Load existing results if any
        results, timestamp = self.load_existing_results()
        completed_ids = {r['query_id'] for r in results} if results else set()
        
        print(f"🚀 Starting Properly Fixed Comparative Analysis Suite")
        print(f"📊 Total scenarios to run: {len(self.filtered_scenarios)}")
        print(f"📂 Previously completed: {len(completed_ids)}")
        print(f"🔄 Remaining to process: {len(self.filtered_scenarios) - len(completed_ids)}")
        print(f"🕐 Timestamp: {timestamp}")
        print(f"🔧 Vector-RAG: Using JSON output format")
        print(f"🔧 CPG: Using improved LLM generation with fallbacks")
        print(f"💾 Results will be saved to: /opt/Test_Suite_Benchmarking/ (JSON format with CSV/Excel backups)")
        print("=" * 80)
        
        for i, scenario in enumerate(self.filtered_scenarios, 1):
            # Skip if already completed
            if scenario['id'] in completed_ids:
                print(f"\n[{i}/{len(self.filtered_scenarios)}] ⏭️  Skipping (already completed): {scenario['id']} - {scenario['category']}")
                continue
                
            print(f"\n[{i}/{len(self.filtered_scenarios)}] Processing: {scenario['id']} - {scenario['category']}")
            print(f"Query: {scenario['query'][:100]}...")

            # Dispatch to selected tool
            hybrid_result   = {}
            vector_result   = {'status': 'skipped', 'ai_response': '', 'response': '', 'raw_results': [], 'response_time_ms': 0, 'error': '', 'metadata': {}, 'reasoning_trace': None}
            cpg_result      = {'status': 'skipped', 'response': '', 'raw_results': [], 'response_time_ms': 0, 'error': '', 'synthesis': {'answer': '', 'details': '', 'confidence': 0.0, 'suggestions': []}}
            pageindex_result = {'status': 'skipped', 'ai_response': '', 'raw_results': [], 'metadata': {}, 'response_time_ms': 0, 'error': ''}

            if self.tool == "hybrid":
                hybrid_result    = await self.run_hybrid_query(scenario['query'], scenario['category'], self.retriever_combination)
                pageindex_full   = hybrid_result.get('pageindex_full_response', {})
                vector_full      = hybrid_result.get('vector_full_response', {})
                cpg_full         = hybrid_result.get('cpg_full_response', {})
                cpg_metadata     = cpg_full.get('metadata', {})
                pageindex_result = {
                    'status':           pageindex_full.get('status', 'not_executed'),
                    'ai_response':      pageindex_full.get('ai_response', ''),
                    'raw_results':      pageindex_full.get('raw_results', []),
                    'metadata':         pageindex_full.get('metadata', {}),
                    'response_time_ms': pageindex_full.get('execution_time_ms', 0),
                    'error':            pageindex_full.get('error', ''),
                }
                vector_result = {
                    'status':           vector_full.get('status', 'success') if vector_full else 'error',
                    'ai_response':      vector_full.get('ai_response', ''),
                    'response':         vector_full.get('ai_response', ''),
                    'raw_results':      vector_full.get('raw_results', []),
                    'response_time_ms': vector_full.get('execution_time_ms', 0),
                    'error':            vector_full.get('error', ''),
                    'metadata':         vector_full.get('metadata', {}),
                    'reasoning_trace':  vector_full.get('metadata', {}).get('reasoning_trace')
                }
                cpg_result = {
                    'status':           cpg_full.get('status', 'success') if cpg_full else 'error',
                    'response':         cpg_full.get('ai_response', ''),
                    'raw_results':      cpg_full.get('raw_results', []),
                    'response_time_ms': cpg_full.get('execution_time_ms', 0),
                    'error':            cpg_full.get('error', ''),
                    'synthesis': {
                        'answer':      cpg_full.get('ai_response', ''),
                        'details':     '',
                        'confidence':  cpg_metadata.get('confidence', 0.0),
                        'suggestions': []
                    }
                }

            elif self.tool == "vector":
                vector_result = await self.run_vector_only_query(scenario['query'])

            elif self.tool == "pageindex":
                pageindex_result = await self.run_pageindex_only_query(scenario['query'])

            elif self.tool == "cpg":
                cpg_result = await self.run_cpg_only_query(scenario['query'], scenario['category'])

            # Extract structured data from all retrievers for evaluation framework
            vector_metadata = vector_result.get('metadata', {})
            vector_reasoning_trace = vector_result.get('reasoning_trace')
            hybrid_metadata = hybrid_result.get('metadata', {})
            
            # Extract hybrid workflow components - handle both string and dict synthesis
            intent_analysis = hybrid_result.get('intent_analysis', {})
            synthesis_raw = hybrid_result.get('synthesis', {})  # Can be string or dict
            synthesis_result = synthesis_raw if isinstance(synthesis_raw, dict) else {"answer": synthesis_raw}
            critic_result = hybrid_result.get('critic_validation', {})  # Fixed: use 'critic_validation' not 'critic_result'
            cross_validation = hybrid_result.get('cross_validation', {})
            
            # Parse CPG response - Enhanced Graph RAG returns direct structure (like test_all_tools.py)
            cpg_ai_response = cpg_result.get('response', '')  # CPG response is in 'response' field
            cpg_raw_results = cpg_result.get('raw_results', [])
            cpg_synthesis_status = "success" if cpg_result.get('status') == 'success' else "unknown"
            
            # Compile results for evaluation framework
            result = {
                # Query Information
                "query_id": scenario['id'],
                "user_query": scenario['query'],
                "query_category": scenario['category'],
                "query_subcategory": scenario['subcategory'],
                "scenario_type": scenario['scenario_type'],
                "timestamp": timestamp,
                
                # VECTOR RETRIEVER - For Reference-based and Reference-free Evaluation
                "vector_status": vector_result['status'],
                "vector_ai_response": vector_result.get('ai_response', vector_result.get('response', '')),  # For reference-free eval
                "vector_raw_results_json": json.dumps(vector_result.get('raw_results', [])),  # For reference-based eval
                "vector_metadata_json": json.dumps(vector_metadata),  # Performance metrics
                "vector_response_time_ms": vector_result['response_time_ms'],
                "vector_error": vector_result['error'],

                # VECTOR REASONING METADATA - ToT+CoT specific metrics
                "vector_reasoning_used": vector_metadata.get('reasoning_used', False),
                "vector_reasoning_metrics_json": json.dumps(vector_metadata.get('reasoning_metrics')) if vector_metadata.get('reasoning_metrics') else None,
                "vector_reasoning_trace_json": json.dumps(vector_reasoning_trace) if vector_reasoning_trace else None,
                
                # CPG RETRIEVER - For Reference-based and Reference-free Evaluation  
                "cpg_status": cpg_result['status'],
                "cpg_ai_response": cpg_ai_response,  # For reference-free eval (main answer)
                "cpg_details": cpg_result.get('synthesis', {}).get('details', '') if isinstance(cpg_result.get('synthesis', {}), dict) else '',  # Detailed response
                "cpg_suggestions": cpg_result.get('synthesis', {}).get('suggestions', []) if isinstance(cpg_result.get('synthesis', {}), dict) else [],  # Suggestions array
                "cpg_confidence": cpg_result.get('synthesis', {}).get('confidence', 0.0) if isinstance(cpg_result.get('synthesis', {}), dict) else 0.0,  # Confidence score
                "cpg_raw_results_json": json.dumps(cpg_raw_results),  # For reference-based eval
                "cpg_synthesis_status": cpg_synthesis_status,  # Synthesis quality
                "cpg_response_time_ms": cpg_result['response_time_ms'],
                "cpg_error": cpg_result['error'],
                
                # HYBRID RETRIEVER - For Reference-based and Reference-free Evaluation
                "hybrid_status": hybrid_result['status'],
                "hybrid_ai_response": hybrid_result.get('response', synthesis_result.get('answer', '')),  # Use direct response field first
                "hybrid_raw_results_json": json.dumps(hybrid_result.get('raw_results', [])),  # For reference-based eval
                "hybrid_metadata_json": json.dumps(hybrid_metadata),  # Hybrid workflow metrics
                "hybrid_response_time_ms": hybrid_result['response_time_ms'],
                "hybrid_error": hybrid_result['error'],
                
                # HYBRID WORKFLOW COMPONENTS - For Advanced Evaluation Framework Analysis
                "intent_analysis_json": json.dumps(intent_analysis),
                "synthesis_result_json": json.dumps(synthesis_result),
                "critic_result_json": json.dumps(critic_result),
                "cross_validation_json": json.dumps(cross_validation),
                
                # SYNTHESIS QUALITY METRICS - For Evaluation Framework Analysis
                "synthesis_status": hybrid_result.get('synthesis_status', 'success' if synthesis_result.get('answer') else 'unknown'),
                "synthesis_confidence": synthesis_result.get('confidence', synthesis_result.get('confidence_score', 0.0)),
                "synthesis_reasoning": synthesis_result.get('reasoning', ''),
                "cross_validation_score": cross_validation.get('confidence_score', 0.0) if isinstance(cross_validation, dict) else 0.0,
                "cross_validation_conflicts": cross_validation.get('conflicts_found', 0) if isinstance(cross_validation, dict) else 0,
                "cross_validation_consensus": cross_validation.get('consensus_points', 0) if isinstance(cross_validation, dict) else 0,

                # PAGEINDEX RETRIEVER - For Reference-based and Reference-free Evaluation
                "pageindex_status": pageindex_result.get('status', 'error'),
                "pageindex_ai_response": pageindex_result.get('ai_response', pageindex_result.get('response', '')),
                "pageindex_raw_results_json": json.dumps(pageindex_result.get('raw_results', [])),
                "pageindex_metadata_json": json.dumps(pageindex_result.get('metadata', {})),
                "pageindex_response_time_ms": pageindex_result.get('response_time_ms', 0),
                "pageindex_error": pageindex_result.get('error', ''),
}
            
            # DEBUG: Final check of what goes into JSON
            print(f"🔍 FINAL JSON DEBUG - cpg_raw_results_json length: {len(result['cpg_raw_results_json'])}")
            if result['cpg_raw_results_json'] != '[]':
                print(f"🔍 FINAL JSON DEBUG - CPG JSON contains: {result['cpg_raw_results_json'][:300]}...")
            else:
                print(f"🔍 FINAL JSON DEBUG - CPG JSON is empty array: {result['cpg_raw_results_json']}")
            print(f"🔍 HYBRID DEBUG - synthesis answer: {synthesis_result.get('answer', '')[:100]}...")
            print(f"🔍 HYBRID DEBUG - cross validation score: {cross_validation.get('confidence_score', 0.0)}")
            
            results.append(result)
            
            # Print progress with hybrid workflow info
            print(f"  ✅ Vector: {vector_result['status']} ({vector_result['response_time_ms']}ms)")
            print(f"  ✅ CPG: {cpg_result['status']} ({cpg_result['response_time_ms']}ms)")
            print(f"  ✅ Hybrid: {hybrid_result['status']} ({hybrid_result['response_time_ms']}ms)")
            print(f"  ✅ PageIndex: {pageindex_result.get('status', 'error')} ({pageindex_result.get('response_time_ms', 0)}ms)")
            if synthesis_result:
                print(f"    🔍 Synthesis: {synthesis_result.get('confidence_score', 0.0)} confidence | Cross-validation: {cross_validation.get('confidence_score', 0.0)} score | Conflicts: {cross_validation.get('conflicts_found', 0)}")
            
            # Save results incrementally after each scenario
            self.save_incremental_results(results, timestamp)
            
        return results, timestamp

    def load_existing_results(self) -> tuple[List[Dict[str, Any]], str]:
        """Load existing results from JSON file if it exists, return results and timestamp."""
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        json_file = output_dir / "properly_fixed_comparative_analysis_current.json"
        
        if json_file.exists():
            try:
                with open(json_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    results = data.get('results', [])
                    timestamp = data.get('timestamp', datetime.now().strftime("%Y%m%d_%H%M%S"))
                print(f"📂 Loaded {len(results)} existing results from {json_file}")
                print(f"🔄 Resuming analysis with timestamp: {timestamp}")
                return results, timestamp
            except Exception as e:
                print(f"⚠️  Failed to load existing results: {e}")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                return [], timestamp
        else:
            print(f"📄 No existing results found - starting fresh")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return [], timestamp
    
    def save_incremental_results(self, results: List[Dict[str, Any]], timestamp: str):
        """Save results incrementally after each scenario."""
        if not results:
            return
        
        # Create output directory
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        output_dir.mkdir(exist_ok=True)
        
        # Save to current JSON (for resuming) - main format
        json_file = output_dir / "properly_fixed_comparative_analysis_current.json"
        json_data = {
            "timestamp": timestamp,
            "total_scenarios": len(self.test_scenarios),
            "completed_scenarios": len(results),
            "results": results
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        # Also save to CSV and Excel for compatibility
        df = pd.DataFrame(results)
        csv_file = output_dir / "properly_fixed_comparative_analysis_current.csv"
        df.to_csv(csv_file, index=False)
        
        excel_file = output_dir / "properly_fixed_comparative_analysis_current.xlsx"
        try:
            df.to_excel(excel_file, index=False, engine='openpyxl')
        except Exception:
            # Don't fail on Excel errors
            pass
            
        print(f"💾 Saved {len(results)} results to {json_file} (and CSV/Excel backups)")

    def save_final_results(self, results: List[Dict[str, Any]], timestamp: str):
        """Save final results to timestamped files and clean up current files."""
        # Create output directory
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        output_dir.mkdir(exist_ok=True)
        
        # Save to final timestamped JSON file (main format)
        json_file = output_dir / f"properly_fixed_comparative_analysis_{timestamp}.json"
        final_json_data = {
            "timestamp": timestamp,
            "total_scenarios": len(self.test_scenarios),
            "completed_scenarios": len(results),
            "metadata": {
                "created_by": "properly_fixed_comparative_analysis.py",
                "enhanced_features": [
                    "JSON output with clean vector-rag CLI integration",
                    "Enhanced CPG semantic queries with rich node properties",
                    "Proper raw data extraction for both vector and CPG results",
                    "Comprehensive synthesis metadata capture"
                ]
            },
            "results": results
        }
        
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(final_json_data, f, indent=2, ensure_ascii=False)
        
        # Also save to CSV and Excel for compatibility
        df = pd.DataFrame(results)
        csv_file = output_dir / f"properly_fixed_comparative_analysis_{timestamp}.csv"
        excel_file = output_dir / f"properly_fixed_comparative_analysis_{timestamp}.xlsx"
        
        df.to_csv(csv_file, index=False)
        
        try:
            df.to_excel(excel_file, index=False, engine='openpyxl')
            print(f"\n✅ Final results saved to:")
            print(f"  📋 JSON: {json_file}")
            print(f"  📄 CSV: {csv_file}")
            print(f"  📊 Excel: {excel_file}")
        except ImportError:
            print(f"\n✅ Final results saved to:")
            print(f"  📋 JSON: {json_file}")
            print(f"  📄 CSV: {csv_file}")
            print(f"  ⚠️  Excel: Skipped (openpyxl not installed)")
        except Exception as e:
            print(f"\n✅ Final results saved to:")
            print(f"  📋 JSON: {json_file}")
            print(f"  📄 CSV: {csv_file}")
            print(f"  ❌ Excel: Failed ({str(e)})")
        
        # CRASH RECOVERY FIX: Only clean up current files if ALL scenarios completed
        total_expected_scenarios = len(self.test_scenarios)
        actual_scenarios_completed = len(results)
        
        if actual_scenarios_completed >= total_expected_scenarios:
            # Clean up current files only when truly complete
            try:
                (output_dir / "properly_fixed_comparative_analysis_current.json").unlink(missing_ok=True)
                (output_dir / "properly_fixed_comparative_analysis_current.csv").unlink(missing_ok=True)
                (output_dir / "properly_fixed_comparative_analysis_current.xlsx").unlink(missing_ok=True)
                print(f"🧹 Cleaned up temporary files (all {total_expected_scenarios} scenarios completed)")
            except Exception:
                pass
        else:
            print(f"⚠️  Keeping current.json for resume capability ({actual_scenarios_completed}/{total_expected_scenarios} scenarios completed)")
            print(f"💡 Resume by running the script again - it will continue from where it left off")
        
        print(f"📊 Total scenarios processed: {len(results)}")
        
        # Print summary statistics (exclude skipped from denominator)
        vector_applicable  = [r for r in results if r['vector_status'] != 'skipped']
        cpg_applicable     = [r for r in results if r['cpg_status'] != 'skipped']
        vector_success     = len([r for r in vector_applicable  if r['vector_status'] == 'success'])
        cpg_success        = len([r for r in cpg_applicable     if r['cpg_status'] == 'success'])
        hybrid_success     = len([r for r in results if r['hybrid_status'] == 'success'])
        pageindex_success  = len([r for r in results if r.get('pageindex_status') == 'success'])
        synthesis_success  = len([r for r in results if r.get('synthesis_status') == 'success'])

        def _rate(n, total):
            return f"{n}/{total} ({n/total*100:.1f}%)" if total > 0 else "0/0 (n/a)"

        if len(results) > 0:
            print(f"\n📈 Success Rates:")
            print(f"  Vector:    {_rate(vector_success, len(vector_applicable))}")
            print(f"  CPG:       {_rate(cpg_success, len(cpg_applicable))}")
            print(f"  Hybrid:    {_rate(hybrid_success, len(results))}")
            print(f"  PageIndex: {_rate(pageindex_success, len(results))}")
            print(f"  Synthesis: {_rate(synthesis_success, len(results))}")
        else:
            print(f"\n⚠️  No results to analyze - check scenario filter")
        
        # Print synthesis statistics
        if synthesis_success > 0:
            avg_synthesis_confidence = sum([r.get('synthesis_confidence', 0.0) for r in results if r.get('synthesis_status') == 'success']) / synthesis_success
            avg_cross_validation_score = sum([r.get('cross_validation_score', 0.0) for r in results if r.get('synthesis_status') == 'success']) / synthesis_success
            # cross_validation_consensus may be a list (conflicts) - get its length if so
            consensus_values = []
            for r in results:
                if r.get('synthesis_status') == 'success':
                    val = r.get('cross_validation_consensus', 0)
                    consensus_values.append(len(val) if isinstance(val, list) else val)
            avg_cross_validation_consensus = sum(consensus_values) / synthesis_success if consensus_values else 0
            
            print(f"\n🔍 Hybrid Workflow Statistics (for successful syntheses):")
            print(f"  Average synthesis confidence: {avg_synthesis_confidence:.2f}")
            print(f"  Average cross-validation score: {avg_cross_validation_score:.2f}")
            print(f"  Average consensus points per analysis: {avg_cross_validation_consensus:.1f}")
        
        return json_file, csv_file, excel_file

def main():
    """Main function to run the properly fixed comparative analysis."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run properly fixed comparative analysis")
    parser.add_argument("--scenarios", type=str, default="all",
                       help="Scenarios to run: 'all' (default), number (e.g., '5'), category (e.g., 'Technical'), or comma-separated IDs (e.g., 'T001,T002,F001')")
    parser.add_argument("--retriever-combination", type=str, default="pageindex_vector_graph",
                       help="Retriever combination: pageindex_vector_graph (default), pageindex_vector, pageindex_graph, pageindex_and_graph, pageindex_and_vector")
    parser.add_argument("--tool", type=str, default="hybrid",
                       choices=["hybrid", "vector", "pageindex", "cpg"],
                       help="Tool to run per scenario: hybrid (default), vector, pageindex, cpg")

    args = parser.parse_args()

    # Parse scenario filter
    if args.scenarios == "all":
        scenario_filter = None
    elif args.scenarios.isdigit():
        scenario_filter = int(args.scenarios)
    elif "," in args.scenarios:
        scenario_filter = args.scenarios.split(",")
    else:
        scenario_filter = args.scenarios

    retriever_combination = args.retriever_combination
    tool = args.tool
    print(f"🎯 Running with scenario filter: {scenario_filter}")
    print(f"🔧 Tool: {tool}")
    print(f"🔧 Retriever combination: {retriever_combination}")

    async def run_analysis():
        analyzer = ProperlyFixedComparativeAnalyzer(
            test_scenario_filter=scenario_filter,
            retriever_combination=retriever_combination,
            tool=tool,
        )
        
        # Run the analysis
        results, timestamp = await analyzer.run_comparative_analysis()
        
        # Save final results
        json_file, csv_file, excel_file = analyzer.save_final_results(results, timestamp)
        
        print(f"\n🎉 Properly Fixed Comparative Analysis completed!")
        print(f"📁 Results saved to JSON (primary), CSV and Excel formats")
        
        return json_file, csv_file, excel_file
    
    return asyncio.run(run_analysis())

if __name__ == "__main__":
    main()