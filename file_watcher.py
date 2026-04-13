#!/usr/bin/env python3
import asyncio
import logging
import argparse
import os
import sys
import hashlib
import redis
import json
import subprocess
from datetime import datetime
import time

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


class ChecksumRedisManager:
    """Manages file checksums using Redis for high-performance storage and retrieval."""
    
    def __init__(self, project_root, redis_host='localhost', redis_port=6379, redis_db=0):
        """Initialize the Redis checksum manager.
        
        Args:
            project_root: Root directory of the project
            redis_host: Redis server hostname
            redis_port: Redis server port
            redis_db: Redis database number
        """
        self.project_root = Path(project_root)
        
        # Generate a unique project identifier based on path
        self.project_hash = hashlib.md5(str(self.project_root).encode()).hexdigest()[:10]
        self.redis_key = f"checksums:{self.project_hash}"
        
        # Connect to Redis
        self.redis = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
            health_check_interval=30
        )
        
        logger.info(f"Initialized Redis checksum manager for project: {self.project_root}")
        self._check_redis_connection()
    
    def _check_redis_connection(self):
        """Verify Redis connection is working."""
        try:
            self.redis.ping()
            logger.info("Successfully connected to Redis server")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis server: {e}")
            raise
    
    def ensure_connection(self):
        """Ensure Redis connection is alive."""
        try:
            self.redis.ping()
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis connection lost, reconnecting...")
            self._check_redis_connection()
    
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
        """Build checksums for all files in the project and store in Redis."""
        ignore_dirs = ignore_dirs or ["node_modules", ".git", "bin", "obj"]

        logger.info(f"Building extended checksums for all files in {self.project_root}")
        file_count = 0
        commit_id = self.get_git_commit_id()

        with self.redis.pipeline() as pipe:
            for path in self.project_root.glob("**/*"):
                if path.is_file() and not any(ig in str(path) for ig in ignore_dirs):
                    rel_path = str(path.relative_to(self.project_root))
                    checksum = self.calculate_checksum(path)
                    blob = self.get_git_blob_hash(path)

                    if checksum:
                        payload = {
                            "checksum": checksum,
                            "commit": commit_id,
                            "blob": blob,
                            "ts": datetime.utcnow().isoformat()
                        }
                        pipe.hset(self.redis_key, rel_path, json.dumps(payload))
                        file_count += 1

                        if file_count % 1000 == 0:
                            pipe.execute()
                            logger.info(f"Processed {file_count} files...")

            pipe.execute()

        logger.info(f"Built extended checksums for {file_count} files in Redis")
        return file_count

    
    def has_file_changed(self, file_path):
        """Check if a file has truly changed by comparing checksums using atomic operations."""
        abs_path = Path(file_path)
        if not abs_path.exists():
            return False

        try:
            self.ensure_connection()
            rel_path = str(abs_path.relative_to(self.project_root))
            new_checksum = self.calculate_checksum(abs_path)
            if not new_checksum:
                return False

            existing_data = self.redis.hget(self.redis_key, rel_path)
            old_checksum = None
            if existing_data:
                try:
                    old_checksum = json.loads(existing_data).get("checksum")
                except json.JSONDecodeError:
                    old_checksum = existing_data  # fallback for legacy flat checksums

            if old_checksum != new_checksum:
                # Update Redis entry
                payload = {
                    "checksum": new_checksum,
                    "commit": self.get_git_commit_id(),
                    "blob": self.get_git_blob_hash(abs_path),
                    "ts": datetime.utcnow().isoformat()
                }
                self.redis.hset(self.redis_key, rel_path, json.dumps(payload))
                return True

            return False

        except Exception as e:
            logger.error(f"Error checking if file changed: {e}")
            return True
    
    def get_all_checksums(self):
        """Get all checksums from Redis."""
        try:
            self.ensure_connection()
            return self.redis.hgetall(self.redis_key)
        except Exception as e:
            logger.error(f"Error getting checksums from Redis: {e}")
            return {}
    
    def clear_checksums(self):
        """Clear all checksums for this project."""
        try:
            self.ensure_connection()
            self.redis.delete(self.redis_key)
            logger.info(f"Cleared all checksums for project: {self.project_root}")
        except Exception as e:
            logger.error(f"Error clearing checksums: {e}")

    def get_git_commit_id(self):
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.project_root).decode().strip()
        except Exception as e:
            logger.warning(f"Failed to get git commit ID: {e}")
            return "unknown"

    def get_git_blob_hash(self, file_path):
        try:
            return subprocess.check_output(["git", "hash-object", str(file_path)], cwd=self.project_root).decode().strip()
        except Exception as e:
            logger.warning(f"Failed to get git blob hash for {file_path}: {e}")
            return "unknown"

