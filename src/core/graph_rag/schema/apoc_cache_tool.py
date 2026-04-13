"""
APOC Cache Tool - Provides incremental access to APOC procedure cache for agents.

This tool allows agents to query the cache incrementally:
1. Get category names
2. Get procedure names in a category
3. Get procedure signature and description

This prevents overwhelming the agent with all procedures at once.
"""

from typing import Dict, Any, List, Optional
from src.core.apoc_procedure_cache import get_apoc_cache


class APOCCacheTool:
    """
    Tool for agents to query APOC procedure cache incrementally.
    """

    def __init__(self, apoc_cache=None):
        self.apoc_cache = apoc_cache or get_apoc_cache()

    def get_all_category_names(self) -> List[str]:
        """
        Get list of all available APOC category names.

        Returns:
            List of category names (e.g., ['apoc.meta', 'apoc.path', ...])
        """
        categories = self.apoc_cache.get_all_categories()
        return sorted(categories.keys())

    def get_category_summary(self) -> Dict[str, int]:
        """
        Get summary of all categories with procedure counts.

        Returns:
            Dict of {category: count}
        """
        return self.apoc_cache.get_all_categories()

    def get_procedures_in_category(self, category: str) -> List[str]:
        """
        Get list of procedure names in a specific category.

        Args:
            category: Category name (e.g., 'apoc.meta')

        Returns:
            List of procedure names in that category
        """
        procedures = self.apoc_cache.get_procedures_by_category(category)
        return [proc['name'] for proc in procedures]

    def get_procedure_signature(self, procedure_name: str) -> Optional[Dict[str, str]]:
        """
        Get signature and description for a specific procedure.

        Args:
            procedure_name: Full procedure name (e.g., 'apoc.meta.schema')

        Returns:
            Dict with name, signature, description, or None if not found
        """
        procedure = self.apoc_cache.get_procedure(procedure_name)
        if not procedure:
            return None

        return {
            'name': procedure['name'],
            'signature': procedure.get('signature', 'N/A'),
            'description': procedure.get('description', 'N/A'),
            'type': procedure.get('type', 'N/A')
        }

    def get_procedures_summary_in_category(self, category: str) -> List[Dict[str, str]]:
        """
        Get list of procedures in category with brief info (name + short description).

        Args:
            category: Category name

        Returns:
            List of dicts with name and description (truncated)
        """
        procedures = self.apoc_cache.get_procedures_by_category(category)
        return [
            {
                'name': proc['name'],
                'description': proc.get('description', 'N/A')[:100] + '...'
            }
            for proc in procedures
        ]

    def search_procedures(self, keyword: str) -> List[str]:
        """
        Search procedures by keyword.

        Args:
            keyword: Search term

        Returns:
            List of matching procedure names
        """
        results = self.apoc_cache.search(keyword)
        return [proc['name'] for proc in results]


def format_category_summary_for_prompt(cache_tool: APOCCacheTool) -> str:
    """
    Format category summary for agent prompt (compact format).

    Returns:
        Formatted string with category names and counts
    """
    categories = cache_tool.get_category_summary()

    lines = ["Available APOC Categories:"]
    for category, count in sorted(categories.items()):
        lines.append(f"  • {category}: {count} procedures")

    return "\n".join(lines)


def format_procedures_for_prompt(cache_tool: APOCCacheTool, category: str) -> str:
    """
    Format procedures in a category for agent prompt.

    Returns:
        Formatted string with procedure names and brief descriptions
    """
    procedures = cache_tool.get_procedures_summary_in_category(category)

    lines = [f"Procedures in {category}:"]
    for proc in procedures:
        lines.append(f"  • {proc['name']}")
        lines.append(f"    {proc['description']}")

    return "\n".join(lines)
