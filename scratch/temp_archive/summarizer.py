import pickle
from typing import Any
import os
import sys
from datetime import datetime


def get_type_name(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    elif isinstance(value, list):
        return f"list[{get_type_name(value[0])}]" if value else "list[unknown]"
    else:
        return type(value).__name__


def summarize_dict(d: dict, depth=0) -> str:
    indent = "  " * depth
    lines = []
    for key, value in d.items():
        if isinstance(value, dict):
            lines.append(f"{indent}{key}: dict {{")
            lines.append(summarize_dict(value, depth + 1))
            lines.append(f"{indent}}}")
        elif isinstance(value, list):
            item_type = get_type_name(value[0]) if value else "unknown"
            lines.append(f"{indent}{key}: list[{item_type}]")
            if value and isinstance(value[0], dict):
                lines.append(f"{indent}  item schema:")
                lines.append(summarize_dict(value[0], depth + 2))
        else:
            preview = repr(value)
            lines.append(f"{indent}{key}: {type(value).__name__} = {preview[:60]}")
    return "\n".join(lines)


def load_and_summarize_pickle(path: str) -> str:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    
    with open(path, "rb") as f:
        obj = pickle.load(f)
    
    if not isinstance(obj, dict):
        raise TypeError(f"Expected dict, got {type(obj)}")
    
    return summarize_dict(obj)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python summarize_pickle.py <path_to_pickle_file>")
        sys.exit(1)

    input_path = sys.argv[1]

    try:
        summary = load_and_summarize_pickle(input_path)
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base_name}_summary_{timestamp}.txt"
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(summary)

        print(f"✅ Summary written to: {output_path}")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