class MCPFileEventHandler(FileSystemEventHandler):
    """Handle file events and notify the MCP server of changes with Redis-based checksum verification and debouncing."""

    def __init__(self, mcp_service, checksum_manager, ignore_dirs=None, debounce_interval=2, max_events_per_minute=1000):
        self.mcp_service = mcp_service
        self.checksum_manager = checksum_manager
        self.ignore_dirs = ignore_dirs or ["node_modules", ".git", "bin", "obj"]
        self.changed_files = set()
        self._debounce_task = None
        self._debounce_interval = debounce_interval
        self._processing_lock = asyncio.Lock()
        
        # Rate limiting to handle heavy file activity gracefully
        self.event_count = 0
        self.last_event_window = time.time()
        self.max_events_per_window = max_events_per_minute
        self.event_window_duration = 60
        self.rate_limited = False
        
        logger.info(f"Initialized file event handler with {debounce_interval}s debounce interval and rate limiting ({max_events_per_minute} events/min max)")

    def on_any_event(self, event):
        if event.is_directory:
            return

        # Rate limiting check
        current_time = time.time()
        if current_time - self.last_event_window > self.event_window_duration:
            # Reset window
            self.last_event_window = current_time
            self.event_count = 0
            if self.rate_limited:
                logger.info("Rate limiting window reset, resuming normal processing")
                self.rate_limited = False
        
        self.event_count += 1
        
        if self.event_count > self.max_events_per_window:
            if not self.rate_limited:
                logger.warning(f"Rate limit exceeded ({self.max_events_per_window} events/{self.event_window_duration}s), "
                             f"entering rate-limited mode")
                self.rate_limited = True
            # In rate-limited mode, only log every 100th event to avoid spam
            if self.event_count % 100 == 0:
                logger.debug(f"Rate limited: processed {self.event_count} events in current window")
            return

        # Pick up src or dest for moved files
        path = event.dest_path if event.event_type == "moved" else event.src_path

        # Skip paths under any ignore_dir
        if any(ig in path for ig in self.ignore_dirs):
            return

        # In normal mode, log file events, but reduce verbosity during heavy activity
        if self.event_count <= 50 or self.event_count % 20 == 0:
            logger.info(f"File {event.event_type}: {path}")
        elif self.event_count == 51:
            logger.info(f"Heavy file activity detected, reducing log verbosity...")
        
        # Only track created/modified/moved files that have truly changed
        if event.event_type in ("created", "modified", "moved"):
            try:
                # For created files or moved files, we always process them
                if event.event_type in ("created", "moved") or self.checksum_manager.has_file_changed(path):
                    if self.event_count <= 50 or self.event_count % 20 == 0:
                        logger.info(f"Detected true change in file: {path}")
                    self.changed_files.add(path)
                    
                    # Schedule debounced notification
                    self._schedule_debounced_notification()
                else:
                    if self.event_count <= 10:  # Only log first few "no change" events
                        logger.info(f"File touched but content unchanged: {path}")
            except Exception as e:
                logger.error(f"Error processing file event for {path}: {e}")
                # Add to changed files anyway to be safe
                self.changed_files.add(path)
                self._schedule_debounced_notification()

    def _schedule_debounced_notification(self):
        """Schedule a debounced notification, canceling any existing one."""
        # Cancel the existing debounce task if it's still pending
        if self._debounce_task and not self._debounce_task.done():
            logger.debug("Canceling previous debounce task")
            self._debounce_task.cancel()

        # Schedule a new debounced notification
        if self.mcp_service.loop:
            self._debounce_task = asyncio.run_coroutine_threadsafe(
                self._debounced_trigger(), self.mcp_service.loop
            )
        else:
            logger.warning("MCP service loop not available for debounced notification")

    async def _debounced_trigger(self):
        """Wait for the debounce interval, then trigger notification if no new events arrive."""
        try:
            logger.debug(f"Starting debounce timer for {self._debounce_interval}s")
            await asyncio.sleep(self._debounce_interval)
            
            # Use lock to prevent race conditions during processing
            async with self._processing_lock:
                if self.changed_files:
                    logger.info(f"Debounce period elapsed, processing {len(self.changed_files)} changed files")
                    await self._trigger()
                else:
                    logger.debug("No files to process after debounce period")
                    
        except asyncio.CancelledError:
            logger.debug("Debounce task was cancelled due to new file events")
            # This is expected when new events come in before the timer expires
            pass
        except Exception as e:
            logger.error(f"Error in debounced trigger: {e}")

    async def _trigger(self):
        """Process accumulated file changes and notify MCP server."""
        try:
            # Take a snapshot of all accumulated changes
            batch = list(self.changed_files)
            self.changed_files.clear()
            
            if batch:
                logger.info(f"Notifying MCP server of {len(batch)} file changes: {batch}")
                await self.mcp_service.notify_file_changes(batch)
            
        except Exception as e:
            logger.error("Error notifying MCP of file changes: %s", e)
        finally:
            # Check if more files were added while we were processing
            if self.changed_files:
                logger.info("New file changes detected during processing, scheduling another notification")
                self._schedule_debounced_notification()


