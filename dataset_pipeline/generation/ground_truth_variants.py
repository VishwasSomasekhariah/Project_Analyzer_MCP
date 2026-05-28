"""
Generates diverse query variants from ground truth scenarios using LLM.
Produces up to gt_variants_per_query variants per GT entry.
"""

from __future__ import annotations

import json
import logging
from typing import List

from dataset_pipeline.models import RawQuery
from dataset_pipeline.utils.io import load_json

logger = logging.getLogger(__name__)

_VARIANT_ANGLES = [
    "rephrase",
    "specificity_increase",
    "specificity_decrease",
    "role_shifted",
    "negative_form",
    "follow_up",
    "constraint_added",
]

_SYSTEM_PROMPT = """\
You are a query diversity generator for a code analysis benchmark.
Given an original question about the HelloWorldApp C# codebase, produce diverse variants.
Each variant must preserve the exact same information need but use a different phrasing, angle, or framing.
Output ONLY valid JSON — a list of objects with fields: angle, query.
Do not include any markdown, explanation, or extra text."""

_USER_PROMPT = """\
Original query: {original_query}
Ground truth answer summary: {gt_summary}

Generate variants for these angles: {angles}

Rules:
- "rephrase": different surface form, same meaning
- "specificity_increase": add more specifics (exact method names, file names)
- "specificity_decrease": broaden the question
- "role_shifted": frame as a new developer asking about this code
- "negative_form": ask what something does NOT do
- "follow_up": a natural follow-up question building on the answer
- "constraint_added": add a constraint like "without looking at X file"

Output JSON array: [{{"angle": "...", "query": "..."}}]"""


async def generate_gt_variants(
    gt_path: str,
    llm_service,
    variants_per_query: int = 7,
    id_prefix: str = "gt",
) -> List[RawQuery]:
    gt_list = load_json(gt_path)
    results: List[RawQuery] = []
    angles = _VARIANT_ANGLES[:variants_per_query]

    for entry in gt_list:
        qid = entry["query_id"]
        original = entry["user_query"]
        gt_summary = entry["ground_truth_response"][:400]
        expected_files = entry.get("source_files_used", [])

        # Derive query_type from scenario_type
        scenario_map = {
            "analysis": "behavioral",
            "factual": "factual",
            "modification": "modification",
        }
        qtype = scenario_map.get(entry.get("scenario_type", "factual"), "factual")
        difficulty = "medium"

        prompt = _USER_PROMPT.format(
            original_query=original,
            gt_summary=gt_summary,
            angles=", ".join(angles),
        )

        try:
            resp = await llm_service.generate_response(
                prompt=prompt,
                system_prompt=_SYSTEM_PROMPT,
                json_mode=True,
                temperature=0.7,
                max_tokens=1500,
            )
            if resp.error:
                logger.warning(f"LLM error for {qid}: {resp.error}")
                continue
            variants = json.loads(resp.content)
            if not isinstance(variants, list):
                logger.warning(f"Unexpected LLM output for {qid}")
                continue
        except Exception as e:
            logger.warning(f"Variant generation failed for {qid}: {e}")
            continue

        for i, v in enumerate(variants[:variants_per_query]):
            angle = v.get("angle", angles[i] if i < len(angles) else "rephrase")
            query_text = v.get("query", "").strip()
            if not query_text or len(query_text) < 15:
                continue

            diff = "hard" if angle in ("constraint_added", "follow_up") else difficulty

            results.append(RawQuery(
                query_id=f"{id_prefix}_{qid}_v{i + 1}",
                query=query_text,
                source="ground_truth_variant",
                base_query_id=qid,
                query_type=qtype,
                difficulty=diff,
                expected_files=expected_files,
                metadata={"angle": angle, "original_query": original},
            ))

        logger.info(f"Generated {len(variants[:variants_per_query])} variants for {qid}")

    logger.info(f"GT variant generation complete: {len(results)} queries from {len(gt_list)} base entries")
    return results
