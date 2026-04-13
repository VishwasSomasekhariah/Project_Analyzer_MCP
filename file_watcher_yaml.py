# file_monitor_service.py
# import asyncio
# import logging
# import argparse
# import os
# import time
# import sys
# from pathlib import Path
# from mcp_use import MCPClient

# # Watchdog imports
# from watchdog.events import FileSystemEventHandler
# from watchdog.observers import Observer

# # Set up logging
# logging.basicConfig(level=logging.INFO, 
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# class MCPFileEventHandler(FileSystemEventHandler):
#     """File system event handler that notifies MCP server of changes"""
    
#     def __init__(self, mcp_service, supported_extensions=None, ignore_dirs=None):
#         """
#         Initialize the event handler.
        
#         Args:
#             mcp_service: Reference to the MCPFileMonitorService
#             supported_extensions: List of file extensions to monitor
#             ignore_dirs: List of directories to ignore
#         """
#         self.mcp_service = mcp_service
#         self.supported_extensions = supported_extensions or [".py", ".js", ".ts"]
#         self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "venv"]
#         self.changed_files = set()
#         self.analysis_in_progress = False
        
#     def on_any_event(self, event):
#         """Handle any file system event"""
#         # Skip directories
#         if event.is_directory:
#             return None
            
#         # Get the file path
#         file_path = event.src_path
        
#         # Skip files in ignored directories
#         if any(ignore_dir in file_path for ignore_dir in self.ignore_dirs):
#             return None
            
#         # Skip files with unsupported extensions
#         if not any(file_path.endswith(ext) for ext in self.supported_extensions):
#             return None
            
#         # Log the event
#         if event.event_type == 'created':
#             logger.info(f"File created: {file_path}")
#             self.changed_files.add(file_path)
#         elif event.event_type == 'modified':
#             logger.info(f"File modified: {file_path}")
#             self.changed_files.add(file_path)
#         elif event.event_type == 'deleted':
#             logger.info(f"File deleted: {file_path}")
#             # We don't track deletions for analysis
#         elif event.event_type == 'moved':
#             logger.info(f"File moved from {file_path} to {event.dest_path}")
#             self.changed_files.add(event.dest_path)
            
#         # Schedule analysis if needed
#         if self.changed_files and not self.analysis_in_progress:
#             asyncio.run_coroutine_threadsafe(
#                 self.trigger_analysis(), 
#                 self.mcp_service.loop
#             )
            
#     async def trigger_analysis(self):
#         """Trigger analysis for changed files"""
#         if self.analysis_in_progress:
#             return
            
#         self.analysis_in_progress = True
#         try:
#             changed_files_copy = self.changed_files.copy()
#             self.changed_files.clear()
            
#             await self.mcp_service.notify_file_changes(changed_files_copy)
#         except Exception as e:
#             logger.error(f"Error triggering analysis: {e}")
#         finally:
#             self.analysis_in_progress = False

# class MCPFileMonitorService:
#     def __init__(self, mcp_config_path):
#         """
#         Initialize file monitor service with MCP client.
        
#         Args:
#             mcp_config_path: Path to the MCP configuration file
#         """
#         self.mcp_config_path = mcp_config_path
#         self.mcp_client = None
#         self.observer = None
#         self.event_handler = None
#         self.loop = None
        
#     async def start_monitoring(self):
#         """Connect, wait for project_path, then start watching."""
#         self.loop = asyncio.get_running_loop()

#         # 1) connect exactly like your Neo4j caller
#         self.client  = MCPClient.from_config_file(self.mcp_config_path)
#         self.session = await self.client.create_session("project-analyzer-server")
#         logger.info(
#             "Connected to Project Analyzer MCP server; tools: %s",
#             [t.name for t in self.session.tools]
#         )

#         # 2) poll get_file_monitor_config until it yields a non-empty project_path
#         project_path = None
#         config = {}
#         while not project_path:
#             result = await self.session.call_tool("get_file_monitor_config", {})
#             raw    = result.content

#             # unwrap a list-of-one if necessary
#             if isinstance(raw, list) and raw and isinstance(raw[0], dict):
#                 config = raw[0]
#             elif isinstance(raw, dict):
#                 config = raw
#             else:
#                 config = {}

#             project_path = config.get("project_path")
#             if not project_path:
#                 logger.info("Waiting on project_path… retry in 2s")
#                 await asyncio.sleep(2)

#         # 3) pull watcher settings
#         exts    = config.get("supported_extensions", [".py", ".js", ".ts"])
#         ignores = config.get("ignore_dirs",         ["node_modules", ".git", "venv"])
#         logger.info("Monitor config loaded; watching %s", project_path)

