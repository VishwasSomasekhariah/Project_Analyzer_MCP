"""
Reads HelloWorldApp C# source files and builds a structured entity index
used by query_templates.py and ambiguous_query_generator.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Entity:
    name: str
    kind: str                      # "class" | "interface" | "method" | "field" | "namespace"
    file_path: str                 # relative path e.g. "Manager.cs"
    namespace: str = ""
    is_static: bool = False
    is_abstract: bool = False
    return_type: Optional[str] = None
    parameters: List[str] = field(default_factory=list)
    parent: Optional[str] = None   # containing class/interface name


@dataclass
class Relationship:
    source: str                    # entity name
    target: str                    # entity name
    rel_type: str                  # "IMPLEMENTS" | "CALLS" | "CREATES" | "USES" | "CONTAINS"
    source_file: str


@dataclass
class EntityIndex:
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def classes(self) -> List[Entity]:
        return [e for e in self.entities if e.kind == "class"]

    def interfaces(self) -> List[Entity]:
        return [e for e in self.entities if e.kind == "interface"]

    def methods(self) -> List[Entity]:
        return [e for e in self.entities if e.kind == "method"]

    def by_name(self, name: str) -> Optional[Entity]:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def relationships_for(self, name: str) -> List[Relationship]:
        return [r for r in self.relationships if r.source == name or r.target == name]


# ---------------------------------------------------------------------------
# Hardcoded index derived from HelloWorldApp source
# (avoids tree-sitter / Roslyn dependency in the pipeline)
# ---------------------------------------------------------------------------

def build_entity_index(repo_path: str) -> EntityIndex:
    """
    Returns a pre-built entity index for HelloWorldApp.
    The structure is derived from reading the actual source files.
    """
    idx = EntityIndex()

    base = "HelloWorldApp"

    # --- Files (relative to repo_path) ---
    idx.files = [
        f"{base}/Manager.cs",
        f"{base}/Program.cs",
        f"{base}/WorkerA.cs",
        f"{base}/WorkerB.cs",
        f"{base}/WorkerC.cs",
        f"{base}/WorkerFactory.cs",
        f"{base}/IWorker.cs",
        f"{base}/INotifier.cs",
        f"{base}/TestAliases.cs",
        f"{base}/Utilities/Helper.cs",
    ]

    # --- Interfaces ---
    for iface, fpath in [("IWorker", f"{base}/IWorker.cs"), ("INotifier", f"{base}/INotifier.cs")]:
        idx.entities.append(Entity(name=iface, kind="interface", file_path=fpath, namespace="HelloWorldApp"))

    # --- Classes ---
    classes = [
        ("Manager",      f"{base}/Manager.cs",      False, False),
        ("Program",      f"{base}/Program.cs",      False, False),
        ("WorkerA",      f"{base}/WorkerA.cs",      False, False),
        ("WorkerB",      f"{base}/WorkerB.cs",      False, False),
        ("WorkerC",      f"{base}/WorkerC.cs",      False, False),
        ("WorkerFactory",f"{base}/WorkerFactory.cs",True,  False),
        ("TestAliases",  f"{base}/TestAliases.cs",  False, False),
        ("Helper",       f"{base}/Utilities/Helper.cs", True, False),
    ]
    for name, fpath, is_static, is_abstract in classes:
        idx.entities.append(Entity(
            name=name, kind="class", file_path=fpath,
            namespace="HelloWorldApp" if name != "Helper" else "HelloWorldApp.Utilities",
            is_static=is_static, is_abstract=is_abstract,
        ))

    # --- Methods ---
    methods = [
        # (name, return_type, parameters, parent, file_path, is_static)
        ("Main",          "void",               ["string[] args"],           "Program",      f"{base}/Program.cs",         True),
        ("Run",           "void",               [],                          "Manager",      f"{base}/Manager.cs",         False),
        ("Notify",        "void",               ["string message"],          "Manager",      f"{base}/Manager.cs",         False),
        ("Process",       "void",               [],                          "WorkerA",      f"{base}/WorkerA.cs",         False),
        ("Process",       "void",               [],                          "WorkerB",      f"{base}/WorkerB.cs",         False),
        ("Process",       "void",               [],                          "WorkerC",      f"{base}/WorkerC.cs",         False),
        ("CreateWorkers", "IEnumerable<IWorker>",["INotifier notifier"],     "WorkerFactory",f"{base}/WorkerFactory.cs",  True),
        ("FormatMessage", "string",             ["string workerName","string text"], "Helper", f"{base}/Utilities/Helper.cs", True),
        ("TestMethod",    "void",               [],                          "TestAliases",  f"{base}/TestAliases.cs",     False),
        ("Process",       "void",               [],                          "IWorker",      f"{base}/IWorker.cs",         False),  # interface method
        ("Notify",        "void",               ["string message"],          "INotifier",    f"{base}/INotifier.cs",       False),  # interface method
    ]
    for mname, rtype, params, parent, fpath, is_static in methods:
        idx.entities.append(Entity(
            name=mname, kind="method", file_path=fpath,
            namespace="HelloWorldApp",
            is_static=is_static,
            return_type=rtype,
            parameters=params,
            parent=parent,
        ))

    # --- Fields ---
    for worker in ("WorkerA", "WorkerB", "WorkerC"):
        fpath = f"{base}/{worker}.cs"
        idx.entities.append(Entity(
            name="_notifier", kind="field", file_path=fpath,
            namespace="HelloWorldApp", parent=worker,
            return_type="INotifier",
        ))

    # --- Relationships ---
    rels = [
        # IMPLEMENTS
        ("Manager",      "INotifier",    "IMPLEMENTS", f"{base}/Manager.cs"),
        ("WorkerA",      "IWorker",      "IMPLEMENTS", f"{base}/WorkerA.cs"),
        ("WorkerB",      "IWorker",      "IMPLEMENTS", f"{base}/WorkerB.cs"),
        ("WorkerC",      "IWorker",      "IMPLEMENTS", f"{base}/WorkerC.cs"),
        # CREATES
        ("WorkerFactory","WorkerA",      "CREATES",    f"{base}/WorkerFactory.cs"),
        ("WorkerFactory","WorkerB",      "CREATES",    f"{base}/WorkerFactory.cs"),
        ("WorkerFactory","WorkerC",      "CREATES",    f"{base}/WorkerFactory.cs"),
        # CALLS
        ("Manager",      "WorkerFactory","CALLS",      f"{base}/Manager.cs"),
        ("Manager",      "IWorker",      "CALLS",      f"{base}/Manager.cs"),
        ("WorkerA",      "Helper",       "CALLS",      f"{base}/WorkerA.cs"),
        ("WorkerB",      "Helper",       "CALLS",      f"{base}/WorkerB.cs"),
        ("WorkerC",      "Helper",       "CALLS",      f"{base}/WorkerC.cs"),
        ("WorkerA",      "INotifier",    "CALLS",      f"{base}/WorkerA.cs"),
        ("WorkerB",      "INotifier",    "CALLS",      f"{base}/WorkerB.cs"),
        ("WorkerC",      "INotifier",    "CALLS",      f"{base}/WorkerC.cs"),
        ("Program",      "Manager",      "CALLS",      f"{base}/Program.cs"),
        # USES
        ("TestAliases",  "IWorker",      "USES",       f"{base}/TestAliases.cs"),
    ]
    for src, tgt, rtype, fpath in rels:
        idx.relationships.append(Relationship(source=src, target=tgt, rel_type=rtype, source_file=fpath))

    return idx


def read_source_files(repo_path: str) -> Dict[str, str]:
    """Returns {relative_path: file_content} for all non-generated C# files."""
    result = {}
    base = os.path.join(repo_path, "HelloWorldApp")
    for root, dirs, files in os.walk(base):
        # skip obj/bin generated dirs
        dirs[:] = [d for d in dirs if d not in ("obj", "bin")]
        for fname in files:
            if fname.endswith(".cs"):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, repo_path)
                with open(full) as f:
                    result[rel] = f.read()
    return result
