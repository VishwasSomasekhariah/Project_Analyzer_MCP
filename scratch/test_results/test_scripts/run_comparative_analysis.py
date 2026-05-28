#!/usr/bin/env python3
"""
Background runner for comparative analysis suite
"""
import asyncio
import logging
import sys
from datetime import datetime

# Configure logging to file
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(f"/opt/genpod/comparative_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

from comparative_analysis_suite import ComparativeAnalyzer

async def main():
    """Run comparative analysis with configurable scenario filter."""
    
    # Get filter from command line args
    test_filter = None
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.isdigit():
            test_filter = int(arg)
        elif arg.startswith('[') and arg.endswith(']'):
            # Parse list format like [T001,T002,F001]
            test_filter = arg[1:-1].split(',')
        else:
            test_filter = arg
    
    logger.info(f"Starting comparative analysis with filter: {test_filter}")
    
    try:
        analyzer = ComparativeAnalyzer(test_scenario_filter=test_filter)
        await analyzer.run_comparative_analysis()
        logger.info("✅ Comparative analysis completed successfully!")
    except Exception as e:
        logger.error(f"❌ Comparative analysis failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())