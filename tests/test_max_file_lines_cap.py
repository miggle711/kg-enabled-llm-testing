"""Regression test for the MAX_FILE_LINES cap (raised 5000 -> 20000).

Confirmed via a 400-instance validation run against real TestGenEval data
that 5000 was excluding real, actively-maintained library source at a
measurable rate (2.5% of instances) -- e.g. sphinx/domains/cpp.py (7813
lines), matplotlib's lib/matplotlib/axes/_axes.py (8451 lines). ast.parse's
actual cost at these sizes is trivial (~37ms), so the cap exists as a
safety net against truly pathological files, not a realistic bound on real
hand-written modules.
"""

from pathlib import Path

from kg_construction.kg.builder import MAX_FILE_LINES, RepoASTParser


def _write_large_file(tmp_path: Path, num_functions: int) -> Path:
    """A synthetic file with many small functions, mimicking a real large
    module rather than one enormous function -- closer in shape to the
    real files (cpp.py, _axes.py) that motivated raising the cap.
    """
    lines = []
    for i in range(num_functions):
        lines.append(f"def function_{i}():\n    return {i}\n\n")
    (tmp_path / "big_module.py").write_text("".join(lines))
    return tmp_path


class TestMaxFileLinesCap:
    def test_file_between_old_and_new_cap_is_now_parsed(self, tmp_path):
        """A file with ~7800 lines (matching cpp.py's real size) used to be
        silently skipped under the old 5000-line cap -- must now be parsed.
        """
        repo_dir = _write_large_file(tmp_path, num_functions=2600)  # ~7800 lines
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        matches = [n for n in kg["nodes"] if n["label"] == "function_0"]
        assert len(matches) == 1
        # Confirm the whole file was actually parsed, not just the start.
        matches_last = [n for n in kg["nodes"] if n["label"] == "function_2599"]
        assert len(matches_last) == 1

    def test_cap_still_exists_for_pathological_files(self, tmp_path):
        """The cap isn't removed entirely -- a file well beyond the new
        cap must still be skipped.
        """
        repo_dir = _write_large_file(tmp_path, num_functions=(MAX_FILE_LINES // 3) + 100)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        file_nodes = [n for n in kg["nodes"] if n.get("type") == "file"]
        assert file_nodes == []
