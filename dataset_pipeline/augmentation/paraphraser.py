"""
LLM query paraphraser. Generates N paraphrases per validated query.
Applies a semantic similarity gate to prevent semantic drift.
"""

from __future__ import annotations

import json
import logging
from typing import List

from dataset_pipeline.models import AugmentedQuery

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a query paraphrasing assistant for a code analysis benchmark.
Output ONLY valid JSON — no markdown, no explanation."""

_USER = """\
Original query about HelloWorldApp C# codebase: {query}

Generate {n} diverse paraphrases. Each must:
1. Preserve the exact same information need
2. Use a different phrasing, tone, or vocabulary
3. Remain a question or request that a developer could naturally ask

Types to produce: "rephrase", "formal_tone", "conversational_tone"

Output JSON: [{{"type": "...", "query": "..."}}]"""


def _similarity(a: str, b: str) -> float:
    """Simple lexical overlap as similarity proxy (avoids embedding model dependency)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    return len(intersection) / max(len(words_a), len(words_b))


async def paraphrase_query(
    parent_query_id: str,
    query: str,
    llm_service,
    n: int = 3,
    similarity_threshold: float = 0.75,
    id_prefix: str = "aug",
) -> List[AugmentedQuery]:
    prompt = _USER.format(query=query, n=n)
    try:
        resp = await llm_service.generate_response(
            prompt=prompt,
            system_prompt=_SYSTEM,
            json_mode=True,
            temperature=0.8,
            max_tokens=1000,
            use_cache=False,
        )
        if resp.error:
            logger.warning(f"Paraphrase error for {parent_query_id}: {resp.error}")
            return []
        raw = json.loads(resp.content)
        if not isinstance(raw, list):
            return []
    except Exception as e:
        logger.warning(f"Paraphrase failed for {parent_query_id}: {e}")
        return []

    results: List[AugmentedQuery] = []
    for i, item in enumerate(raw[:n]):
        paraphrase = item.get("query", "").strip()
        atype = item.get("type", "rephrase")
        if not paraphrase or len(paraphrase) < 15:
            continue
        # Semantic drift check — reject if too similar (near-duplicate) or too dissimilar
        sim = _similarity(query, paraphrase)
        if sim > 0.95:
            logger.debug(f"Skipping near-duplicate paraphrase for {parent_query_id}")
            continue
        if sim < similarity_threshold * 0.5:  # allow some slack on lexical overlap
            logger.debug(f"Paraphrase too dissimilar for {parent_query_id}: sim={sim:.2f}")
            continue
        aug_id = f"{id_prefix}_{parent_query_id}_aug{i+1}"
        results.append(AugmentedQuery(
            query_id=aug_id,
            parent_query_id=parent_query_id,
            query=paraphrase,
            augmentation_type=atype if atype in ("rephrase", "formal_tone", "conversational_tone") else "rephrase",
            augment_index=i + 1,
        ))

    return results
