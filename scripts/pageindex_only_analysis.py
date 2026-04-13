#!/usr/bin/env python3
"""
PageIndex-Only Analysis Suite

Runs only the query_pageindex_only MCP tool across all benchmark scenarios
and saves results in the same JSON format as properly_fixed_comparative_analysis.py.
Supports incremental saving and resume on crash.
"""

import asyncio
import json
import logging
import time
import pickle
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime

import pandas as pd
from mcp_use import MCPSession
from mcp_use.connectors.http import HttpConnector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PageIndexOnlyAnalyzer:
    def __init__(self, test_scenario_filter=None, mcts_iterations: int = 20):
        """
        Initialize the PageIndex-only analyzer.

        Args:
            test_scenario_filter: Can be:
                - None: Run all scenarios (DEFAULT)
                - int: Run first N scenarios (e.g., 5)
                - list: Run specific scenario IDs (e.g., ['T001', 'T002'])
                - str: Run single ID or category (e.g., 'Technical')
            mcts_iterations: MCTS search iterations per query (default: 20)
        """
        self.config_file = "/opt/genpod/file_watcher_mcp_config.json"
        self.project_path = "/opt/HelloWorldApp"
        self.vector_config = "/opt/genpod/qdrant_config.json"
        self.mcts_iterations = mcts_iterations
        self.test_scenario_filter = test_scenario_filter

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

            # Constructor & Field Analysis
            {"id": "T061", "category": "Technical", "subcategory": "Constructor Analysis", "query": "How many parameters does the WorkerA constructor accept?", "scenario_type": "factual"},
            {"id": "T062", "category": "Technical", "subcategory": "Constructor Signatures", "query": "What is the exact constructor signature of WorkerB?", "scenario_type": "factual"},
            {"id": "T063", "category": "Technical", "subcategory": "Constructor Patterns", "query": "Which worker classes have identical constructor patterns?", "scenario_type": "factual"},
            {"id": "T064", "category": "Technical", "subcategory": "Access Modifiers", "query": "What access modifier is used for all worker constructors?", "scenario_type": "factual"},
            {"id": "T065", "category": "Technical", "subcategory": "Field Count", "query": "How many private fields does the Manager class have?", "scenario_type": "factual"},

            # Using Statements & Dependencies
            {"id": "T066", "category": "Technical", "subcategory": "Using Statements", "query": "What using statements are present in Program.cs?", "scenario_type": "factual"},
            {"id": "T067", "category": "Technical", "subcategory": "Import Dependencies", "query": "Which files contain System.Collections.Generic using statements?", "scenario_type": "factual"},
            {"id": "T068", "category": "Technical", "subcategory": "Import Order", "query": "What is the first using statement in Manager.cs?", "scenario_type": "factual"},
            {"id": "T069", "category": "Technical", "subcategory": "Import Count", "query": "How many using statements are in WorkerFactory.cs?", "scenario_type": "factual"},
            {"id": "T070", "category": "Technical", "subcategory": "System Imports", "query": "Which class files import the System namespace explicitly?", "scenario_type": "factual"},

            # Comments & Documentation
            {"id": "T071", "category": "Technical", "subcategory": "Code Comments", "query": "What is the exact text of the first WATCHER TEST comment in WorkerA.cs?", "scenario_type": "factual"},
            {"id": "T072", "category": "Technical", "subcategory": "Comment Count", "query": "How many comment lines are in WorkerA.cs?", "scenario_type": "factual"},
            {"id": "T073", "category": "Technical", "subcategory": "Redis Comments", "query": "What Redis-related comments appear in WorkerB.cs?", "scenario_type": "factual"},
            {"id": "T074", "category": "Technical", "subcategory": "Timestamp Comments", "query": "Which files contain timestamp comments?", "scenario_type": "factual"},
            {"id": "T075", "category": "Technical", "subcategory": "Last Comment", "query": "What is the last comment line in WorkerA.cs?", "scenario_type": "factual"},

            # Code Patterns & Structure
            {"id": "T076", "category": "Technical", "subcategory": "Static Classes", "query": "How many classes are declared as public static?", "scenario_type": "factual"},
            {"id": "T077", "category": "Technical", "subcategory": "String Interpolation", "query": "Which methods use string interpolation ($\"...\")?", "scenario_type": "factual"},
            {"id": "T078", "category": "Technical", "subcategory": "Console Calls", "query": "How many methods call Console.WriteLine directly?", "scenario_type": "factual"},
            {"id": "T079", "category": "Technical", "subcategory": "Readonly Usage", "query": "Which classes use the readonly keyword?", "scenario_type": "factual"},
            {"id": "T080", "category": "Technical", "subcategory": "Naming Patterns", "query": "What variable naming pattern is used for private fields?", "scenario_type": "factual"},

            # Project File Details
            {"id": "T081", "category": "Technical", "subcategory": "Project SDK", "query": "What SDK is specified in the project file?", "scenario_type": "factual"},
            {"id": "T082", "category": "Technical", "subcategory": "Project Settings", "query": "Is ImplicitUsings enabled in the project configuration?", "scenario_type": "factual"},
            {"id": "T083", "category": "Technical", "subcategory": "Root Namespace", "query": "What is the exact RootNamespace value in the project file?", "scenario_type": "factual"},
            {"id": "T084", "category": "Technical", "subcategory": "Project Structure", "query": "How many project properties are defined in the HelloWorldApp.csproj file?", "scenario_type": "factual"},

            # Method Implementation Details
            {"id": "T086", "category": "Functional", "subcategory": "Statement Count", "query": "How many assignment statements are in Helper.FormatMessage?", "scenario_type": "factual"},
            {"id": "T087", "category": "Functional", "subcategory": "Variable Names", "query": "What variable name stores the formatted message in WorkerA?", "scenario_type": "factual"},
            {"id": "T088", "category": "Functional", "subcategory": "Control Flow", "query": "Which methods contain foreach loops?", "scenario_type": "factual"},
            {"id": "T089", "category": "Functional", "subcategory": "Method Calls", "query": "How many method calls are in Manager.Run()?", "scenario_type": "factual"},
        ]

        self.filtered_scenarios = self._filter_scenarios()

    def _filter_scenarios(self) -> List[Dict]:
        f = self.test_scenario_filter
        if f is None:
            return self.test_scenarios
        if isinstance(f, int):
            return self.test_scenarios[:f]
        if isinstance(f, list):
            return [s for s in self.test_scenarios if s["id"] in f]
        if isinstance(f, str):
            single = [s for s in self.test_scenarios if s["id"] == f]
            if single:
                return single
            return [s for s in self.test_scenarios if s["category"] == f]
        return self.test_scenarios

    async def _create_session(self) -> MCPSession:
        """Create MCP session with extended SSE timeout."""
        with open(self.config_file) as f:
            config = json.load(f)
        server_config = config["mcpServers"]["mcp-analysis-server"]
        connector = HttpConnector(
            base_url=server_config["url"],
            headers=server_config.get("headers"),
            auth_token=server_config.get("auth_token"),
            timeout=10,
            sse_read_timeout=3600,
        )
        session = MCPSession(connector)
        await session.initialize()
        logger.info("📡 MCP session created (SSE timeout: 3600s)")
        return session

    async def run_pageindex_query(self, query: str) -> Dict[str, Any]:
        """Run a single query via query_pageindex_only MCP tool."""
        start_time = time.time()
        session = None

        try:
            session = await self._create_session()

            result = await session.call_tool(
                "query_pageindex_only",
                {
                    "query": query,
                    "project_path": self.project_path,
                    "mcts_iterations": self.mcts_iterations,
                    "config": self.vector_config,
                    "output_format": "json"
                }
            )

            # Pickle dump for debugging
            pickle_dir = Path("/opt/genpod/mcp_debug_dumps")
            pickle_dir.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            pickle_file = pickle_dir / f"pageindex_raw_{ts}.pkl"
            with open(pickle_file, "wb") as f:
                pickle.dump(result, f)
            print(f"🐍 SAVED PAGEINDEX RAW MCP RESULT: {pickle_file}")

            result_content = result.content[0] if isinstance(result.content, list) else result.content
            content_text = result_content.text if hasattr(result_content, "text") else str(result_content)
            response_time_ms = int((time.time() - start_time) * 1000)

            try:
                parsed = json.loads(content_text)

                if isinstance(parsed, dict) and parsed.get("status") == "success":
                    metadata = parsed.get("metadata", {})
                    return {
                        "status": "success",
                        "ai_response": parsed.get("ai_response", ""),
                        "raw_results": parsed.get("raw_results", []),
                        "response_time_ms": response_time_ms,
                        "error": "",
                        "metadata": {
                            "total_results": metadata.get("total_results", 0),
                            "processing_time": metadata.get("processing_time", 0),
                            "confidence_score": metadata.get("confidence_score"),
                            "mcts_iterations": self.mcts_iterations,
                            "faithfulness_score": metadata.get("faithfulness_score"),
                            "coverage_score": metadata.get("coverage_score"),
                            "unsupported_claims": metadata.get("unsupported_claims", []),
                            "uncovered_topics": metadata.get("uncovered_topics", []),
                            "hallucinated_count": metadata.get("hallucinated_count"),
                            "hallucinated_entities": metadata.get("hallucinated_entities", []),
                            "answer_identifiers": metadata.get("answer_identifiers"),
                            "symbol_table_size": metadata.get("symbol_table_size"),
                        },
                        "full_response": content_text
                    }
                else:
                    return {
                        "status": parsed.get("status", "error"),
                        "ai_response": "",
                        "raw_results": [],
                        "response_time_ms": response_time_ms,
                        "error": parsed.get("error", "Unknown error"),
                        "metadata": {},
                        "full_response": content_text
                    }

            except json.JSONDecodeError:
                return {
                    "status": "success",
                    "ai_response": content_text,
                    "raw_results": [],
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
                "response_time_ms": int((time.time() - start_time) * 1000),
                "error": str(e),
                "metadata": {},
                "full_response": ""
            }
        finally:
            if session is not None:
                try:
                    await session.disconnect()
                    logger.info("🔌 MCP session disconnected")
                except Exception as e:
                    logger.warning(f"Session cleanup warning: {e}")

    async def run_analysis(self) -> tuple[List[Dict[str, Any]], str]:
        """Run pageindex queries across all filtered scenarios with resume support."""
        results, timestamp = self._load_existing_results()
        completed_ids = {r["query_id"] for r in results}

        print(f"🚀 Starting PageIndex-Only Analysis Suite")
        print(f"📊 Total scenarios: {len(self.filtered_scenarios)}")
        print(f"📂 Already completed: {len(completed_ids)}")
        print(f"🔄 Remaining: {len(self.filtered_scenarios) - len(completed_ids)}")
        print(f"🕐 Timestamp: {timestamp}")
        print(f"🔧 Retriever: pageindex  |  MCTS iterations: {self.mcts_iterations}")
        print(f"💾 Output: /opt/Test_Suite_Benchmarking/pageindex_only_analysis_current.json")
        print("=" * 80)

        for i, scenario in enumerate(self.filtered_scenarios, 1):
            if scenario["id"] in completed_ids:
                print(f"\n[{i}/{len(self.filtered_scenarios)}] ⏭️  Skipping (done): {scenario['id']} - {scenario['subcategory']}")
                continue

            print(f"\n[{i}/{len(self.filtered_scenarios)}] Processing: {scenario['id']} - {scenario['subcategory']}")
            print(f"Query: {scenario['query'][:100]}...")

            pageindex_result = await self.run_pageindex_query(scenario["query"])

            result = {
                # Query metadata
                "query_id": scenario["id"],
                "user_query": scenario["query"],
                "query_category": scenario["category"],
                "query_subcategory": scenario["subcategory"],
                "scenario_type": scenario["scenario_type"],
                "timestamp": timestamp,

                # PageIndex retriever output
                "pageindex_status": pageindex_result["status"],
                "pageindex_ai_response": pageindex_result["ai_response"],
                "pageindex_raw_results_json": json.dumps(pageindex_result["raw_results"]),
                "pageindex_metadata_json": json.dumps(pageindex_result["metadata"]),
                "pageindex_response_time_ms": pageindex_result["response_time_ms"],
                "pageindex_error": pageindex_result["error"],
            }

            print(f"  ✅ PageIndex: {pageindex_result['status']} ({pageindex_result['response_time_ms']}ms) | "
                  f"results: {len(pageindex_result['raw_results'])} | "
                  f"confidence: {pageindex_result['metadata'].get('confidence_score', 'n/a')}")

            results.append(result)
            self._save_incremental(results, timestamp)

        return results, timestamp

    def _load_existing_results(self) -> tuple[List[Dict[str, Any]], str]:
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        json_file = output_dir / "pageindex_only_analysis_current.json"

        if json_file.exists():
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                results = data.get("results", [])
                timestamp = data.get("timestamp", datetime.now().strftime("%Y%m%d_%H%M%S"))
                print(f"📂 Loaded {len(results)} existing results — resuming with timestamp: {timestamp}")
                return results, timestamp
            except Exception as e:
                print(f"⚠️  Failed to load existing results: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        print(f"📄 No existing results — starting fresh")
        return [], timestamp

    def _save_incremental(self, results: List[Dict[str, Any]], timestamp: str):
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        output_dir.mkdir(exist_ok=True)

        json_file = output_dir / "pageindex_only_analysis_current.json"
        data = {
            "timestamp": timestamp,
            "total_scenarios": len(self.test_scenarios),
            "completed_scenarios": len(results),
            "retriever": "pageindex",
            "mcts_iterations": self.mcts_iterations,
            "results": results
        }
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        df = pd.DataFrame(results)
        df.to_csv(output_dir / "pageindex_only_analysis_current.csv", index=False)
        try:
            df.to_excel(output_dir / "pageindex_only_analysis_current.xlsx", index=False, engine="openpyxl")
        except Exception:
            pass

        print(f"💾 Saved {len(results)} results incrementally")

    def save_final_results(self, results: List[Dict[str, Any]], timestamp: str):
        output_dir = Path("/opt/Test_Suite_Benchmarking")
        output_dir.mkdir(exist_ok=True)

        json_file = output_dir / f"pageindex_only_analysis_{timestamp}.json"
        data = {
            "timestamp": timestamp,
            "total_scenarios": len(self.test_scenarios),
            "completed_scenarios": len(results),
            "retriever": "pageindex",
            "mcts_iterations": self.mcts_iterations,
            "results": results
        }
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        df = pd.DataFrame(results)
        csv_file = output_dir / f"pageindex_only_analysis_{timestamp}.csv"
        excel_file = output_dir / f"pageindex_only_analysis_{timestamp}.xlsx"
        df.to_csv(csv_file, index=False)
        try:
            df.to_excel(excel_file, index=False, engine="openpyxl")
            print(f"\n✅ Final results saved:")
            print(f"  📋 JSON:  {json_file}")
            print(f"  📄 CSV:   {csv_file}")
            print(f"  📊 Excel: {excel_file}")
        except Exception as e:
            print(f"\n✅ Final results saved:")
            print(f"  📋 JSON: {json_file}")
            print(f"  📄 CSV:  {csv_file}")
            print(f"  ❌ Excel: {e}")

        # Clean up current files only when fully complete
        if len(results) >= len(self.test_scenarios):
            for suffix in ["current.json", "current.csv", "current.xlsx"]:
                try:
                    (output_dir / f"pageindex_only_analysis_{suffix}").unlink(missing_ok=True)
                except Exception:
                    pass
            print(f"🧹 Cleaned up temporary files")
        else:
            print(f"⚠️  Keeping current.json for resume ({len(results)}/{len(self.test_scenarios)} complete)")

        # Summary stats
        success = len([r for r in results if r["pageindex_status"] == "success"])
        print(f"\n📈 PageIndex Success Rate: {success}/{len(results)} ({success/len(results)*100:.1f}%)" if results else "\n⚠️  No results")

        avg_time = sum(r["pageindex_response_time_ms"] for r in results) / len(results) if results else 0
        print(f"⏱️  Average response time: {avg_time/1000:.1f}s")

        return json_file, csv_file, excel_file


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run PageIndex-only benchmark analysis")
    parser.add_argument("--scenarios", type=str, default="all",
                        help="Scenarios to run: 'all', number (e.g. '5'), category, or comma-separated IDs")
    parser.add_argument("--mcts-iterations", type=int, default=20,
                        help="MCTS iterations per query (default: 20)")
    args = parser.parse_args()

    if args.scenarios == "all":
        scenario_filter = None
    elif args.scenarios.isdigit():
        scenario_filter = int(args.scenarios)
    elif "," in args.scenarios:
        scenario_filter = args.scenarios.split(",")
    else:
        scenario_filter = args.scenarios

    print(f"🎯 Scenario filter: {scenario_filter}  |  MCTS iterations: {args.mcts_iterations}")

    async def run():
        analyzer = PageIndexOnlyAnalyzer(
            test_scenario_filter=scenario_filter,
            mcts_iterations=args.mcts_iterations
        )
        results, timestamp = await analyzer.run_analysis()
        analyzer.save_final_results(results, timestamp)
        print(f"\n🎉 PageIndex-Only Analysis complete!")

    asyncio.run(run())


if __name__ == "__main__":
    main()