#         # 4) start watchdog
#         self.event_handler = MCPFileEventHandler(self, exts, ignores)
#         self.observer      = Observer()
#         self.observer.schedule(self.event_handler, project_path, recursive=True)
#         self.observer.start()
#         logger.info("File watcher running on %s", project_path)

#         # 5) keep alive until shutdown
#         try:
#             await self.keep_alive()
#         finally:
#             self.observer.stop()
#             self.observer.join()
#             await self.client.close_session("project-analyzer-server")


#     async def get_config_from_server(self):
#         """Fetch the raw config dict from MCP server."""
#         try:
#             result = await self.session.call_tool("get_file_monitor_config", {})
#             raw    = result.content
#             if isinstance(raw, list) and raw and isinstance(raw[0], dict):
#                 cfg = raw[0]
#             elif isinstance(raw, dict):
#                 cfg = raw
#             else:
#                 cfg = {}
#             logger.info("Monitor config: %s", cfg)
#             return cfg
#         except Exception as e:
#             logger.error("Error getting configuration: %s", e)
#             return {}


#     # async def notify_file_changes(self, changed_files):
#     #     """Send changed_files back to MCP server."""
#     #     try:
#     #         result  = await self.session.call_tool(
#     #             "process_file_changes",
#     #             {"changed_files": list(changed_files)}
#     #         )
#     #         raw     = result.content
#     #         # unwrap similarly
#     #         if isinstance(raw, list) and raw and isinstance(raw[0], dict):
#     #             payload = raw[0]
#     #         elif isinstance(raw, dict):
#     #             payload = raw
#     #         else:
#     #             payload = {}
#     #         logger.info(
#     #             "Notified MCP server of %d changed files: %s",
#     #             len(changed_files), payload
#     #         )
#     #         return payload
#     #     except Exception as e:
#     #         logger.error("Error notifying file changes: %s", e)
#     #         return None

#     async def notify_file_changes(self, changed_files):
#         """Log the list of changed files (no server call)."""
#         if not changed_files:
#             logger.info("No files changed.")
#         else:
#             logger.info("Detected %d changed files:", len(changed_files))
#             for path in changed_files:
#                 logger.info("  • %s", path)
#         # We’re only logging, not calling any MCP tool
#         return None
    
#     async def keep_alive(self):
#         """Keep the service alive"""
#         try:
#             while True:
#                 # This keeps the connection alive
#                 await asyncio.sleep(5)
#         except asyncio.CancelledError:
#             logger.info("Service shutdown requested")
#         except Exception as e:
#             logger.error(f"Error in keep_alive loop: {e}")

# async def run_as_background_service(config_path):
#     """Run the file monitor as a background service connected to MCP"""
#     service = MCPFileMonitorService(config_path)
#     await service.start_monitoring()

# def main():
#     """Main entry point for the file monitor service."""
#     parser = argparse.ArgumentParser(description="MCP File Monitor Service")
#     parser.add_argument("--config", required=True, help="Path to the MCP configuration file")
#     parser.add_argument("--daemon", action="store_true", help="Run as daemon process")
#     args = parser.parse_args()
    
#     # Run as daemon if requested
#     if args.daemon and os.name != 'nt':
#         try:
#             # Fork the process
#             pid = os.fork()
#             if pid > 0:
#                 # Exit the parent process
#                 logger.info(f"Started daemon process with PID {pid}")
#                 exit(0)
#         except OSError as e:
#             logger.error(f"Fork failed: {e}")
#             exit(1)
            
#         # Detach from terminal
#         os.setsid()
#         os.umask(0)
        
#         # Close standard file descriptors
#         sys.stdin.close()
#         sys.stdout.close()
#         sys.stderr.close()
    
#     # Run the service
#     asyncio.run(run_as_background_service(args.config))

# if __name__ == "__main__":
#     main()


# # file_watcher.py
# import asyncio
# import logging
# import argparse
# import os
# import sys
# from pathlib import Path
# from typing import Set, Dict, Any

# # Watchdog imports
# from watchdog.events import FileSystemEventHandler
# from watchdog.observers import Observer

# # MCP client
# from mcp_use import MCPClient

# # Set up logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
# )
# logger = logging.getLogger(__name__)

# class MCPFileEventHandler(FileSystemEventHandler):
#     """File system event handler that notifies MCP server of changes"""
    
#     def __init__(self, mcp_service, supported_extensions=None, ignore_dirs=None):
#         """
#         Initialize the event handler.
        
#         Args:
#             mcp_service: Reference to the MCPFileMonitorService
#             supported_extensions: List of file extensions to monitor
#             ignore_dirs: List of directories to ignore
#         """
#         self.mcp_service = mcp_service
#         self.supported_extensions = supported_extensions or [".py", ".js", ".ts"]
#         self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "venv"]
#         self.changed_files: Set[str] = set()
#         self.analysis_in_progress = False
        
