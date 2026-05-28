"""
Generates systematic query coverage from the entity index using template patterns.
Produces ~328 unique queries covering every entity, relationship, and file.
"""

from __future__ import annotations

import itertools
from typing import List

from dataset_pipeline.generation.repo_analyzer import EntityIndex, build_entity_index
from dataset_pipeline.models import RawQuery


_ENTITY_TEMPLATES = [
    # factual
    ("factual",     "easy",   "What is the purpose of the {kind} {name} in HelloWorldApp?"),
    ("factual",     "easy",   "Which file defines {name}?"),
    ("factual",     "easy",   "What namespace does {name} belong to?"),
    ("factual",     "easy",   "Is {name} static or instance-level?"),
    # structural
    ("structural",  "medium", "List all members (methods and fields) of {name}."),
    ("structural",  "medium", "What access modifier does {name} use?"),
    # behavioral
    ("behavioral",  "medium", "What does {name} do at runtime?"),
    ("behavioral",  "hard",   "Describe the execution flow when {name} is called."),
]

_METHOD_TEMPLATES = [
    ("factual",     "easy",   "What does the method {name} in {parent} return?"),
    ("factual",     "easy",   "What parameters does {name} in {parent} accept?"),
    ("behavioral",  "medium", "Describe what happens when {parent}.{name}() is invoked."),
    ("structural",  "medium", "Is {parent}.{name} a static or instance method?"),
]

_RELATIONSHIP_TEMPLATES = [
    ("structural",  "medium", "Which classes implement {target} in HelloWorldApp?"),
    ("structural",  "hard",   "Describe the dependency between {source} and {target}."),
    ("behavioral",  "hard",   "How does {source} interact with {target} at runtime?"),
    ("cross_cutting","hard",  "Trace the call chain from {source} to {target}."),
]

_FILE_TEMPLATES = [
    ("factual",     "easy",   "What is the role of {file} in HelloWorldApp?"),
    ("structural",  "easy",   "List all classes or interfaces defined in {file}."),
    ("structural",  "medium", "What using statements appear in {file}?"),
    ("behavioral",  "medium", "What happens when the code in {file} executes?"),
]

_CROSS_FILE_TEMPLATES = [
    ("cross_cutting","medium","How do {file_a} and {file_b} relate to each other?"),
    ("cross_cutting","hard",  "What is the interaction between the code in {file_a} and {file_b}?"),
]


def _base_name(file_path: str) -> str:
    """Returns just the filename, e.g. 'Manager.cs'."""
    return file_path.split("/")[-1]


def generate_template_queries(repo_path: str, id_prefix: str = "tmpl") -> List[RawQuery]:
    idx = build_entity_index(repo_path)
    queries: List[RawQuery] = []
    seen: set = set()
    counter = [0]

    def add(text: str, qtype: str, difficulty: str, expected_files: List[str]) -> None:
        if text in seen:
            return
        seen.add(text)
        counter[0] += 1
        queries.append(RawQuery(
            query_id=f"{id_prefix}_{counter[0]:04d}",
            query=text,
            source="repo_generated",
            base_query_id=None,
            query_type=qtype,
            difficulty=difficulty,
            expected_files=expected_files,
        ))

    # Per-entity templates (classes and interfaces)
    for entity in idx.classes() + idx.interfaces():
        for qtype, difficulty, tmpl in _ENTITY_TEMPLATES:
            text = tmpl.format(kind=entity.kind, name=entity.name)
            add(text, qtype, difficulty, [entity.file_path])

    # Per-method templates
    for method in idx.methods():
        if method.parent:
            for qtype, difficulty, tmpl in _METHOD_TEMPLATES:
                text = tmpl.format(name=method.name, parent=method.parent)
                add(text, qtype, difficulty, [method.file_path])

    # Relationship templates — IMPLEMENTS and CALLS only (most interesting)
    impl_rels = [r for r in idx.relationships if r.rel_type == "IMPLEMENTS"]
    call_rels = [r for r in idx.relationships if r.rel_type in ("CALLS", "CREATES")]
    for rel in impl_rels + call_rels:
        src_entity = idx.by_name(rel.source)
        tgt_entity = idx.by_name(rel.target)
        src_file = src_entity.file_path if src_entity else rel.source_file
        tgt_file = tgt_entity.file_path if tgt_entity else ""
        expected = list({src_file, tgt_file} - {""})
        for qtype, difficulty, tmpl in _RELATIONSHIP_TEMPLATES:
            text = tmpl.format(source=rel.source, target=rel.target)
            add(text, qtype, difficulty, expected)

    # Per-file templates
    for fpath in idx.files:
        fname = _base_name(fpath)
        for qtype, difficulty, tmpl in _FILE_TEMPLATES:
            text = tmpl.format(file=fname)
            add(text, qtype, difficulty, [fpath])

    # Cross-file pairs (sample interesting pairs to avoid combinatorial explosion)
    interesting_pairs = [
        ("Manager.cs",      "WorkerFactory.cs"),
        ("Manager.cs",      "INotifier.cs"),
        ("WorkerA.cs",      "IWorker.cs"),
        ("WorkerFactory.cs","IWorker.cs"),
        ("Program.cs",      "Manager.cs"),
        ("WorkerA.cs",      "Helper.cs"),
        ("WorkerB.cs",      "WorkerC.cs"),
        ("IWorker.cs",      "INotifier.cs"),
        ("TestAliases.cs",  "Manager.cs"),
    ]
    file_map = {_base_name(f): f for f in idx.files}
    for fa, fb in interesting_pairs:
        for qtype, difficulty, tmpl in _CROSS_FILE_TEMPLATES:
            text = tmpl.format(file_a=fa, file_b=fb)
            expected = [p for p in [file_map.get(fa), file_map.get(fb)] if p]
            add(text, qtype, difficulty, expected)

    return queries
