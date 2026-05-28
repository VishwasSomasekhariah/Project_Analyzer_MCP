"""
Generates N diverse routing plans per query using the LLM.
"""

from __future__ import annotations

import json
import logging
from typing import List

from dataset_pipeline.models import RawQuery, RoutingPlan, StepInstruction
from dataset_pipeline.planning.prompts import PLAN_SYSTEM, PLAN_USER

logger = logging.getLogger(__name__)

_VALID_AGENTS = {"pageindex", "vector", "graph"}


def _parse_plans(raw: list, query_id: str, n_plans: int) -> List[RoutingPlan]:
    plans: List[RoutingPlan] = []
    for i, item in enumerate(raw[:n_plans]):
        seq = [a for a in item.get("agent_sequence", []) if a in _VALID_AGENTS]
        if not seq:
            continue
        raw_steps = item.get("step_instructions", [])
        steps = []
        for j, step in enumerate(raw_steps):
            agent = step.get("agent", seq[j] if j < len(seq) else seq[0])
            if agent not in _VALID_AGENTS:
                agent = seq[j] if j < len(seq) else seq[0]
            steps.append(StepInstruction(
                agent=agent,
                what_to_look_for=step.get("what_to_look_for", ""),
            ))
        # If no steps, synthesize from sequence
        if not steps:
            steps = [StepInstruction(agent=a, what_to_look_for="") for a in seq]

        plans.append(RoutingPlan(
            plan_id=f"{query_id}_plan{i}",
            query_id=query_id,
            agent_sequence=seq,
            step_instructions=steps,
            llm_reasoning=item.get("reasoning", ""),
            plan_index=i,
        ))
    return plans


async def generate_plans_for_query(
    raw_query: RawQuery,
    llm_service,
    n_plans: int = 3,
) -> List[RoutingPlan]:
    prompt = PLAN_USER.format(
        query=raw_query.query,
        query_type=raw_query.query_type,
        n_plans=n_plans,
    )
    try:
        resp = await llm_service.generate_response(
            prompt=prompt,
            system_prompt=PLAN_SYSTEM,
            json_mode=True,
            temperature=0.7,
            max_tokens=2000,
            use_cache=False,
        )
        if resp.error:
            logger.warning(f"Plan generation error for {raw_query.query_id}: {resp.error}")
            return _fallback_plans(raw_query, n_plans)
        raw = json.loads(resp.content)
        if not isinstance(raw, list):
            logger.warning(f"Unexpected plan output for {raw_query.query_id}")
            return _fallback_plans(raw_query, n_plans)
        plans = _parse_plans(raw, raw_query.query_id, n_plans)
        if not plans:
            return _fallback_plans(raw_query, n_plans)
        return plans
    except Exception as e:
        logger.warning(f"Plan generation failed for {raw_query.query_id}: {e}")
        return _fallback_plans(raw_query, n_plans)


def _fallback_plans(raw_query: RawQuery, n_plans: int) -> List[RoutingPlan]:
    """Minimal fallback plans when LLM fails — ensures pipeline continues."""
    sequences = [
        ["pageindex"],
        ["vector", "graph"],
        ["graph", "vector"],
    ]
    plans = []
    for i, seq in enumerate(sequences[:n_plans]):
        steps = [StepInstruction(agent=a, what_to_look_for=raw_query.query) for a in seq]
        plans.append(RoutingPlan(
            plan_id=f"{raw_query.query_id}_plan{i}",
            query_id=raw_query.query_id,
            agent_sequence=seq,
            step_instructions=steps,
            llm_reasoning="fallback plan",
            plan_index=i,
        ))
    return plans