#     def on_any_event(self, event):
#         """Handle any file system event"""
#         # Skip directories
#         if event.is_directory:
#             return None
            
#         # Get the file path
#         file_path = event.src_path
        
#         # Skip files in ignored directories
#         if any(ignore_dir in file_path for ignore_dir in self.ignore_dirs):
#             return None
            
#         # Skip files with unsupported extensions
#         if not any(file_path.endswith(ext) for ext in self.supported_extensions):
#             return None
            
#         # Log the event
#         if event.event_type == 'created':
#             logger.info(f"File created: {file_path}")
#             self.changed_files.add(file_path)
#         elif event.event_type == 'modified':
#             logger.info(f"File modified: {file_path}")
#             self.changed_files.add(file_path)
#         elif event.event_type == 'deleted':
#             logger.info(f"File deleted: {file_path}")
#             # We don't track deletions for analysis
#         elif event.event_type == 'moved':
#             logger.info(f"File moved from {file_path} to {event.dest_path}")
#             self.changed_files.add(event.dest_path)
            
#         # Schedule analysis if needed
#         if self.changed_files and not self.analysis_in_progress:
#             asyncio.run_coroutine_threadsafe(
#                 self.trigger_analysis(),
#                 self.mcp_service.loop
#             )
            
#     async def trigger_analysis(self):
#         """Trigger analysis for changed files"""
#         if self.analysis_in_progress:
#             return
            
#         self.analysis_in_progress = True
#         try:
#             changed_files_copy = list(self.changed_files)
#             self.changed_files.clear()
#             await self.mcp_service.notify_file_changes(changed_files_copy)
#         except Exception as e:
#             logger.error(f"Error triggering analysis: {e}")
#         finally:
#             self.analysis_in_progress = False

# # Update the MCPFileMonitorService class
# class MCPFileMonitorService:
#     """Service that monitors file changes and communicates with MCP server"""
    
#     def __init__(self, config_path):
#         """
#         Initialize file monitor service with MCP client.
        
#         Args:
#             config_path: Path to the MCP configuration file
#         """
#         self.config_path = config_path
#         self.client = None
#         self.session = None
#         self.observer = None
#         self.event_handler = None
#         self.loop = None
        
#     async def start_monitoring(self):
#         """Connect, wait for project_path, then start watching."""
#         self.loop = asyncio.get_running_loop()
        
#         # Connect to MCP server using config file
#         logger.info(f"Connecting to MCP server using config: {self.config_path}")
#         self.client = MCPClient.from_config_file(self.config_path)
#         self.session = await self.client.create_session("project-analyzer-server")
        
#         logger.info(
#             "Connected to Project Analyzer MCP server; tools: %s",
#             [t.name for t in self.session.tools]
#         )
        
#         # Poll get_file_monitor_config until it yields a non-empty project_path
#         project_path = None
#         config = {}
        
#         while not project_path:
#             result = await self.session.call_tool("get_file_monitor_config", {})
#             raw = result.content
            
#             # Unwrap a list-of-one if necessary
#             if isinstance(raw, list) and raw and isinstance(raw[0], dict):
#                 config = raw[0]
#             elif isinstance(raw, dict):
#                 config = raw
#             else:
#                 config = {}
                
#             project_path = config.get("project_path")
            
#             if not project_path:
#                 logger.info("Waiting on project_path... retry in 2s")
#                 await asyncio.sleep(2)
        
#         logger.info("project_path available: %s — closing SSE session", project_path)
#         # Tear down the SSE connection so post_writer can exit cleanly
#         await self.client.close_session("project-analyzer-server")
        
#         # Pull watcher settings
#         exts = config.get("supported_extensions", [".py", ".js", ".ts"])
#         ignores = config.get("ignore_dirs", ["node_modules", ".git", "venv"])
        
#         logger.info("Monitor config loaded; watching %s", project_path)
        
#         # Start watchdog
#         self.event_handler = MCPFileEventHandler(self, exts, ignores)
#         self.observer = Observer()
#         self.observer.schedule(self.event_handler, project_path, recursive=True)
#         self.observer.start()
        
#         logger.info("File watcher running on %s", project_path)
        
#         # Keep alive until shutdown
#         try:
#             await self.keep_alive()
#         finally:
#             self.observer.stop()
#             self.observer.join()
            
#     async def notify_file_changes(self, changed_files):
#         """Send changed_files back to MCP server."""
#         try:
#             result = await self.session.call_tool(
#                 "process_file_changes",
#                 {"changed_files": changed_files}
#             )
            
#             raw = result.content
#             # Unwrap result
#             if isinstance(raw, list) and raw and isinstance(raw[0], dict):
#                 payload = raw[0]
#             elif isinstance(raw, dict):
#                 payload = raw
#             else:
#                 payload = {}
                
