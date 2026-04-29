"""
Shared utilities for the Hybrid Fast Workflow.
"""
import json
import re


def parse_llm_json(text: str) -> dict:
    """
    Robustly extract the first JSON object from an LLM response.
    Handles trailing content, markdown fences, and extra whitespace
    that LLMs sometimes add even in json_mode.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    obj, _ = json.JSONDecoder().raw_decode(text.strip())
    return obj
