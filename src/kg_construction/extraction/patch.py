"""
patch.py

Unified diff parsing for code change extraction.

Identifies which functions/classes in code_file were genuinely changed by a
patch, by parsing the PRE-PATCH source file's real AST and mapping each
changed line number (from the diff) against each function/class's actual
lineno/end_lineno range -- rather than inferring boundaries from whatever
happens to be visible in a hunk's small, variable context window.

Replaces an earlier hunk/line-scanning approach that inferred boundaries
from the diff text alone. That approach caused four distinct bugs over
time (kg_construction#14, #43, #63, #71), all from the same root cause: a
diff's context window can miss a real def/class line, or sweep in an
unrelated one, and there was no way to tell the two apart from the diff
text alone. Resolving by real line ranges eliminates that whole class --
see kg_construction#75 for the investigation and rationale.
"""

import ast
import re
from typing import List, NamedTuple, Optional, Set, Tuple


class _FunctionRange(NamedTuple):
    """A function/class's real line range in the pre-patch source, plus its
    enclosing scope. start_line includes any decorators (their own lines
    are part of "this function changed" just as much as the def line
    itself), even though ast.FunctionDef.lineno alone points only at the
    def line.
    """
    name: str
    is_class: bool
    enclosing_class: Optional[str]
    enclosing_function: Optional[str]
    start_line: int
    end_line: int


def _function_ranges(source: str) -> List[_FunctionRange]:
    """Collect every function/class definition's real line range in source,
    recursively (including nested functions and methods), via ast.

    Returns:
        List of _FunctionRange, in no particular order. A name can appear
        more than once (same-named methods on different classes, or a
        name reused at different nesting levels) -- callers match by line
        number, not name, so this ambiguity is resolved by construction
        rather than needing to be disambiguated after the fact.
    """
    tree = ast.parse(source)
    ranges: List[_FunctionRange] = []

    def visit(node: ast.AST, enclosing_class: Optional[str], enclosing_function: Optional[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start_line = child.lineno
                if child.decorator_list:
                    start_line = min(start_line, child.decorator_list[0].lineno)
                ranges.append(_FunctionRange(
                    name=child.name, is_class=False,
                    enclosing_class=enclosing_class, enclosing_function=enclosing_function,
                    start_line=start_line, end_line=child.end_lineno,
                ))
                visit(child, enclosing_class=None, enclosing_function=child.name)
            elif isinstance(child, ast.ClassDef):
                start_line = child.lineno
                if child.decorator_list:
                    start_line = min(start_line, child.decorator_list[0].lineno)
                ranges.append(_FunctionRange(
                    name=child.name, is_class=True,
                    enclosing_class=enclosing_class, enclosing_function=enclosing_function,
                    start_line=start_line, end_line=child.end_lineno,
                ))
                visit(child, enclosing_class=child.name, enclosing_function=None)
            else:
                visit(child, enclosing_class, enclosing_function)

    visit(tree, enclosing_class=None, enclosing_function=None)
    return ranges


def _innermost_range(ranges: List[_FunctionRange], line: int) -> Optional[_FunctionRange]:
    """Return the smallest range containing line, or None if no range
    contains it (e.g. the line is a module-level statement, outside any
    function/class).
    """
    containing = [r for r in ranges if r.start_line <= line <= r.end_line]
    if not containing:
        return None
    return min(containing, key=lambda r: r.end_line - r.start_line)


def _changed_pre_patch_lines(patch: str, code_file: str) -> Set[int]:
    """Return the set of pre-patch line numbers, in code_file, that a
    changed line should be attributed against.

    A '-' (removed) line has its own real pre-patch line number, used
    directly. A '+' (added) line has no pre-patch line number of its own
    (it doesn't exist in the pre-patch file) -- its insertion POINT is used
    instead: the pre-patch line immediately after which it was inserted
    (old_lineno at the moment it's encountered, before advancing past any
    following context line). This correctly anchors a pure addition (no
    matching '-' line at all) to whichever function's range contains that
    insertion point.
    """
    changed_lines: Set[int] = set()
    current_file = None
    old_lineno = None

    for line in patch.split('\n'):
        if line.startswith('+++'):
            match = re.match(r'^\+\+\+ b/(.+)$', line)
            current_file = match.group(1) if match else None
            continue

        if current_file != code_file:
            continue

        if line.startswith('@@'):
            match = re.match(r'^@@ -(\d+)', line)
            old_lineno = int(match.group(1)) if match else None
            continue

        if old_lineno is None:
            continue

        if line.startswith('-') and not line.startswith('---'):
            changed_lines.add(old_lineno)
            old_lineno += 1
        elif line.startswith('+') and not line.startswith('+++'):
            # Anchor to the insertion point: both the pre-patch line just
            # before it and just after it, since either can be the one
            # actually inside the enclosing function's range (an addition
            # at the very first or very last line of a function's body
            # only has one real neighbor on the correct side).
            changed_lines.add(old_lineno)
            if old_lineno > 1:
                changed_lines.add(old_lineno - 1)
        elif line.startswith(' '):
            old_lineno += 1

    return changed_lines


class PatchParser:
    """Parse unified diffs to extract changed function/class names, using
    the pre-patch source's real AST rather than the diff text alone.
    """

    @staticmethod
    def extract_changed_functions(
        patch: str, code_file: str, pre_patch_source: str
    ) -> Set[str]:
        """Extract function and class names genuinely changed in code_file.

        Args:
            patch: Unified diff string (multi-file).
            code_file: Relative path to the file to extract changes from
                      (e.g. 'requests/sessions.py').
            pre_patch_source: code_file's actual text before the patch was
                              applied -- required to resolve real function/
                              class line ranges via ast (kg_construction#75).

        Returns:
            Set of function/class name strings genuinely changed in
            code_file. Bare names only -- callers needing to disambiguate a
            name that matches more than one class' method should use
            extract_changed_functions_with_scope instead.

        Raises:
            SyntaxError: If pre_patch_source doesn't parse. Raised directly
                         rather than silently falling back to a guess --
                         a wrong guess here is exactly the bug class this
                         AST-based approach replaces.
        """
        return {
            name for name, _class_name in PatchParser.extract_changed_functions_with_scope(
                patch, code_file, pre_patch_source
            )
        }

    @staticmethod
    def extract_changed_functions_with_scope(
        patch: str, code_file: str, pre_patch_source: str
    ) -> Set[Tuple[str, Optional[str]]]:
        """Same as extract_changed_functions, but also reports the
        enclosing class name for each changed method, when there is one.

        Each changed line's real pre-patch line number is looked up
        against every function/class's real ast-derived range, and
        attributed to the innermost (smallest) containing range -- so a
        change inside a method is attributed to that method, not its
        enclosing class, and a change inside a nested closure is
        attributed to the closure, not its enclosing function
        (kg_construction#74).

        Returns:
            Set of (name, enclosing_class_or_None) tuples. A changed
            nested function (not a class method) also has
            enclosing_class=None -- the enclosing SCOPE information is
            still real, just not a class; only kg_construction#63's
            same-class-method-name ambiguity needs the class hint, and a
            nested function can't collide with a class method that way.
        """
        ranges = _function_ranges(pre_patch_source)
        changed_lines = _changed_pre_patch_lines(patch, code_file)

        changed: Set[Tuple[str, Optional[str]]] = set()
        for line in changed_lines:
            match = _innermost_range(ranges, line)
            if match is None:
                continue  # module-level change, not inside any function/class
            changed.add((match.name, match.enclosing_class))

        return changed