class MCPConnectionManager:
    """Manages resilient MCP connections with retry logic and circuit breaker pattern."""
    
    def __init__(self, config_path: str, max_retries=5, base_delay=1.0, max_delay=60.0):
        self.config_path = config_path
        self.client = None
        self.session = None
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.connection_failures = 0
        self.last_failure_time = 0
        self.circuit_open = False
        self.circuit_breaker_timeout = 300  # 5 minutes
        
    async def ensure_connection(self):
        """Ensure MCP connection is established with circuit breaker and retry logic."""
        if self.circuit_open:
            if time.time() - self.last_failure_time > self.circuit_breaker_timeout:
                logger.info("Circuit breaker timeout expired, attempting to reconnect")
                self.circuit_open = False
                self.connection_failures = 0
            else:
                logger.debug("Circuit breaker is open, skipping connection attempt")
                return False
                
        if self.session is None:
            return await self._establish_connection()
        
        # Test existing connection
        try:
            # Simple health check by listing tools
            tools = self.session.tools
            logger.debug(f"MCP connection healthy, {len(tools)} tools available")
            return True
        except Exception as e:
            logger.warning(f"MCP connection test failed: {e}")
            await self._cleanup_connection()
            return await self._establish_connection()
    
    async def _establish_connection(self):
        """Establish MCP connection with exponential backoff retry."""
        for attempt in range(self.max_retries):
            try:
                logger.info(f"Attempting MCP connection (attempt {attempt + 1}/{self.max_retries})")
                
                self.client = MCPClient.from_config_file(self.config_path)
                self.session = await self.client.create_session("mcp-analysis-server")
                
                logger.info(f"✓ MCP connection established, tools: {[t.name for t in self.session.tools]}")
                self.connection_failures = 0
                self.circuit_open = False
                return True
                
            except Exception as e:
                self.connection_failures += 1
                self.last_failure_time = time.time()
                
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"MCP connection attempt {attempt + 1} failed: {e}")
                
                if attempt < self.max_retries - 1:
                    logger.info(f"Retrying in {delay:.1f} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {self.max_retries} connection attempts failed, opening circuit breaker")
                    self.circuit_open = True
                    
        return False
    
    async def _cleanup_connection(self):
        """Clean up existing MCP connection."""
        try:
            if self.session and self.client:
                await self.client.close_session("mcp-analysis-server")
        except Exception as e:
            logger.debug(f"Error during connection cleanup: {e}")
        finally:
            self.session = None
            self.client = None
    
    async def call_tool_resilient(self, tool_name: str, arguments: dict, timeout=30):
        """Call MCP tool with resilient error handling."""
        if not await self.ensure_connection():
            logger.warning(f"Cannot call tool {tool_name}: MCP connection unavailable")
            return None
            
        try:
            # Add timeout to prevent hanging calls
            result = await asyncio.wait_for(
                self.session.call_tool(tool_name, arguments),
                timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            logger.error(f"Tool call {tool_name} timed out after {timeout}s")
            return None
        except Exception as e:
            logger.error(f"Tool call {tool_name} failed: {e}")
            # Mark connection as potentially bad
            await self._cleanup_connection()
            return None
    
    async def shutdown(self):
        """Gracefully shutdown MCP connection."""
        await self._cleanup_connection()


class MCPFileMonitorService:
    """Poll for project_path, then watch files and push changes to MCP with Redis-based checksum verification."""

    def __init__(self, config_path: str, redis_host='localhost', redis_port=6379, redis_db=0, debounce_interval=2, max_events_per_minute=1000):
        self.config_path = config_path
        self.mcp_manager = MCPConnectionManager(config_path)
        self.observer = None
        self.loop = None
        self.checksum_manager = None
        self.debounce_interval = debounce_interval
        self.max_events_per_minute = max_events_per_minute
        self.redis_config = {
            'host': redis_host,
            'port': redis_port,
            'db': redis_db
        }
        self.pending_notifications = []
        self.max_pending_notifications = 100  # Prevent memory overflow

    async def start_monitoring(self):
        self.loop = asyncio.get_running_loop()

        # ——— Step 1: Read project_path from env, else fall back to HTTP polling ————
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

        logger.info(f"Discovered project_path={project_path}; initializing Redis checksum manager")
        
        # ——— Step 2: Initialize Redis checksum manager and build initial checksums ————
        ignore_dirs = config.get("ignore_dirs", ["node_modules", ".git", "bin", "obj"])
        self.checksum_manager = ChecksumRedisManager(
            project_path,
            redis_host=self.redis_config['host'],
            redis_port=self.redis_config['port'],
            redis_db=self.redis_config['db']
        )
        
        # Build checksums in a separate thread to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, 
            lambda: self.checksum_manager.build_all_checksums(ignore_dirs)
        )
        
        # ——— Step 3: Start watchdog with Redis-based checksum verification and debouncing ——————————
        handler = MCPFileEventHandler(
            self, 
            self.checksum_manager, 
            ignore_dirs, 
            debounce_interval=self.debounce_interval,
            max_events_per_minute=self.max_events_per_minute
        )
        self.observer = Observer()
        self.observer.schedule(handler, project_path, recursive=True)
        self.observer.start()
        logger.info(f"File watcher now running on {project_path} with Redis-based checksum verification and {self.debounce_interval}s debounce")

        # ——— Step 4: Attempt initial MCP connection (non-blocking) ————————————————————————————————
        logger.info("Attempting initial MCP connection...")
        connection_established = await self.mcp_manager.ensure_connection()
        
        if connection_established:
            logger.info("✓ Initial MCP connection successful")
        else:
            logger.warning("⚠ Initial MCP connection failed, will retry in background")
            logger.info("File watcher will continue monitoring and queue notifications")

        # ——— Step 5: Start background connection monitor and notification processor —————————————
        asyncio.create_task(self._connection_monitor())
        asyncio.create_task(self._notification_processor())

        # ——— Step 6: Keep process alive until interrupted —————————————
        try:
            while True:
                await asyncio.sleep(5)
                # Log status periodically
                if len(self.pending_notifications) > 0:
                    logger.info(f"File watcher status: {len(self.pending_notifications)} pending notifications, "
                              f"circuit_open={self.mcp_manager.circuit_open}")
        except asyncio.CancelledError:
            logger.info("Shutdown requested")
        finally:
            logger.info("Stopping observer and closing MCP session")
            self.observer.stop()
            self.observer.join()
            await self.mcp_manager.shutdown()

    async def notify_file_changes(self, changed_files):
        """Queue file changes for resilient notification to MCP server."""
        if len(self.pending_notifications) >= self.max_pending_notifications:
            logger.warning(f"Notification queue full ({self.max_pending_notifications}), dropping oldest notifications")
            # Remove oldest notifications to make room
            self.pending_notifications = self.pending_notifications[-(self.max_pending_notifications//2):]
            
        # Add to queue with timestamp
        notification = {
            "files": changed_files,
            "timestamp": time.time(),
            "attempts": 0
        }
        self.pending_notifications.append(notification)
        logger.info(f"Queued notification for {len(changed_files)} files, queue size: {len(self.pending_notifications)}")
        
    async def _connection_monitor(self):
        """Background task to monitor and maintain MCP connection."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                if self.mcp_manager.circuit_open:
                    logger.debug("Connection monitor: Circuit breaker is open")
                else:
                    await self.mcp_manager.ensure_connection()
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                await asyncio.sleep(10)  # Shorter retry on error
                
    async def _notification_processor(self):
        """Background task to process queued notifications."""
        while True:
            try:
                if not self.pending_notifications:
                    await asyncio.sleep(5)  # Check every 5 seconds when idle
                    continue
                    
                # Process the oldest notification
                notification = self.pending_notifications[0]
                notification["attempts"] += 1
                
                # Try to send the notification
                result = await self.mcp_manager.call_tool_resilient(
                    "process_file_changes",
                    {"changed_files": notification["files"]},
                    timeout=15  # Shorter timeout for file change notifications
                )
                
                if result is not None:
                    # Success - remove from queue
                    self.pending_notifications.pop(0)
                    raw = result.content
                    payload = raw[0] if isinstance(raw, list) else raw
                    logger.info(f"✓ Notification sent successfully: {payload}")
                else:
                    # Failed - check if we should retry or drop
                    max_attempts = 3
                    age_hours = (time.time() - notification["timestamp"]) / 3600
                    
                    if notification["attempts"] >= max_attempts or age_hours > 1:
                        # Drop old or repeatedly failed notifications
                        self.pending_notifications.pop(0)
                        logger.warning(f"Dropping notification after {notification['attempts']} attempts "
                                     f"(age: {age_hours:.1f}h): {len(notification['files'])} files")
                    else:
                        # Retry later
                        logger.info(f"Notification failed, will retry (attempt {notification['attempts']}/{max_attempts})")
                        await asyncio.sleep(10)  # Wait before retrying
                        
            except Exception as e:
                logger.error(f"Error in notification processor: {e}")
                await asyncio.sleep(5)


async def run_service(config_path, redis_host, redis_port, redis_db, debounce_interval, max_events_per_minute=1000):
    svc = MCPFileMonitorService(
        config_path,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        debounce_interval=debounce_interval,
        max_events_per_minute=max_events_per_minute
    )
    await svc.start_monitoring()


def main():
    p = argparse.ArgumentParser(description="MCP File Monitor Service with Redis Checksum Verification, Debouncing, and Resilient MCP Connections")
    p.add_argument("--config", required=True,
                   help="Path to MCP JSON config file")
    p.add_argument("--redis-host", default="localhost",
                   help="Redis server hostname (default: localhost)")
    p.add_argument("--redis-port", type=int, default=6379,
                   help="Redis server port (default: 6379)")
    p.add_argument("--redis-db", type=int, default=0,
                   help="Redis database number (default: 0)")
    p.add_argument("--debounce-interval", type=float, default=2.0,
                   help="Debounce interval in seconds (default: 2.0)")
    p.add_argument("--max-events-per-minute", type=int, default=1000,
                   help="Maximum file events per minute before rate limiting (default: 1000)")
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

    asyncio.run(run_service(
        args.config,
        args.redis_host,
        args.redis_port,
        args.redis_db,
        args.debounce_interval,
        args.max_events_per_minute
    ))


if __name__ == "__main__":
    main()
