#!/usr/bin/env python3
"""
Test script for the project-analyzer CLI cypher-server mode.
Tests functionality, performance, and cleanup mechanisms.
"""

import asyncio
import json
import subprocess
import time
import logging
from typing import Dict, Any, Optional, List
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CypherServerTester:
    """Test harness for the cypher-server mode functionality."""
    
    def __init__(self, neo4j_config_path: str = "/opt/genpod/neo4j_config.json"):
        self.neo4j_config_path = neo4j_config_path
        self.server_process: Optional[subprocess.Popen] = None
        
    def start_cypher_server(self) -> bool:
        """Start the cypher-server process."""
        try:
            logger.info("Starting cypher-server process...")
            cmd = [
                "project-analyzer", 
                "--config-file", self.neo4j_config_path,
                "cypher-server",
                "--input-mode", "stdin",
                "--buffer-size", "8192",
                "--timeout", "30"
            ]
            
            self.server_process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Give the server time to start
            time.sleep(2)
            
            if self.server_process.poll() is None:
                logger.info("Cypher-server started successfully")
                return True
            else:
                stderr = self.server_process.stderr.read() if self.server_process.stderr else ""
                logger.error(f"Cypher-server failed to start: {stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error starting cypher-server: {e}")
            return False
    
    def send_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Send a single query to the cypher-server."""
        if not self.server_process:
            logger.error("Server process not started")
            return None
            
        try:
            request = {
                "query": query,
                "params": params or {}
            }
            
            logger.info(f"Sending query: {query[:100]}...")
            
            # Send request
            json_request = json.dumps(request) + "\n"
            self.server_process.stdin.write(json_request)
            self.server_process.stdin.flush()
            
            # Read response
            response_line = self.server_process.stdout.readline()
            if not response_line:
                logger.error("No response received from server")
                return None
                
            response = json.loads(response_line.strip())
            logger.info(f"Received response with {len(str(response))} characters")
            return response
            
        except Exception as e:
            logger.error(f"Error sending query: {e}")
            return None
    
    def send_batch_queries(self, queries: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Send multiple queries in sequence."""
        results = []
        
        for i, query_data in enumerate(queries):
            logger.info(f"Sending batch query {i+1}/{len(queries)}")
            result = self.send_query(query_data.get("query"), query_data.get("params"))
            if result:
                results.append(result)
            else:
                logger.warning(f"Query {i+1} failed")
                results.append({"success": False, "error": "Query failed"})
                
        return results
    
    def test_basic_functionality(self) -> bool:
        """Test basic query execution."""
        logger.info("Testing basic functionality...")
        
        # Simple test query
        query = "MATCH (n) RETURN count(n) as node_count LIMIT 1"
        result = self.send_query(query)
        
        if result and result.get("success", False):
            logger.info(f"Basic test passed: {result}")
            return True
        else:
            logger.error(f"Basic test failed: {result}")
            return False
    
    def test_connection_recovery(self) -> bool:
        """Test automatic connection recovery."""
        logger.info("Testing connection recovery...")
        
        # Send a query that might stress the connection
        query = """
        MATCH (n) 
        WITH count(n) as total
        RETURN total, 'connection_test' as test_type
        """
        
        # Send multiple queries to test persistence
        for i in range(3):
            logger.info(f"Connection recovery test {i+1}/3")
            result = self.send_query(query)
            if not result or not result.get("success", False):
                logger.error(f"Connection recovery test failed at iteration {i+1}")
                return False
            time.sleep(1)
        
        logger.info("Connection recovery test passed")
        return True
    
    def test_error_handling(self) -> bool:
        """Test error handling with invalid queries."""
        logger.info("Testing error handling...")
        
        # Invalid Cypher query
        invalid_query = "INVALID CYPHER SYNTAX HERE"
        result = self.send_query(invalid_query)
        
        if result and "error" in result:
            logger.info(f"Error handling test passed: {result.get('error')}")
            return True
        else:
            logger.error("Error handling test failed - should have returned an error")
            return False
    
    def test_performance(self) -> Dict[str, float]:
        """Test performance compared to subprocess calls."""
        logger.info("Testing performance...")
        
        test_query = "MATCH (n) RETURN count(n) as total LIMIT 1"
        num_queries = 5
        
        # Test hot CLI performance
        start_time = time.time()
        for i in range(num_queries):
            self.send_query(test_query)
        hot_cli_time = time.time() - start_time
        
        logger.info(f"Hot CLI: {num_queries} queries in {hot_cli_time:.2f}s")
        
        # Test traditional subprocess performance (for comparison)
        start_time = time.time()
        for i in range(num_queries):
            try:
                cmd = [
                    "project-analyzer",
                    "--config-file", self.neo4j_config_path,
                    "query",
                    "--query", test_query
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired:
                logger.warning(f"Subprocess query {i+1} timed out")
        
        subprocess_time = time.time() - start_time
        
        logger.info(f"Subprocess: {num_queries} queries in {subprocess_time:.2f}s")
        
        performance_improvement = ((subprocess_time - hot_cli_time) / subprocess_time) * 100
        logger.info(f"Performance improvement: {performance_improvement:.1f}%")
        
        return {
            "hot_cli_time": hot_cli_time,
            "subprocess_time": subprocess_time,
            "improvement_percent": performance_improvement
        }
    
    def test_shutdown_command(self) -> bool:
        """Test graceful shutdown functionality."""
        logger.info("Testing shutdown command...")
        
        # Send shutdown command
        shutdown_request = {
            "command": "shutdown",
            "reason": "test_cleanup"
        }
        
        try:
            json_request = json.dumps(shutdown_request) + "\n"
            self.server_process.stdin.write(json_request)
            self.server_process.stdin.flush()
            
            # Wait for process to terminate
            try:
                self.server_process.wait(timeout=10)
                logger.info("Server shut down gracefully")
                return True
            except subprocess.TimeoutExpired:
                logger.warning("Server did not shut down within timeout")
                return False
                
        except Exception as e:
            logger.error(f"Error during shutdown test: {e}")
            return False
    
    def cleanup(self):
        """Force cleanup of server process."""
        if self.server_process:
            if self.server_process.poll() is None:
                logger.info("Terminating server process...")
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning("Force killing server process...")
                    self.server_process.kill()
                    self.server_process.wait()
            
            self.server_process = None
            logger.info("Server process cleaned up")

async def run_comprehensive_test():
    """Run comprehensive test suite."""
    tester = CypherServerTester()
    
    test_results = {
        "server_start": False,
        "basic_functionality": False,
        "connection_recovery": False,
        "error_handling": False,
        "performance": {},
        "shutdown": False
    }
    
    try:
        # Start server
        test_results["server_start"] = tester.start_cypher_server()
        if not test_results["server_start"]:
            logger.error("Failed to start server - aborting tests")
            return test_results
        
        # Run tests
        test_results["basic_functionality"] = tester.test_basic_functionality()
        test_results["connection_recovery"] = tester.test_connection_recovery()
        test_results["error_handling"] = tester.test_error_handling()
        test_results["performance"] = tester.test_performance()
        test_results["shutdown"] = tester.test_shutdown_command()
        
        # Summary
        logger.info("\n=== TEST RESULTS ===")
        for test_name, result in test_results.items():
            if test_name == "performance":
                logger.info(f"{test_name}: {result}")
            else:
                status = "PASS" if result else "FAIL"
                logger.info(f"{test_name}: {status}")
        
        return test_results
        
    finally:
        # Ensure cleanup
        tester.cleanup()

if __name__ == "__main__":
    # Check if config file exists
    config_path = "/opt/genpod/neo4j_config.json"
    if not Path(config_path).exists():
        logger.error(f"Neo4j config file not found: {config_path}")
        logger.error("Please create the config file or update the path in the script")
        exit(1)
    
    # Run tests
    results = asyncio.run(run_comprehensive_test())
    
    # Exit with appropriate code
    all_passed = all([
        results["server_start"],
        results["basic_functionality"], 
        results["connection_recovery"],
        results["error_handling"],
        results["shutdown"]
    ])
    
    exit(0 if all_passed else 1)