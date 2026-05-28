def _extract_key_properties(props):
    """
    Extract only key properties for node matching to avoid oversized queries
    """
    key_props = {}
    
    # Priority order for properties to use for matching
    priority_props = ['name', 'project_path', 'file_path', 'id', 'uuid', 'checksum']
    
    # First try to find priority properties
    for key in priority_props:
        if key in props and props[key] is not None:
            key_props[key] = props[key]
    
    # If we don't have any key properties, use a subset of available properties
    if not key_props:
        # Avoid large properties like 'body', 'symbols_location', etc.
        excluded_props = ['body', 'symbols_location', 'base_list', 'fields', 'documentation']
        for key, value in props.items():
            if key not in excluded_props and value is not None:
                key_props[key] = value
                # Limit to 3 properties to avoid oversized queries
                if len(key_props) >= 3:
                    break
    
    return key_props

def _flatten_complex_properties(props):
    """
    Flatten complex properties (tuples, lists, dicts) to JSON strings
    for Neo4j compatibility
    """
    import json
    
    flat_props = {}
    for k, v in props.items():
        if isinstance(v, (tuple, list)):
            # Convert tuples and lists to JSON strings
            flat_props[k] = json.dumps(v)
        elif isinstance(v, dict):
            # Convert dicts to JSON strings
            flat_props[k] = json.dumps(v)
        elif v is None:
            # Skip None values
            continue
        else:
            flat_props[k] = v
    return flat_props

import pickle

with open("generated_graph.pkl", "rb") as f:
    generated_graph = pickle.load(f)

items = generated_graph.keys()
Nodes = []
Relationships = []
for item in items:
    Nodes.append(generated_graph[item]['nodes'])
    Relationships.append(generated_graph[item]['relationships'])
flat_nodes = [d for sublist in Nodes for d in sublist]
flat_relationships = [d for sublist in Relationships for d in sublist]
rel_groups = {}

import json
import pickle

def fix_json_control_chars(s: str) -> str:
    fixed = ''
    in_str = False
    i = 0
    while i < len(s):
        c = s[i]
        if c == '"':
            # Count preceding backslashes to check if this quote is escaped
            bs = 0
            j = i - 1
            while j >= 0 and s[j] == '\\':
                bs += 1
                j -= 1
            if bs % 2 == 0:
                in_str = not in_str
            fixed += c
        elif c == '\n' and in_str:
            fixed += '\\n'
        else:
            fixed += c
        i += 1
    return fixed

# 1) Load and fix the JSON
with open('records.json', 'r', encoding='utf-8-sig') as f:
    raw = f.read()
data = json.loads(fix_json_control_chars(raw))

# 2) Extract CALLS segments with full node info
call_relations_graphdb = []
for record in data:
    for seg in record.get("p", {}).get("segments", []):
        rel = seg.get("relationship", {})
        if rel.get("type") == "CALLS":
            call_relations_graphdb.append({
                "relationship": rel,
                "source_node": seg.get("start"),   # full start node dict
                "target_node": seg.get("end")      # full end node dict
            })

calls_raw = [r for r in Relationships if r.get("type") == "CALLS"]

from collections import Counter

# 1) Robust key extractors

def raw_key(r):
    """
    For calls_raw entries like {'type':'CALLS','from':{...},'to':{...}, ...}
    """
    src, tgt = r.get("from", {}), r.get("to", {})
    return (
        src.get("file_path"),
        src.get("name"),
        tgt.get("file_path"),
        tgt.get("name"),
    )

def graph_key(r):
    """
    For call_relations_graphdb entries like
      {'relationship': {...},
       'source_node': {'properties': {...}},
       'target_node': {'properties': {...}}}
    """
    src = r.get("source_node", {}).get("properties", {})
    tgt = r.get("target_node", {}).get("properties", {})
    return (
        src.get("file_path"),
        src.get("name"),
        tgt.get("file_path"),
        tgt.get("name"),
    )

# 2) Filter out any entries where the key is incomplete
filtered_raw   = [r for r in calls_raw              if None not in raw_key(r)]
filtered_graph = [r for r in call_relations_graphdb if None not in graph_key(r)]

# 3) Build sets of keys
raw_keys   = { raw_key(r)   for r in filtered_raw }
graph_keys = { graph_key(r) for r in filtered_graph }

# 4) Intersection and differences
common_keys     = raw_keys   & graph_keys
raw_only_keys   = raw_keys   - graph_keys
graph_only_keys = graph_keys - raw_keys

# 5) Recover the actual dicts
common_in_raw   = [r for r in filtered_raw   if raw_key(r)   in common_keys]
common_in_graph = [r for r in filtered_graph if graph_key(r) in common_keys]

raw_only        = [r for r in filtered_raw   if raw_key(r)   in raw_only_keys]
graph_only      = [r for r in filtered_graph if graph_key(r) in graph_only_keys]

print("Totals:")
print(f"  • CALLS in both:    {len(common_keys)}")
print(f"  • CALLS only raw:   {len(raw_only_keys)}")
print(f"  • CALLS only graph: {len(graph_only_keys)}")

# 6) (Optional) See counts by type
print("All types in raw:", Counter(r["type"] for r in calls_raw))
print("All types in graph:", Counter(r["relationship"]["type"] for r in call_relations_graphdb))

for rel in Relationships:
    from_type = rel.get("from_node_type")
    to_type = rel.get("to_node_type")
    rel_type = rel.get("rel_type", "").split("?")[0]  # Sanitize relationship type
    
    key = f"{from_type}_{rel_type}_{to_type}"
    if key not in rel_groups:
        rel_groups[key] = []
    
    # Extract only key properties for matching
    from_key_props = _extract_key_properties(rel.get("from_node_props", {}))
    to_key_props = _extract_key_properties(rel.get("to_node_props", {}))
    
    rel_groups[key].append({
        "from_props": _flatten_complex_properties(from_key_props),
        "to_props": _flatten_complex_properties(to_key_props),
        "rel_props": _flatten_complex_properties(rel.get("properties", {}))
    })

print("Hello World")