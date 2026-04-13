from .server import run_server as server_main

import asyncio
import argparse
import os

def main():
    """Main entry point for the package."""
    asyncio.run(server_main())

# Optionally expose other important items at package level
__all__ = ["main", "server"]
