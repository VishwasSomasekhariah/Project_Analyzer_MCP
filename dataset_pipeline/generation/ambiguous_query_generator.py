"""
Generates ambiguous queries — misspelled entity names, wrong entity types,
non-existent entities, and ambiguous references. These teach the orchestrator
to recover gracefully rather than fail silently.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List

from dataset_pipeline.generation.repo_analyzer import build_entity_index
from dataset_pipeline.models import RawQuery

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are generating intentionally flawed code analysis queries to test retrieval robustness.
Output ONLY valid JSON. No markdown, no explanation."""

_MISSPELL_PROMPT = """\
Entity names in HelloWorldApp: {entity_names}

For each entity, generate ONE query that contains a realistic typo or misspelling of that entity name (1–2 character changes). The query should ask something natural about the entity.

Output JSON array: [{{"entity": "...", "misspelled_as": "...", "query": "...", "expected_resolution": "..."}}]"""

_WRONG_TYPE_PROMPT = """\
Entities in HelloWorldApp with their actual types:
{entity_list}

For 8 of these, generate queries that incorrectly describe the entity type (e.g., calling a class an interface, a method a class, etc.). The query should ask something natural but use the wrong type label.

Output JSON array: [{{"entity": "...", "actual_type": "...", "wrong_type_used": "...", "query": "...", "expected_resolution": "..."}}]"""

_NONEXISTENT_PROMPT = """\
Real entities in HelloWorldApp: {entity_names}

Generate 10 queries that ask about plausible but non-existent entities — names that sound like they COULD be in a .NET app but are NOT in HelloWorldApp. Examples: ServiceLocator, Repository, EventBus, LogManager, WorkerD.

Output JSON array: [{{"fictitious_entity": "...", "query": "...", "expected_resolution": null}}]"""

_AMBIGUOUS_REF_PROMPT = """\
HelloWorldApp has these entities: {entity_names}

Generate 8 queries that use vague references ("the worker", "the factory", "the interface", "the helper") without specifying which exact entity. These should be questions where multiple entities match the vague description.

Output JSON array: [{{"vague_term": "...", "query": "...", "expected_resolution": ["list", "of", "matching", "entities"]}}]"""


async def _call_llm(llm_service, prompt: str) -> Any:
    resp = await llm_service.generate_response(
        prompt=prompt,
        system_prompt=_SYSTEM_PROMPT,
        json_mode=True,
        temperature=0.8,
        max_tokens=2000,
    )
    if resp.error:
        raise RuntimeError(resp.error)
    return json.loads(resp.content)


async def generate_ambiguous_queries(
    repo_path: str,
    llm_service,
    id_prefix: str = "amb",
) -> List[RawQuery]:
    idx = build_entity_index(repo_path)
    results: List[RawQuery] = []
    counter = [0]

    def make_id() -> str:
        counter[0] += 1
        return f"{id_prefix}_{counter[0]:04d}"

    entity_names = [e.name for e in idx.classes() + idx.interfaces()]
    entity_list = "\n".join(
        f"- {e.name}: {e.kind} in {e.file_path}"
        for e in idx.classes() + idx.interfaces() + idx.methods()
    )

    # --- Misspelled ---
    try:
        items = await _call_llm(llm_service, _MISSPELL_PROMPT.format(entity_names=", ".join(entity_names)))
        for item in items:
            q = item.get("query", "").strip()
            if not q:
                continue
            entity = idx.by_name(item.get("entity", ""))
            results.append(RawQuery(
                query_id=make_id(),
                query=q,
                source="ambiguous",
                base_query_id=None,
                query_type="ambiguous",
                difficulty="hard",
                expected_files=[entity.file_path] if entity else [],
                ambiguity_type="misspelled",
                expected_resolution=item.get("expected_resolution"),
                metadata={"misspelled_as": item.get("misspelled_as")},
            ))
        logger.info(f"Generated {len(items)} misspelled queries")
    except Exception as e:
        logger.warning(f"Misspelled query generation failed: {e}")

    # --- Wrong type ---
    try:
        items = await _call_llm(llm_service, _WRONG_TYPE_PROMPT.format(entity_list=entity_list))
        for item in items:
            q = item.get("query", "").strip()
            if not q:
                continue
            entity = idx.by_name(item.get("entity", ""))
            results.append(RawQuery(
                query_id=make_id(),
                query=q,
                source="ambiguous",
                base_query_id=None,
                query_type="ambiguous",
                difficulty="hard",
                expected_files=[entity.file_path] if entity else [],
                ambiguity_type="wrong_type",
                expected_resolution=item.get("expected_resolution"),
                metadata={"actual_type": item.get("actual_type"), "wrong_type_used": item.get("wrong_type_used")},
            ))
        logger.info(f"Generated {len(items)} wrong-type queries")
    except Exception as e:
        logger.warning(f"Wrong-type query generation failed: {e}")

    # --- Non-existent ---
    try:
        items = await _call_llm(llm_service, _NONEXISTENT_PROMPT.format(entity_names=", ".join(entity_names)))
        for item in items:
            q = item.get("query", "").strip()
            if not q:
                continue
            results.append(RawQuery(
                query_id=make_id(),
                query=q,
                source="ambiguous",
                base_query_id=None,
                query_type="ambiguous",
                difficulty="hard",
                expected_files=[],
                ambiguity_type="nonexistent",
                expected_resolution=None,
                metadata={"fictitious_entity": item.get("fictitious_entity")},
            ))
        logger.info(f"Generated {len(items)} non-existent entity queries")
    except Exception as e:
        logger.warning(f"Non-existent query generation failed: {e}")

    # --- Ambiguous reference ---
    try:
        items = await _call_llm(llm_service, _AMBIGUOUS_REF_PROMPT.format(entity_names=", ".join(entity_names)))
        for item in items:
            q = item.get("query", "").strip()
            if not q:
                continue
            candidates = item.get("expected_resolution", [])
            candidate_entities = [idx.by_name(c) for c in candidates if idx.by_name(c)]
            expected_files = list({e.file_path for e in candidate_entities if e})
            results.append(RawQuery(
                query_id=make_id(),
                query=q,
                source="ambiguous",
                base_query_id=None,
                query_type="ambiguous",
                difficulty="hard",
                expected_files=expected_files,
                ambiguity_type="ambiguous_ref",
                expected_resolution=candidates,
                metadata={"vague_term": item.get("vague_term")},
            ))
        logger.info(f"Generated {len(items)} ambiguous-reference queries")
    except Exception as e:
        logger.warning(f"Ambiguous-ref query generation failed: {e}")

    logger.info(f"Ambiguous query generation complete: {len(results)} total")
    return results
