"""
Retry utilities for the Graph RAG Multi-Agent system.

Provides decorators for retry with exponential backoff on API calls.
"""

import asyncio
import logging
from functools import wraps
from typing import Callable, TypeVar

from openai import APIConnectionError, APIError, RateLimitError

from src.core.graph_rag.core.exceptions import AgentExecutionError

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable)


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for retry with exponential backoff.

    Retries on RateLimitError and APIConnectionError.
    Raises AgentExecutionError on APIError or max retries exceeded.

    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (will be exponentially increased)
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (RateLimitError, APIConnectionError) as e:
                    last_exception = e
                    delay = base_delay * (2 ** attempt)
                    logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                except APIError as e:
                    logger.error(f"API error (not retrying): {e}")
                    raise AgentExecutionError(f"API error: {e}") from e
            raise AgentExecutionError(f"Max retries exceeded: {last_exception}") from last_exception
        return wrapper
    return decorator


__all__ = ['retry_with_backoff']
