"""
LLM-based sufficiency check: given a query and collected evidence, decides
whether the retrieved information is sufficient to answer accurately.
"""

from __future__ import annotations

import json
import logging
from typing import List

from dataset_pipeline.models import CitationRecord, HopRecord, PlanExecutionTrace

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a precise evidence evaluator for a code retrieval system.
Given a user question and retrieved evidence, determine whether the evidence is sufficient to answer accurately.
Output ONLY valid JSON — no markdown, no explanation."""

_USER = """\
Question: {query}

Retrieved evidence:
{evidence_text}

Is there enough information in the retrieved evidence to answer the question accurately?

Output JSON: {{"verdict": "sufficient" | "insufficient", "reasoning": "<one sentence>"}}"""


def _format_evidence(hops: List[HopRecord], citations: List[CitationRecord]) -> str:
    parts = []
    for hop in hops:
        parts.append(f"[Hop {hop.hop_number} — {hop.agent}]: {hop.raw_result_summary}")
    if citations:
        parts.append("\nCitations:")
        for c in citations[:10]:
            parts.append(f"  - {c.entity_name} in {c.file_path}: {c.evidence_text[:150]}")
    return "\n".join(parts) or "(no evidence retrieved)"


async def check_sufficiency(
    query: str,
    trace: PlanExecutionTrace,
    llm_service,
) -> PlanExecutionTrace:
    if trace.status == "error" or not trace.hops:
        trace.sufficiency_verdict = "insufficient"
        trace.sufficiency_reasoning = "execution failed or no hops"
        return trace

    evidence_text = _format_evidence(trace.hops, trace.citations)
    prompt = _USER.format(query=query, evidence_text=evidence_text)

    try:
        resp = await llm_service.generate_response(
            prompt=prompt,
            system_prompt=_SYSTEM,
            json_mode=True,
            temperature=0.0,
            max_tokens=300,
            use_cache=False,
        )
        if resp.error:
            logger.warning(f"Sufficiency check error for {trace.trace_id}: {resp.error}")
            trace.sufficiency_verdict = "insufficient"
            trace.sufficiency_reasoning = "LLM error"
            return trace
        result = json.loads(resp.content)
        trace.sufficiency_verdict = result.get("verdict", "insufficient")
        trace.sufficiency_reasoning = result.get("reasoning", "")
    except Exception as e:
        logger.warning(f"Sufficiency check failed for {trace.trace_id}: {e}")
        trace.sufficiency_verdict = "insufficient"
        trace.sufficiency_reasoning = str(e)

    return trace