#             logger.info(
#                 "Notified MCP server of %d changed files: %s",
#                 len(changed_files), payload
#             )
#             return payload
#         except Exception as e:
#             logger.error(f"Error notifying file changes: {e}")
#             return None
            
#     async def keep_alive(self):
#         """Keep the service alive"""
#         try:
#             while True:
#                 # This keeps the connection alive
#                 await asyncio.sleep(5)
#         except asyncio.CancelledError:
#             logger.info("Service shutdown requested")
#         except Exception as e:
#             logger.error(f"Error in keep_alive loop: {e}")

# # Update the run_service function
# async def run_service(config_path):
#     """Run the file monitor as a service connected to MCP"""
#     service = MCPFileMonitorService(config_path)
#     await service.start_monitoring()

# def main():
#     """Main entry point for the file monitor service."""
#     parser = argparse.ArgumentParser(description="MCP File Monitor Service")
#     parser.add_argument("--config", required=True, 
#                         help="Path to the MCP configuration file")
#     parser.add_argument("--daemon", action="store_true",
#                         help="Run as daemon process")
#     args = parser.parse_args()
    
#     # Run as daemon if requested
#     if args.daemon and os.name != 'nt':
#         try:
#             # Fork the process
#             pid = os.fork()
#             if pid > 0:
#                 # Exit the parent process
#                 logger.info(f"Started daemon process with PID {pid}")
#                 exit(0)
#         except OSError as e:
#             logger.error(f"Fork failed: {e}")
#             exit(1)
            
#         # Detach from terminal
#         os.setsid()
#         os.umask(0)
        
#         # Close standard file descriptors
#         sys.stdin.close()
#         sys.stdout.close()
#         sys.stderr.close()
    
#     # Then modify the main function to use the config file
#     asyncio.run(run_service(args.config))

# if __name__ == "__main__":
#     main()

# # file_watcher.py
# #!/usr/bin/env python3
# import asyncio
# import logging
# import argparse
# import os
# import sys
# import time

# import httpx
# from watchdog.events import FileSystemEventHandler
# from watchdog.observers import Observer

# from mcp_use import MCPClient

# # ——— Logging setup —————————————————————————————————————————————
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# )
# logger = logging.getLogger(__name__)


# class MCPFileEventHandler(FileSystemEventHandler):
#     """Handle file events and notify the MCP server of changes."""
#     def __init__(self, mcp_service, supported_extensions=None, ignore_dirs=None):
#         self.mcp_service = mcp_service
#         self.supported_extensions = supported_extensions or [".py", ".js", ".ts",'.cs','.java']
#         self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "venv"]
#         self.changed_files = set()
#         self.analysis_in_progress = False

#     def on_any_event(self, event):
#         if event.is_directory:
#             return

#         path = event.dest_path if event.event_type == "moved" else event.src_path

#         if any(ig in path for ig in self.ignore_dirs):
#             return
#         if not any(path.endswith(ext) for ext in self.supported_extensions):
#             return

#         logger.info(f"File {event.event_type}: {path}")
#         if event.event_type in ("created", "modified", "moved"):
#             self.changed_files.add(path)

#         if self.changed_files and not self.analysis_in_progress:
#             asyncio.run_coroutine_threadsafe(
#                 self._trigger(),
#                 self.mcp_service.loop
#             )

#     async def _trigger(self):
#         if self.analysis_in_progress:
#             return
#         self.analysis_in_progress = True
#         try:
#             changed = list(self.changed_files)
#             self.changed_files.clear()
#             await self.mcp_service.notify_file_changes(changed)
#         except Exception as e:
#             logger.error("Error notifying MCP of file changes: %s", e)
#         finally:
#             self.analysis_in_progress = False


# class MCPFileMonitorService:
#     """Poll for project_path, then watch files and push changes to MCP."""

#     def __init__(self, config_path: str):
#         self.config_path = config_path
#         self.client = None
#         self.session = None
#         self.observer = None
#         self.loop = None

#     async def start_monitoring(self):
#         self.loop = asyncio.get_running_loop()

#         # 1) Bootstrap via HTTP polling
#         project_path = None
#         while not project_path:
#             logger.info("Polling /project-config for project_path…")
#             try:
#                 # Adjust host if needed; this matches your SSE config
#                 resp = httpx.get("http://host.docker.internal:9000/project-config", timeout=5)
#                 data = resp.json()
#                 project_path = data.get("project_path")
#             except Exception as e:
#                 logger.warning("Failed to fetch project-config: %s", e)

#             if not project_path:
#                 await asyncio.sleep(2)

#         logger.info("Discovered project_path=%r; spinning up file watcher", project_path)

