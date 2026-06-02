"""
Logging configuration for the Adaptive CPG Workflow MCP Server.

Provides rotating file handlers with automatic cleanup and memory-efficient buffering.
Logs are written to the package installation directory under logs/.
"""
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional


class WorkflowLogger:
    """
    Logger with file rotation and memory management.

    Logs are written to:
    - {log_dir}/server.log - Server operations (INFO and above)
    - {log_dir}/workflow.log - General workflow logs (INFO and above)
    - {log_dir}/workflow_error.log - Error logs only (ERROR and above)
    - {log_dir}/workflow_debug.log - Debug logs (DEBUG and above) - optional
    """

    def __init__(
        self,
        name: str = "mcp_analysis_server",
        log_dir: Optional[Path] = None,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB per file
        backup_count: int = 5,  # Keep 5 old log files
        console_level: int = logging.INFO,
        file_level: int = logging.DEBUG,
        enable_debug_file: bool = False
    ):
        """
        Initialize logging infrastructure.

        Args:
            name: Logger name
            log_dir: Directory for log files (defaults to package installation dir)
            max_bytes: Maximum size of each log file before rotation
            backup_count: Number of backup log files to keep
            console_level: Minimum level for console output
            file_level: Minimum level for file output
            enable_debug_file: Whether to create separate debug log file
        """
        self.name = name
        self.logger = logging.getLogger(name)

        # Prevent duplicate handlers if logger already configured
        if self.logger.handlers:
            return

        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        # Determine log directory - use package installation directory
        if log_dir is None:
            package_root = Path(__file__).parent.parent.parent
            log_dir = package_root / "logs"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Touch log files so they exist on disk immediately (before first write).
        for fname in ("server.log", "workflow.log", "workflow_error.log"):
            (self.log_dir / fname).touch(exist_ok=True)

        # Formatters
        detailed_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        simple_formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(simple_formatter)
        self.logger.addHandler(console_handler)

        # Server operations log (for server.py, HTTP requests, MCP connections)
        server_log_file = self.log_dir / "server.log"
        server_handler = logging.handlers.RotatingFileHandler(
            filename=server_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        server_handler.setLevel(logging.INFO)
        server_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(server_handler)

        # Workflow file handler with rotation (workflow execution details)
        workflow_log_file = self.log_dir / "workflow.log"
        workflow_handler = logging.handlers.RotatingFileHandler(
            filename=workflow_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        workflow_handler.setLevel(file_level)
        workflow_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(workflow_handler)

        # Error file handler (errors only)
        error_log_file = self.log_dir / "workflow_error.log"
        error_handler = logging.handlers.RotatingFileHandler(
            filename=error_log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(error_handler)

        # Optional debug file handler
        if enable_debug_file:
            debug_log_file = self.log_dir / "workflow_debug.log"
            debug_handler = logging.handlers.RotatingFileHandler(
                filename=debug_log_file,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            debug_handler.setLevel(logging.DEBUG)
            debug_handler.setFormatter(detailed_formatter)
            self.logger.addHandler(debug_handler)

        # ============================================================================
        # Configure ALL src.* package loggers to use the same handlers
        # ============================================================================
        # This ensures ALL logs from ALL components go to the log files
        src_logger = logging.getLogger("src")
        src_logger.setLevel(logging.DEBUG)
        src_logger.propagate = False  # Don't propagate to root to avoid duplicate console output

        # Add the same file handlers to src.* loggers
        src_logger.addHandler(server_handler)
        src_logger.addHandler(workflow_handler)
        src_logger.addHandler(error_handler)
        if enable_debug_file:
            src_logger.addHandler(debug_handler)

        # Add console handler for src.* loggers
        src_console = logging.StreamHandler()
        src_console.setLevel(console_level)
        src_console.setFormatter(simple_formatter)
        src_logger.addHandler(src_console)

        self.logger.info(f"="*80)
        self.logger.info(f"Production logging initialized")
        self.logger.info(f"Log directory: {self.log_dir}")
        self.logger.info(f"  - server.log: Server operations")
        self.logger.info(f"  - workflow.log: Workflow execution")
        self.logger.info(f"  - workflow_error.log: Errors only")
        if enable_debug_file:
            self.logger.info(f"  - workflow_debug.log: Debug details")
        self.logger.info(f"Rotation policy: {max_bytes / (1024*1024):.1f}MB per file, {backup_count} backups")
        self.logger.info(f"="*80)

    def get_logger(self) -> logging.Logger:
        """Get the configured logger instance."""
        return self.logger

    def cleanup_old_logs(self, days_to_keep: int = 7):
        """
        Remove log files older than specified days.

        Args:
            days_to_keep: Delete log files older than this many days
        """
        import time

        cutoff_time = time.time() - (days_to_keep * 86400)
        deleted_count = 0

        for log_file in self.log_dir.glob("*.log*"):
            try:
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    deleted_count += 1
                    self.logger.debug(f"Deleted old log file: {log_file.name}")
            except Exception as e:
                self.logger.warning(f"Failed to delete old log {log_file.name}: {e}")

        if deleted_count > 0:
            self.logger.info(f"Cleaned up {deleted_count} old log files (older than {days_to_keep} days)")


# Global logger instance
_global_logger: Optional[WorkflowLogger] = None


def setup_logging(
    log_dir: Optional[Path] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    enable_debug_file: bool = False
) -> logging.Logger:
    """
    Set up logging infrastructure (call once at application startup).

    Args:
        log_dir: Directory for log files
        max_bytes: Maximum size per log file before rotation (default: 10MB)
        backup_count: Number of backup files to keep (default: 5)
        console_level: Console output level (default: INFO)
        file_level: File output level (default: DEBUG)
        enable_debug_file: Create separate debug log file (default: False)

    Returns:
        Configured logger instance
    """
    global _global_logger

    if _global_logger is None:
        _global_logger = WorkflowLogger(
            log_dir=log_dir,
            max_bytes=max_bytes,
            backup_count=backup_count,
            console_level=console_level,
            file_level=file_level,
            enable_debug_file=enable_debug_file
        )

    return _global_logger.get_logger()


def get_logger() -> logging.Logger:
    """
    Get the configured logger instance.
    Initializes with default settings if not already configured.
    """
    global _global_logger

    if _global_logger is None:
        return setup_logging()

    return _global_logger.get_logger()


def cleanup_old_logs(days_to_keep: int = 7):
    """
    Remove log files older than specified days.

    Args:
        days_to_keep: Delete log files older than this many days
    """
    global _global_logger

    if _global_logger is not None:
        _global_logger.cleanup_old_logs(days_to_keep)
