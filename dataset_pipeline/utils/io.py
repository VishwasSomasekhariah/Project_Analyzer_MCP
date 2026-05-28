"""
JSONL read/write helpers with atomic saves.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, List, TypeVar

T = TypeVar("T")


def write_jsonl(path: str, records: Iterable[Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for rec in records:
            obj = asdict(rec) if hasattr(rec, "__dataclass_fields__") else rec
            f.write(json.dumps(obj, default=str) + "\n")
    os.replace(tmp, path)


def append_jsonl(path: str, record: Any) -> None:
    obj = asdict(record) if hasattr(record, "__dataclass_fields__") else record
    with open(path, "a") as f:
        f.write(json.dumps(obj, default=str) + "\n")


def read_jsonl(path: str, constructor: Callable[[dict], T] = None) -> List[Any]:
    results = []
    if not os.path.exists(path):
        return results
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            results.append(constructor(**obj) if constructor else obj)
    return results


def iter_jsonl(path: str) -> Iterator[dict]:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_json(path: str) -> Any:
    with open(path) as f:
        return json.load(f)


def save_json(path: str, obj: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2, default=str)
    os.replace(tmp, path)