#         # 2) Start Watchdog
#         #    (we don't yet open the MCP SSE session—only after watcher is running)
#         #    You can adjust extensions/ignores if needed.
#         exts = [".py", ".js", ".ts",'.cs','.java']
#         ignores = ["node_modules", ".git", "venv"]
#         handler = MCPFileEventHandler(self, exts, ignores)
#         self.observer = Observer()
#         self.observer.schedule(handler, project_path, recursive=True)
#         self.observer.start()

#         logger.info("File watcher now running on %s", project_path)

#         # 3) Now that the watcher is live, connect to MCP SSE
#         self.client = MCPClient.from_config_file(self.config_path)
#         self.session = await self.client.create_session("project-analyzer-server")
#         logger.info(
#             "Connected SSE to MCP; tools: %s",
#             [t.name for t in self.session.tools]
#         )

#         # 4) Keep the process alive
#         try:
#             while True:
#                 await asyncio.sleep(5)
#         except asyncio.CancelledError:
#             logger.info("Shutdown requested")
#         finally:
#             logger.info("Stopping observer and closing MCP session")
#             self.observer.stop()
#             self.observer.join()
#             await self.client.close_session("project-analyzer-server")

#     async def notify_file_changes(self, changed_files):
#         """Send a process_file_changes call to the MCP server."""
#         try:
#             result = await self.session.call_tool(
#                 "process_file_changes",
#                 {"changed_files": changed_files}
#             )
#             # Unwrap list-of-one TextContent → dict
#             raw = result.content
#             payload = raw[0] if isinstance(raw, list) else raw
#             logger.info("MCP ack: %s", payload)
#         except Exception as e:
#             logger.error("Error in notify_file_changes: %s", e)


# async def run_service(config_path):
#     svc = MCPFileMonitorService(config_path)
#     await svc.start_monitoring()


# def main():
#     p = argparse.ArgumentParser(description="MCP File Monitor Service")
#     p.add_argument("--config", required=True,
#                    help="Path to MCP JSON config file")
#     p.add_argument("--daemon", action="store_true",
#                    help="Daemonize (Unix only)")
#     args = p.parse_args()

#     if args.daemon and os.name != "nt":
#         try:
#             pid = os.fork()
#             if pid > 0:
#                 logger.info("Daemon started; PID %d", pid)
#                 sys.exit(0)
#         except OSError as e:
#             logger.error("Fork failed: %s", e)
#             sys.exit(1)
#         os.setsid()
#         os.umask(0)
#         sys.stdin.close()
#         sys.stdout.close()
#         sys.stderr.close()

#     asyncio.run(run_service(args.config))


# if __name__ == "__main__":
#     main()

#!/usr/bin/env python3
import asyncio
import logging
import argparse
import os
import sys
import hashlib
import yaml
import platform
import redis
from pathlib import Path

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from mcp_use import MCPClient

