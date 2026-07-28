"""Regression tests for nested function/closure extraction (kg_construction#74).

Nested function definitions (closures inside another function's body) were
never extracted as KG nodes at all -- any patch whose changed function was a
nested closure had no matching node to seed context from. Confirmed on a
real sphinx-doc/sphinx patch (keyfunc, a sort-key closure inside
create_index): the patch touches keyfunc, but the KG had zero nodes labeled
keyfunc, so seed selection silently fell back to the containing file.
"""

from pathlib import Path

from kg_construction.kg.builder import RepoASTParser


def _write_repo(tmp_path: Path) -> Path:
    (tmp_path / "mod.py").write_text(
        "def outer(items):\n"
        "    def keyfunc(entry):\n"
        "        return entry[0]\n"
        "    return sorted(items, key=keyfunc)\n"
        "\n"
        "\n"
        "class Widget:\n"
        "    def build(self, items):\n"
        "        def sort_key(entry):\n"
        "            return entry[1]\n"
        "        return sorted(items, key=sort_key)\n"
    )
    return tmp_path


class TestNestedFunctionExtraction:
    def test_nested_function_becomes_its_own_node(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        matches = [n for n in kg["nodes"] if n["label"] == "keyfunc"]
        assert len(matches) == 1
        assert matches[0]["type"] == "function"
        assert matches[0]["metadata"].get("parent_function") == "outer"

    def test_nested_function_inside_a_method_also_extracted(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        matches = [n for n in kg["nodes"] if n["label"] == "sort_key"]
        assert len(matches) == 1
        assert matches[0]["metadata"].get("parent_function") == "build"

    def test_nested_function_has_contains_edge_from_enclosing_function(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        outer_id = next(n["id"] for n in kg["nodes"] if n["label"] == "outer")
        keyfunc_id = next(n["id"] for n in kg["nodes"] if n["label"] == "keyfunc")

        assert any(
            e["relation"] == "contains" and e["source"] == outer_id and e["target"] == keyfunc_id
            for e in kg["edges"]
        )

    def test_doubly_nested_function_is_also_extracted(self, tmp_path):
        (tmp_path / "mod.py").write_text(
            "def outer():\n"
            "    def middle():\n"
            "        def inner():\n"
            "            return 1\n"
            "        return inner()\n"
            "    return middle()\n"
        )
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", tmp_path)

        labels = {n["label"] for n in kg["nodes"] if n["type"] == "function"}
        assert {"outer", "middle", "inner"} <= labels

        middle_id = next(n["id"] for n in kg["nodes"] if n["label"] == "middle")
        inner = next(n for n in kg["nodes"] if n["label"] == "inner")
        assert inner["metadata"].get("parent_function") == "middle"
        assert any(
            e["relation"] == "contains" and e["source"] == middle_id and e["target"] == inner["id"]
            for e in kg["edges"]
        )

    def test_top_level_function_metadata_has_no_parent_function(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        outer = next(n for n in kg["nodes"] if n["label"] == "outer")
        assert "parent_function" not in outer["metadata"]
