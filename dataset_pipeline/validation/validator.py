"""
Validates execution traces against raw queries.
Keeps both successful (is_valid=True) and failed (is_valid=False) traces —
both are training signal for RL.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from dataset_pipeline.models import ValidatedPlanResult

logger = logging.getLogger(__name__)


def validate_trace(
    trace: dict,
    raw_query: dict,
    min_citation_coverage: float = 0.3,
    min_answer_length: int = 50,
) -> ValidatedPlanResult:
    trace_id = trace.get("trace_id", "")
    query_id = trace.get("query_id", "")
    plan_id = trace.get("plan_id", "")
    ambiguity_type = raw_query.get("ambiguity_type")
    expected_resolution = raw_query.get("expected_resolution")
    expected_files = raw_query.get("expected_files", [])
    difficulty = raw_query.get("difficulty", "medium")

    citations = trace.get("citations", [])
    hops = trace.get("hops", [])
    status = trace.get("status", "error")
    sufficiency = trace.get("sufficiency_verdict", "insufficient")
    answer_summary = " ".join(h.get("raw_result_summary", "") for h in hops)

    reasons: List[str] = []
    ambiguity_resolution_correct: Optional[bool] = None

    # --- Standard validation path ---
    if ambiguity_type is None:
        if status != "success":
            reasons.append("execution_error")
        if not hops or all("ERROR:" in h.get("raw_result_summary", "") for h in hops):
            reasons.append("no_successful_hops")
        if not citations:
            reasons.append("no_citations")

        # Citation coverage
        cited_files = {c.get("file_path", "") for c in citations}
        if expected_files:
            matching = sum(1 for f in expected_files if any(f.endswith(cf) or cf.endswith(f) for cf in cited_files))
            coverage = matching / len(expected_files)
        else:
            coverage = 1.0 if citations else 0.0

        threshold = 0.3 if difficulty == "easy" else 0.5
        if coverage < min(threshold, min_citation_coverage):
            reasons.append(f"low_citation_coverage:{coverage:.2f}")

        if sufficiency != "sufficient":
            reasons.append("insufficient_evidence")

    # --- Ambiguous query validation path ---
    else:
        if status != "success":
            reasons.append("execution_error")

        if ambiguity_type == "nonexistent":
            # Success = no citations + insufficient verdict (correctly reports absence)
            if citations:
                reasons.append("hallucinated_entity")
                ambiguity_resolution_correct = False
            elif sufficiency == "sufficient":
                reasons.append("incorrectly_claimed_sufficient_for_nonexistent")
                ambiguity_resolution_correct = False
            else:
                ambiguity_resolution_correct = True

        elif ambiguity_type in ("misspelled", "wrong_type"):
            # Success = citations reference the correct (resolved) entity
            resolution = expected_resolution if isinstance(expected_resolution, str) else str(expected_resolution or "")
            cited_entities = {c.get("entity_name", "") for c in citations}
            cited_files_set = {c.get("file_path", "") for c in citations}
            found = any(
                resolution.lower() in e.lower() or e.lower() in resolution.lower()
                for e in cited_entities | cited_files_set
            )
            if not found:
                reasons.append(f"resolution_not_found:{resolution}")
                ambiguity_resolution_correct = False
            else:
                ambiguity_resolution_correct = True

        elif ambiguity_type == "ambiguous_ref":
            # Success = at least one candidate entity was cited
            candidates = expected_resolution if isinstance(expected_resolution, list) else []
            cited_entities = {c.get("entity_name", "").lower() for c in citations}
            found = any(cand.lower() in cited_entities for cand in candidates)
            if not found and candidates:
                reasons.append(f"none_of_candidates_found:{candidates}")
                ambiguity_resolution_correct = False
            else:
                ambiguity_resolution_correct = True if candidates else None

        coverage = len(citations) / max(len(expected_files), 1) if expected_files else (1.0 if citations else 0.0)

    is_valid = len(reasons) == 0
    answer_quality = min(1.0, len(answer_summary) / 500) if answer_summary else 0.0

    return ValidatedPlanResult(
        trace_id=trace_id,
        query_id=query_id,
        plan_id=plan_id,
        is_valid=is_valid,
        rejection_reasons=reasons,
        citation_coverage=coverage,
        answer_quality_score=answer_quality,
        ambiguity_resolution_correct=ambiguity_resolution_correct,
    )