# ——— Logging setup —————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class ChecksumManager:
    """Manages file checksums to detect true changes in files."""
    
    def __init__(self, project_root, app_name="file_monitor_checksums"):
        """Initialize the checksum manager.
        
        Args:
            project_root: Root directory of the project
            app_name: Name of the application folder to create in system app data
        """
        self.project_root = Path(project_root)
        self.app_name = app_name
        
        # Get appropriate system app data directory
        self.app_data_dir = self._get_app_data_dir()
        
        # Create a unique folder name based on the project path hash
        project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:10]
        self.checksum_dir = self.app_data_dir / f"{project_hash}"
        self.checksum_file = self.checksum_dir / "checksums.yaml"
        
        self.checksums = {}
        self._ensure_checksum_dir()
        self._load_checksums()
    
    def _get_app_data_dir(self):
        """Get the appropriate system directory for storing application data."""
        system = platform.system()
        
        if system == "Windows":
            # Use ProgramData on Windows (accessible to all users)
            app_data = os.environ.get("PROGRAMDATA")
            if not app_data:
                app_data = "C:\\ProgramData"
            return Path(app_data) / self.app_name
            
        elif system == "Darwin":  # macOS
            return Path.home() / "Library" / "Application Support" / self.app_name
            
        else:  # Linux and other Unix-like
            # Use XDG_DATA_HOME or fallback to ~/.local/share
            xdg_data_home = os.environ.get("XDG_DATA_HOME")
            if xdg_data_home:
                return Path(xdg_data_home) / self.app_name
            else:
                return Path.home() / ".local" / "share" / self.app_name
    
    def _ensure_checksum_dir(self):
        """Ensure the checksum directory exists with proper permissions."""
        if not self.checksum_dir.exists():
            try:
                self.checksum_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created checksum directory: {self.checksum_dir}")
            except PermissionError:
                logger.warning(f"Permission denied creating {self.checksum_dir}, falling back to user home")
                # Fallback to user home directory if system directory is not writable
                self.checksum_dir = Path.home() / ".file_monitor_checksums" / hashlib.md5(
                    str(self.project_root).encode()).hexdigest()[:10]
                self.checksum_file = self.checksum_dir / "checksums.yaml"
                self.checksum_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created fallback checksum directory: {self.checksum_dir}")

    
    def _load_checksums(self):
        """Load existing checksums from file."""
        if self.checksum_file.exists():
            try:
                with open(self.checksum_file, 'r') as f:
                    self.checksums = yaml.safe_load(f) or {}
                logger.info(f"Loaded {len(self.checksums)} checksums from {self.checksum_file}")
            except Exception as e:
                logger.error(f"Error loading checksums: {e}")
                self.checksums = {}
        else:
            logger.info("No existing checksum file found, will create new one")
            self.checksums = {}
    
    def _save_checksums(self):
        """Save checksums to file."""
        try:
            with open(self.checksum_file, 'w') as f:
                yaml.dump(self.checksums, f)
            logger.info(f"Saved {len(self.checksums)} checksums to {self.checksum_file}")
        except Exception as e:
            logger.error(f"Error saving checksums: {e}")
    
    def calculate_checksum(self, file_path):
        """Calculate MD5 checksum for a file."""
        try:
            with open(file_path, 'rb') as f:
                file_hash = hashlib.md5()
                while chunk := f.read(8192):
                    file_hash.update(chunk)
            return file_hash.hexdigest()
        except Exception as e:
            logger.error(f"Error calculating checksum for {file_path}: {e}")
            return None
    
    def build_all_checksums(self, ignore_dirs=None):
        """Build checksums for all files in the project."""
        ignore_dirs = ignore_dirs or ["node_modules", ".git", "bin", "obj", str(self.checksum_dir.name)]
        
        logger.info(f"Building checksums for all files in {self.project_root}")
        file_count = 0
        
        for path in self.project_root.glob('**/*'):
            if path.is_file():
                # Skip files in ignored directories
                if any(ig in str(path) for ig in ignore_dirs):
                    continue
                
                rel_path = str(path.relative_to(self.project_root))
                checksum = self.calculate_checksum(path)
                if checksum:
                    self.checksums[rel_path] = checksum
                    file_count = 1
                    
                # Log progress every 100 files
                if file_count % 100 == 0:
                    logger.info(f"Processed {file_count} files...")
        
        logger.info(f"Built checksums for {file_count} files")
        self._save_checksums()
        return file_count
    
    def has_file_changed(self, file_path):
        """Check if a file has truly changed by comparing checksums."""
        abs_path = Path(file_path)
        if not abs_path.exists():
            # File was deleted or doesn't exist
            return False
            
        try:
            # Convert to relative path for storage
            if abs_path.is_absolute():
                rel_path = str(abs_path.relative_to(self.project_root))
            else:
                rel_path = str(abs_path)
                
            old_checksum = self.checksums.get(rel_path)
            new_checksum = self.calculate_checksum(abs_path)
            
            if old_checksum != new_checksum:
                # Update the stored checksum
                self.checksums[rel_path] = new_checksum
                self._save_checksums()
                return True
            return False
        except Exception as e:
            logger.error(f"Error checking if file changed: {e}")
            # If there's an error, assume the file changed to be safe
            return True


class MCPFileEventHandler(FileSystemEventHandler):
    """Handle file events and notify the MCP server of changes with checksum verification."""

    def __init__(self, mcp_service, checksum_manager, ignore_dirs=None, debounce_interval=5):
        self.mcp_service = mcp_service
        self.checksum_manager = checksum_manager
        self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "bin", "obj"]
        self.changed_files = set()
        self._debounce_task = None
        self._debounce_interval = debounce_interval

    def on_any_event(self, event):
        if event.is_directory:
            return

        # pick up src or dest for moved files
        path = event.dest_path if event.event_type == "moved" else event.src_path

        # skip paths under any ignore_dir
        if any(ig in path for ig in self.ignore_dirs):
            return

        logger.info(f"File {event.event_type}: {path}")
        
        # Only track created/modified/moved files that have truly changed
        if event.event_type in ("created", "modified", "moved"):
            # For created files or moved files, we always process them
            if event.event_type in ("created", "moved") or self.checksum_manager.has_file_changed(path):
                logger.info(f"Detected true change in file: {path}")
                self.changed_files.add(path)
            else:
                logger.info(f"File touched but content unchanged: {path}")

        # schedule a debounced notification
        if self.changed_files:
            # cancel the old debounce if it’s still pending
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()

            # schedule a new one
            loop = self.mcp_service.loop
            self._debounce_task = asyncio.run_coroutine_threadsafe(
                self._debounced_trigger(), loop
            )

    async def _debounced_trigger(self):
        try:
            # wait for a quiet period
            await asyncio.sleep(self._debounce_interval)
            await self._trigger()
        except asyncio.CancelledError:
            # a new event came in before timer fired
            pass

    async def _trigger(self):
        # take a snapshot of everything that’s accumulated
        try:
            batch = list(self.changed_files)
            self.changed_files.clear()
            await self.mcp_service.notify_file_changes(batch)
        except Exception as e:
            logger.error("Error notifying MCP of file changes: %s", e)
        finally:
            # if more files arrived while we were sending, re‐schedule immediately
            if self.changed_files:
                await self._trigger()


