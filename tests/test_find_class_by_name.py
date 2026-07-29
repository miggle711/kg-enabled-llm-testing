"""kg_construction#85: find_function_by_name only ever searches
function/method/test_function node types -- a changed CLASS itself (e.g. a
class-body attribute assignment, not inside any method) can never be found
by seed lookup, which silently falls through to the file-level fallback.
"""

from pathlib import Path

from kg_construction.kg.builder import RepoASTParser
from kg_construction.kg.query import KGQueryEngine


def _write_repo(tmp_path: Path) -> Path:
    (tmp_path / "mod.py").write_text(
        "class Widget:\n"
        "    template_name = 'widget.html'\n"
        "\n"
        "    def build(self):\n"
        "        return 1\n"
        "\n"
        "\n"
        "class Gadget:\n"
        "    pass\n"
    )
    return tmp_path


class TestFindClassByName:
    def test_finds_class_node_by_name(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)
        engine = KGQueryEngine(kg)

        results = engine.find_class_by_name("Widget")
        assert len(results) == 1
        assert results[0]["type"] == "class"
        assert results[0]["label"] == "Widget"

    def test_does_not_match_a_method_of_the_same_name(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)
        engine = KGQueryEngine(kg)

        assert engine.find_class_by_name("build") == []

    def test_no_match_returns_empty_list(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)
        engine = KGQueryEngine(kg)

        assert engine.find_class_by_name("DoesNotExist") == []
