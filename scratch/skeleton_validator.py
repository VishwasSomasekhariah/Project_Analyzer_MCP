"""
Validates the skeleton output against the original source file.

Checks:
1. Every skeleton line's comment says // LN — verify the line content matches
   the actual source line N (verbatim, modulo padding).
2. Every ... placeholder's range [Ls-Le] — verify those source lines are
   genuinely inside a body block (not declarations).
3. No source line is both in the skeleton AND in a suppressed range.
4. Every source line is accounted for exactly once (either kept or suppressed).
5. Suppressed ranges contain no entity declarations (signatures not lost).
"""

import re
import sys
sys.path.insert(0, '/opt/genpod/project_analyzer_cli')

from tree_sitter import Language, Parser
from project_analyzer.utils.path_utils import get_parser_path

LEAF_ENTITY_TYPES = {
    'method_declaration', 'constructor_declaration', 'destructor_declaration',
    'operator_declaration', 'accessor_declaration', 'function_declaration',
    'method_definition', 'function_definition', 'function_item',
    'arrow_function', 'function_expression',
}
BODY_NODE_TYPES = {'block', 'statement_block', 'body', 'compound_statement'}

# Entity declaration node types — these must NEVER be inside a suppressed range
DECLARATION_NODE_TYPES = {
    'class_declaration', 'interface_declaration', 'struct_declaration',
    'enum_declaration', 'namespace_declaration',
    'method_declaration', 'constructor_declaration', 'destructor_declaration',
    'operator_declaration', 'accessor_declaration', 'function_declaration',
    'method_definition', 'function_definition',
    'field_declaration', 'property_declaration', 'event_declaration',
}


def get_body_ranges(tree):
    """Return set of (interior_start, interior_end) 0-indexed line ranges for all leaf bodies."""
    ranges = []
    cursor = tree.walk()
    visited_children = False
    while True:
        node = cursor.node
        if not visited_children:
            if node.type in LEAF_ENTITY_TYPES:
                for child in node.children:
                    if child.type in BODY_NODE_TYPES:
                        s = child.start_point[0] + 1   # 0-indexed interior start
                        e = child.end_point[0] - 1     # 0-indexed interior end
                        if e >= s:
                            ranges.append((s, e, child))
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
    return ranges


def get_all_declaration_lines(tree):
    """Return set of 0-indexed line numbers where entity declarations start."""
    decl_lines = set()
    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type in DECLARATION_NODE_TYPES:
            decl_lines.add(node.start_point[0])
        stack.extend(node.children)
    return decl_lines


def parse_skeleton(skeleton_lines):
    """
    Parse skeleton lines into:
    - kept: {line_number_1indexed: stripped_content}
    - suppressed: [(start_1indexed, end_1indexed)]

    Two line formats:
      Kept      : <content padded>  // L{n}
      Suppressed: <indent>...       // L{s}-{e}  (or // L{n} for single line)
    """
    kept = {}
    suppressed = []

    for skel_line in skeleton_lines:
        # Suppressed: line contains '...' before the comment
        supp_m = re.match(r'^(\s*)\.\.\.(\s*)//\s+L(\d+)(?:-(\d+))?\s*$', skel_line)
        if supp_m:
            s = int(supp_m.group(3))
            e = int(supp_m.group(4)) if supp_m.group(4) else s
            suppressed.append((s, e))
            continue

        # Kept: ends with // L{n} (single number only)
        kept_m = re.search(r'//\s+L(\d+)\s*$', skel_line)
        if kept_m:
            ln = int(kept_m.group(1))
            content = skel_line[:kept_m.start()].rstrip()
            kept[ln] = content

    return kept, suppressed