class MCPFileMonitorService:
    """Poll for project_path, then watch files and push changes to MCP with checksum verification."""

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.client = None
        self.session = None
        self.observer = None
        self.loop = None
        self.checksum_manager = None

    async def start_monitoring(self):
        self.loop = asyncio.get_running_loop()

        # ——— Step 1: read project_path from env, else fall back to HTTP polling —————
        project_path = os.environ.get("PROJECT_ROOT")
        config = {}
        if project_path:
            logger.info("Using PROJECT_ROOT from env: %r", project_path)
        else:
            while not project_path:
                logger.info("PROJECT_ROOT not set, polling /project-config for project_path…")
                try:
                    resp = httpx.get("http://host.docker.internal:9000/project-config", timeout=5)
                    config = resp.json()
                    project_path = config.get("project_path")
                except Exception as e:
                    logger.warning("Failed to fetch project-config: %s", e)

                if not project_path:
                    await asyncio.sleep(2)

        logger.info(f"Discovered project_path={project_path}; initializing checksum manager")
        
        # ——— Step 2: Initialize checksum manager and build initial checksums ————
        ignore_dirs = config.get("ignore_dirs", ["node_modules", ".git", "bin", "obj"])
        self.checksum_manager = ChecksumManager(project_path)
        
        # Build checksums in a separate thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            lambda: self.checksum_manager.build_all_checksums(ignore_dirs)
        )
        
        # ——— Step 3: start watchdog with checksum verification ——————————
        handler = MCPFileEventHandler(self, self.checksum_manager, ignore_dirs)
        self.observer = Observer()
        self.observer.schedule(handler, project_path, recursive=True)
        self.observer.start()
        logger.info(f"File watcher now running on {project_path} with checksum verification")

        # ——— Step 4: connect to MCP SSE ————————————————————————————————
        self.client = MCPClient.from_config_file(self.config_path)
        self.session = await self.client.create_session("project-analyzer-server")
        logger.info(
            "Connected SSE to MCP; tools: %s",
            [t.name for t in self.session.tools]
        )

        # ——— Step 5: keep process alive until interrupted —————————————
        try:
            while True:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("Shutdown requested")
        finally:
            logger.info("Stopping observer and closing MCP session")
            self.observer.stop()
            self.observer.join()
            await self.client.close_session("project-analyzer-server")

    async def notify_file_changes(self, changed_files):
        """Send a process_file_changes call to the MCP server."""
        try:
            result = await self.session.call_tool(
                "process_file_changes",
                {"changed_files": changed_files}
            )
            raw = result.content
            payload = raw[0] if isinstance(raw, list) else raw
            logger.info("MCP ack: %s", payload)
        except Exception as e:
            logger.error("Error in notify_file_changes: %s", e)


async def run_service(config_path):
    svc = MCPFileMonitorService(config_path)
    await svc.start_monitoring()


def main():
    p = argparse.ArgumentParser(description="MCP File Monitor Service with Checksum Verification")
    p.add_argument("--config", required=True,
                   help="Path to MCP JSON config file")
    p.add_argument("--daemon", action="store_true",
                   help="Daemonize (Unix only)")
    args = p.parse_args()

    if args.daemon and os.name != "nt":
        try:
            pid = os.fork()
            if pid > 0:
                logger.info("Daemon started; PID %d", pid)
                sys.exit(0)
        except OSError as e:
            logger.error("Fork failed: %s", e)
            sys.exit(1)
        os.setsid()
        os.umask(0)
        sys.stdin.close()
        sys.stdout.close()
        sys.stderr.close()

    asyncio.run(run_service(args.config))


if __name__ == "__main__":
    main()



# #!/usr/bin/env python3
# import asyncio
# import logging
# import argparse
# import os
# import sys

# import httpx
# from watchdog.events import FileSystemEventHandler
# from watchdog.observers import Observer
# from mcp_use import MCPClient

# # ——— Logging setup —————————————————————————————————————————————
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# )
# logger = logging.getLogger(__name__)


# class MCPFileEventHandler(FileSystemEventHandler):
#     """Handle file events and notify the MCP server of changes (no extension filtering)."""

