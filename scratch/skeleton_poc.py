"""
Proof-of-concept: Language-agnostic code skeleton builder using tree-sitter.

Traverses the AST and replaces entity bodies with ... + line range,
producing an Option-C style skeleton regardless of language.
"""

import sys
sys.path.insert(0, '/opt/genpod/project_analyzer_cli')

from tree_sitter import Language, Parser
from project_analyzer.utils.path_utils import get_parser_path

# ---------------------------------------------------------------------------
# Leaf entity types whose bodies should be stripped.
# These are nodes that contain executable code (not structural containers).
# Namespace / class / interface bodies are NOT stripped — they're structure.
# ---------------------------------------------------------------------------
LEAF_ENTITY_TYPES = {
    # C#, Java, Go, Rust
    'method_declaration',
    'constructor_declaration',
    'destructor_declaration',
    'operator_declaration',
    'accessor_declaration',       # C# property getter/setter
    'function_declaration',       # Go, C, C++
    'method_definition',          # JS/TS class method
    'function_definition',        # Python, C, C++
    # Rust
    'function_item',
    # JS/TS
    'arrow_function',
    'function_expression',
}

# The child node type that holds the body for each leaf entity
BODY_NODE_TYPES = {
    'block',             # C#, Java, Go, Rust
    'statement_block',   # JavaScript, TypeScript
    'body',              # Python
    'compound_statement' # C, C++
}

# ---------------------------------------------------------------------------
# Language config: .so path + file extensions
# ---------------------------------------------------------------------------
LANGUAGE_MAP = {
    '.cs':   ('tree_sitter_c_sharp',    None,           'c_sharp'),
    '.py':   ('tree_sitter_python',     None,           'python'),
    '.java': ('tree_sitter_java',       None,           'java'),
    '.go':   ('tree_sitter_go',         None,           'go'),
    '.js':   ('tree_sitter_javascript', None,           'javascript'),
    '.ts':   ('tree_sitter_typescript', '._typescript', 'typescript'),
    '.rs':   ('tree_sitter_rust',       None,           'rust'),
    '.c':    ('tree_sitter_c',          None,           'c'),
    '.cpp':  ('tree_sitter_cpp',        None,           'cpp'),
}


def get_language(ext: str) -> Language:
    if ext not in LANGUAGE_MAP:
        raise ValueError(f"Unsupported extension: {ext}")
    grammar, subdir, lang_key = LANGUAGE_MAP[ext]
    so_path = get_parser_path(grammar, subdir)
    return Language(so_path, lang_key)


def build_skeleton(source: str, language: Language) -> str:
    """
    Parse source and return skeleton: entity declarations kept,
    bodies stripped and replaced with '... // L{start}-{end}'.
    """
    parser = Parser()
    parser.set_language(language)
    tree = parser.parse(source.encode())

    lines = source.splitlines()
    # Track which line ranges are body interiors to suppress
    # Each entry: (first_interior_line, last_interior_line)
    suppressed: list[tuple[int, int]] = []

    # TreeCursor traversal — C-level, no Python Node allocation per step
    cursor = tree.walk()
    visited_children = False
    while True:
        node = cursor.node
        if not visited_children:
            if node.type in LEAF_ENTITY_TYPES:
                for child in node.children:
                    if child.type in BODY_NODE_TYPES:
                        body_start = child.start_point[0]
                        body_end   = child.end_point[0]
                        interior_start = body_start + 1
                        interior_end   = body_end - 1
                        if interior_end >= interior_start:
                            suppressed.append((interior_start, interior_end))
                # skip descending into leaf entity — body already captured
                visited_children = True
                continue
            if cursor.goto_first_child():
                visited_children = False
                continue
        if cursor.goto_next_sibling():
            visited_children = False
            continue
        if not cursor.goto_parent():
            break
        visited_children = True

    # Build a set of suppressed line numbers for fast lookup
    suppressed_lines: dict[int, tuple[int, int]] = {}
    for (s, e) in suppressed:
        for ln in range(s, e + 1):
            suppressed_lines[ln] = (s + 1, e + 1)  # convert to 1-indexed for display

    output = []
    i = 0
    while i < len(lines):
        ln = i  # 0-indexed
        if ln in suppressed_lines:
            s1, e1 = suppressed_lines[ln]
            # Emit a single ... placeholder, then skip to end of suppressed range
            indent = len(lines[ln]) - len(lines[ln].lstrip())
            placeholder = ' ' * indent + f'...'
            comment = f'// L{s1}-{e1}' if s1 != e1 else f'// L{s1}'
            output.append(f'{placeholder:<60}{comment}')
            # Skip all lines in this suppressed block
            while i < len(lines) and i in suppressed_lines:
                i += 1
        else:
            line = lines[ln]
            comment = f'// L{ln + 1}'
            output.append(f'{line:<60}{comment}')
            i += 1

    return '\n'.join(output)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    import os

    target = sys.argv[1] if len(sys.argv) > 1 else '/opt/HelloWorldApp/HelloWorldApp/Manager.cs'
    ext = os.path.splitext(target)[1]

    print(f"File : {target}")
    print(f"Lang : {ext}")
    print("=" * 80)

    with open(target) as f:
        source = f.read()

    lang = get_language(ext)
    skeleton = build_skeleton(source, lang)
    print(skeleton)