def validate(source_path, skeleton_path):
    with open(source_path) as f:
        source = f.read()
    source_lines = source.splitlines()

    with open(skeleton_path) as f:
        skeleton_raw = [l.rstrip('\n') for l in f.readlines()]

    # Parse
    so_path = get_parser_path('tree_sitter_c_sharp', None)
    lang = Language(so_path, 'c_sharp')
    parser = Parser()
    parser.set_language(lang)
    tree = parser.parse(source.encode())

    body_ranges = get_body_ranges(tree)
    decl_lines  = get_all_declaration_lines(tree)

    # Build ground-truth suppressed set from AST (0-indexed)
    ast_suppressed = set()
    for (s, e, _) in body_ranges:
        for ln in range(s, e + 1):
            ast_suppressed.add(ln)

    kept, suppressed = parse_skeleton(skeleton_raw)

    errors = []
    warnings = []

    # ----------------------------------------------------------------
    # CHECK 1: Every kept line's content matches source verbatim
    # ----------------------------------------------------------------
    for ln_1, skel_content in kept.items():
        ln_0 = ln_1 - 1
        if ln_0 >= len(source_lines):
            errors.append(f"CHECK1: skeleton references L{ln_1} but source only has {len(source_lines)} lines")
            continue
        src_content = source_lines[ln_0]
        # Compare stripped (the skeleton pads with spaces for alignment)
        if skel_content.rstrip() != src_content.rstrip():
            errors.append(
                f"CHECK1: L{ln_1} content mismatch\n"
                f"  skeleton : {repr(skel_content.rstrip())}\n"
                f"  source   : {repr(src_content.rstrip())}"
            )

    # ----------------------------------------------------------------
    # CHECK 2: Every suppressed range matches AST body ranges
    # ----------------------------------------------------------------
    for (s, e) in suppressed:
        for ln_1 in range(s, e + 1):
            ln_0 = ln_1 - 1
            if ln_0 not in ast_suppressed:
                errors.append(
                    f"CHECK2: L{ln_1} is in skeleton suppressed range [{s}-{e}] "
                    f"but AST says it is NOT inside a body"
                )

    # ----------------------------------------------------------------
    # CHECK 3: No source line is both kept and suppressed
    # ----------------------------------------------------------------
    skeleton_suppressed_set = set()
    for (s, e) in suppressed:
        for ln_1 in range(s, e + 1):
            skeleton_suppressed_set.add(ln_1)

    for ln_1 in kept:
        if ln_1 in skeleton_suppressed_set:
            errors.append(f"CHECK3: L{ln_1} appears both as kept and suppressed in skeleton")

    # ----------------------------------------------------------------
    # CHECK 4: Every source line accounted for exactly once
    # ----------------------------------------------------------------
    all_skeleton_lines = set(kept.keys()) | skeleton_suppressed_set
    for ln_0 in range(len(source_lines)):
        ln_1 = ln_0 + 1
        if ln_1 not in all_skeleton_lines:
            errors.append(f"CHECK4: L{ln_1} is missing from skeleton entirely")

    for ln_1 in all_skeleton_lines:
        ln_0 = ln_1 - 1
        if ln_0 >= len(source_lines):
            errors.append(f"CHECK4: skeleton references L{ln_1} which is beyond source end")

    # ----------------------------------------------------------------
    # CHECK 5: No declaration node starts inside a suppressed range
    # ----------------------------------------------------------------
    for ln_0 in decl_lines:
        if ln_0 in ast_suppressed:
            ln_1 = ln_0 + 1
            errors.append(
                f"CHECK5: Declaration at L{ln_1} ({source_lines[ln_0].strip()[:60]}) "
                f"is inside a suppressed body range — signature would be lost"
            )

    # ----------------------------------------------------------------
    # Summary
    # ----------------------------------------------------------------
    total_src   = len(source_lines)
    total_kept  = len(kept)
    total_supp  = len(skeleton_suppressed_set)
    compression = (1 - len(skeleton_raw) / total_src) * 100

    print(f"Source lines     : {total_src:,}")
    print(f"Skeleton lines   : {len(skeleton_raw):,}  ({compression:.1f}% compression)")
    print(f"Lines kept       : {total_kept:,}")
    print(f"Lines suppressed : {total_supp:,}  ({len(suppressed)} ranges)")
    print(f"Decl lines found : {len(decl_lines):,}")
    print()

    if errors:
        print(f"FAILED — {len(errors)} error(s):")
        for e in errors[:20]:   # cap at 20
            print(f"  ✗ {e}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more")
    else:
        print(f"ALL CHECKS PASSED")

    if warnings:
        for w in warnings:
            print(f"  ⚠ {w}")

    return len(errors) == 0


if __name__ == '__main__':
    src  = sys.argv[1] if len(sys.argv) > 1 else '/tmp/large_test.cs'
    skel = sys.argv[2] if len(sys.argv) > 2 else '/tmp/large_skeleton.txt'
    ok = validate(src, skel)
    sys.exit(0 if ok else 1)