#     def __init__(self, mcp_service, ignore_dirs=None):
#         self.mcp_service = mcp_service
#         # we no longer filter by extension, only by ignored directories:
#         self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "bin", "obj"]
#         self.changed_files = set()
#         self.analysis_in_progress = False

#     def on_any_event(self, event):
#         if event.is_directory:
#             return

#         # pick up src or dest for moved files
#         path = event.dest_path if event.event_type == "moved" else event.src_path

#         # skip paths under any ignore_dir
#         if any(ig in path for ig in self.ignore_dirs):
#             return

#         logger.info(f"File {event.event_type}: {path}")
#         # track created/modified/moved
#         if event.event_type in ("created", "modified", "moved"):
#             self.changed_files.add(path)

#         # if there are pending changes & we're not already notifying, fire off the coroutine
#         if self.changed_files and not self.analysis_in_progress:
#             asyncio.run_coroutine_threadsafe(self._trigger(), self.mcp_service.loop)

#     async def _trigger(self):
#         if self.analysis_in_progress:
#             return
#         self.analysis_in_progress = True
#         try:
#             changed = list(self.changed_files)
#             self.changed_files.clear()
#             await self.mcp_service.notify_file_changes(changed)
#         except Exception as e:
#             logger.error("Error notifying MCP of file changes: %s", e)
#         finally:
#             self.analysis_in_progress = False


# class MCPFileMonitorService:
#     """Poll for project_path, then watch files and push changes to MCP."""

#     def __init__(self, config_path: str):
#         self.config_path = config_path
#         self.client = None
#         self.session = None
#         self.observer = None
#         self.loop = None

#     async def start_monitoring(self):
#         self.loop = asyncio.get_running_loop()

#         # ——— Step 1: bootstrap via HTTP polling ————————————————————————
#         project_path = None
#         config = {}
#         while not project_path:
#             logger.info("Polling /project-config for project_path…")
#             try:
#                 resp = httpx.get("http://host.docker.internal:9000/project-config", timeout=5)
#                 config = resp.json()
#                 project_path = config.get("project_path")
#             except Exception as e:
#                 logger.warning("Failed to fetch project-config: %s", e)

#             if not project_path:
#                 await asyncio.sleep(2)

#         logger.info("Discovered project_path=%r; spinning up file watcher", project_path)

#         # ——— Step 2: start watchdog (no extension filtering) —————————————
#         ignore_dirs = config.get("ignore_dirs", ["node_modules", ".git", "bin", "obj"])
#         handler = MCPFileEventHandler(self, ignore_dirs)
#         self.observer = Observer()
#         self.observer.schedule(handler, project_path, recursive=True)
#         self.observer.start()
#         logger.info("File watcher now running on %s", project_path)

#         # ——— Step 3: once watching is live, connect to MCP SSE ————————
#         self.client = MCPClient.from_config_file(self.config_path)
#         self.session = await self.client.create_session("project-analyzer-server")
#         logger.info(
#             "Connected SSE to MCP; tools: %s",
#             [t.name for t in self.session.tools]
#         )

#         # ——— Step 4: keep process alive until interrupted —————————————
#         try:
#             while True:
#                 await asyncio.sleep(5)
#         except asyncio.CancelledError:
#             logger.info("Shutdown requested")
#         finally:
#             logger.info("Stopping observer and closing MCP session")
#             self.observer.stop()
#             self.observer.join()
#             await self.client.close_session("project-analyzer-server")

#     async def notify_file_changes(self, changed_files):
#         """Send a process_file_changes call to the MCP server."""
#         try:
#             result = await self.session.call_tool(
#                 "process_file_changes",
#                 {"changed_files": changed_files}
#             )
#             raw = result.content
#             payload = raw[0] if isinstance(raw, list) else raw
#             logger.info("MCP ack: %s", payload)
#         except Exception as e:
#             logger.error("Error in notify_file_changes: %s", e)


# async def run_service(config_path):
#     svc = MCPFileMonitorService(config_path)
#     await svc.start_monitoring()


# def main():
#     p = argparse.ArgumentParser(description="MCP File Monitor Service")
#     p.add_argument("--config", required=True,
#                    help="Path to MCP JSON config file")
#     p.add_argument("--daemon", action="store_true",
#                    help="Daemonize (Unix only)")
#     args = p.parse_args()

#     if args.daemon and os.name != "nt":
#         try:
#             pid = os.fork()
#             if pid > 0:
#                 logger.info("Daemon started; PID %d", pid)
#                 sys.exit(0)
#         except OSError as e:
#             logger.error("Fork failed: %s", e)
#             sys.exit(1)
#         os.setsid()
#         os.umask(0)
#         sys.stdin.close()
#         sys.stdout.close()
#         sys.stderr.close()

#     asyncio.run(run_service(args.config))


# if __name__ == "__main__":
#     main()
