# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - Unreleased

First versioned snapshot. Prior development history (structural KG
construction, patch parsing, subgraph extraction, validation) predates
this changelog and isn't reconstructed retroactively -- see `git log` for
the full commit history.

### Added
- `pkg-run` CLI: `build` (clone-by-commit or local-directory mode) and
  `query` (`--callers`, `--callees`, `--file`, `--json`) subcommands.
  Falls back to the pre-existing interactive wizard when run with no
  arguments.
- `RepoKGBuilder.build_from_dir`: build a KG from a local directory with
  no git/commit dependency, for a working tree including uncommitted
  changes.
- Package metadata for PyPI distribution (description, license, classifiers,
  project URLs).

### Fixed
- Seed lookup could never resolve a changed CLASS itself (only
  functions/methods) -- a class-body-level change silently fell back to
  seeding the whole file.
- Seed connectivity validation only checked outgoing edges, wrongly
  rejecting seeds with real incoming (caller) context.
- A file created by the patch itself (no pre-patch version to fetch)
  raised outright instead of resolving against the reconstructed
  post-patch source.
- `MAX_FILE_LINES` cap (was 5000) was silently excluding real,
  actively-maintained files at ~2.5% prevalence in real-world repos;
  raised to 20000 after confirming `ast.parse` cost at that size is
  trivial.
