"""Regression test for kg_construction#70: SKIP_DIRS previously excluded
ANY path containing a 'migrations' directory, including Django's own
hand-written migration framework code (django/db/migrations/), not just
auto-generated app migration files (e.g. myapp/migrations/0001_initial.py).

Confirmed via a real audit across 12 repos: the only false positive is
Django's own django/db/migrations/ -- every other 'migrations' directory
sampled (Django's contrib apps' own migrations, etc.) is genuinely
auto-generated, numeric-prefixed files. The fix targets that distinction
directly: skip a file inside a 'migrations' directory only if its own
name matches the generated-migration naming convention.
"""

from pathlib import Path

from kg_construction.kg.builder import RepoASTParser


def _write_repo(tmp_path: Path) -> Path:
    # Hand-written migration FRAMEWORK code, at a path shaped like Django's
    # own django/db/migrations/ -- must be parsed, not skipped.
    framework_dir = tmp_path / "db" / "migrations"
    framework_dir.mkdir(parents=True)
    (framework_dir / "__init__.py").write_text("")
    (framework_dir / "serializer.py").write_text(
        "def serialize(value):\n    return str(value)\n"
    )

    # Auto-generated APP migration files -- must still be skipped.
    app_dir = tmp_path / "myapp" / "migrations"
    app_dir.mkdir(parents=True)
    (app_dir / "__init__.py").write_text("")
    (app_dir / "0001_initial.py").write_text(
        "def apply():\n    pass\n"
    )
    (app_dir / "0002_add_field.py").write_text(
        "def apply():\n    pass\n"
    )

    return tmp_path


class TestMigrationsSkipDirFalsePositive:
    def test_hand_written_migration_framework_file_is_parsed(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        matches = [n for n in kg["nodes"] if n["label"] == "serialize"]
        assert len(matches) == 1
        assert matches[0]["metadata"]["filepath"] == "db/migrations/serializer.py"

    def test_generated_migration_files_are_still_skipped(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        file_paths = {
            n["metadata"].get("path")
            for n in kg["nodes"] if n["type"] == "file"
        }
        assert "myapp/migrations/0001_initial.py" not in file_paths
        assert "myapp/migrations/0002_add_field.py" not in file_paths

    def test_generated_migration_functions_are_not_in_the_kg(self, tmp_path):
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        # 'apply' only exists inside the two skipped generated files.
        matches = [n for n in kg["nodes"] if n["label"] == "apply"]
        assert matches == []

    def test_non_numeric_prefixed_files_in_any_migrations_dir_are_parsed(self, tmp_path):
        """The fix targets FILENAME shape (numeric-prefixed), not which
        migrations/ directory a file lives in -- an __init__.py is parsed
        the same way regardless of whether its migrations/ dir is a real
        framework package or a generated-migrations package. Only files
        that actually look generated (numeric-prefixed) are skipped.
        """
        repo_dir = _write_repo(tmp_path)
        parser = RepoASTParser(max_workers=1)
        kg = parser.parse_repo("test/repo", repo_dir)

        file_paths = {
            n["metadata"].get("path")
            for n in kg["nodes"] if n["type"] == "file"
        }
        assert "db/migrations/__init__.py" in file_paths
        assert "myapp/migrations/__init__.py" in file_paths
