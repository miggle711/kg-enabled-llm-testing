"""
validate_testgeneval_sample.py

Ad-hoc validation of this repo's KG construction + context extraction
(RepoKGBuilder, PatchParser, extract_and_validate) against a sample of
real TestGenEval instances, across all 11 source repos -- independent of
any hand-curated dataset, to check whether the pipeline holds up on real,
unfiltered patches it wasn't specifically built against.

Defaults to TestGenEvalLite (160 instances); pass --dataset
kjain14/testgeneval for the full 1,210-instance benchmark. Lite's rows are
a strict subset of the full dataset's, so history entries are valid
exclusions against either.

Tracked/sampled by each row's unique 'id' field (e.g.
'sphinx-doc__sphinx-9155-17043'), NOT 'instance_id' -- the full dataset
has 45 instance_ids that each correspond to more than one row (same
SWE-bench instance, different code_file per row); using instance_id alone
previously caused a real mix-up (a c.py-targeting row's result reported
errors about cpp.py, from the OTHER row sharing that instance_id).

Instances already run are tracked in HISTORY_PATH (committed to the repo)
and automatically excluded from future random samples, so repeated runs
expand real coverage instead of re-testing the same instances. Each run
merges its results into that history rather than overwriting it.

Each stored result is stamped with the commit this script's own repo
checkout was at, and a UTC timestamp -- a stored failure's error text can
otherwise go stale silently once the underlying bug is fixed (e.g. #72's
clone-recovery fix made several historical astropy entries read like a
still-live bug when they weren't).

Usage:
    python scripts/validate_testgeneval_sample.py --sample-size 50 --seed 42
    python scripts/validate_testgeneval_sample.py --instances a,b,c   # specific instance_ids
    python scripts/validate_testgeneval_sample.py --sample-size 50 --allow-rerun  # ignore history

Writes:
    validation_results.json -- this run's results only, for CI artifact upload
    data/testgeneval_validation_history.json -- cumulative, merged across all runs
"""

import argparse
import json
import random
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HISTORY_PATH = Path(__file__).parent.parent / "data" / "testgeneval_validation_history.json"


def _current_commit() -> str:
    """The commit this script's OWN repo checkout is at -- stamped onto
    every result so a stored failure can be told apart from one that
    predates a since-landed fix (e.g. the #72 clone-recovery fix made
    several historical astropy entries stale) instead of being silently
    trusted as still-current.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
            capture_output=True, text=True, timeout=10, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    return json.loads(HISTORY_PATH.read_text())


def _save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True))


def _load_sample(sample_size: int, seed: int, per_repo_cap: int, exclude: set, dataset_name: str) -> list:
    from datasets import load_dataset

    dataset = load_dataset(dataset_name)
    by_repo = defaultdict(list)
    for row in dataset["test"]:
        if row["id"] in exclude:
            continue
        by_repo[row["repo"]].append(row)

    rng = random.Random(seed)
    sample = []
    for repo, rows in by_repo.items():
        rows = list(rows)
        rng.shuffle(rows)
        sample.extend(rows[:per_repo_cap])

    rng.shuffle(sample)
    sample = sample[:sample_size]

    return [_to_instance(row) for row in sample]


def _load_specific(names: list, dataset_name: str) -> list:
    """Load specific rows by their unique 'id' field (e.g.
    'sphinx-doc__sphinx-9155-17043') -- NOT 'instance_id' alone, which is
    NOT unique in the full kjain14/testgeneval dataset: 45 instance_ids
    there each correspond to more than one row (the same SWE-bench
    instance touching more than one code_file, one row per file). Using
    'instance_id' here would non-deterministically pick one of several
    real, distinct rows.
    """
    from datasets import load_dataset

    dataset = load_dataset(dataset_name)
    wanted = set(names)
    instances = [_to_instance(row) for row in dataset["test"] if row["id"] in wanted]
    missing = wanted - {i["name"] for i in instances}
    if missing:
        print(f"WARNING: ids not found in dataset: {sorted(missing)}", file=sys.stderr)
    return instances


def _to_instance(row: dict) -> dict:
    return {
        # 'id' (e.g. 'sphinx-doc__sphinx-9155-17043') is unique per row in
        # BOTH kjain14/testgeneval and kjain14/testgenevallite. 'instance_id'
        # alone is NOT unique in the full dataset -- 45 instance_ids there
        # each have more than one row (same SWE-bench instance, different
        # code_file per row). Using 'instance_id' as the tracking key
        # caused a real bug: two rows sharing instance_id
        # 'sphinx-doc__sphinx-9155' (code_file 'c.py' vs 'cpp.py') were
        # indistinguishable in history/sampling, and dataset iteration
        # order picked whichever row happened to match first.
        "name": row["id"],
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "patch": row["patch"],
        "code_file": row["code_file"],
        "test_file": row["test_file"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-repo-cap", type=int, default=12,
                         help="Max instances taken from any single repo, for a spread sample.")
    parser.add_argument("--instances", type=str, default=None,
                         help="Comma-separated row ids (the dataset's 'id' field, e.g. "
                              "'sphinx-doc__sphinx-9155-17043') to run instead of a random "
                              "sample. NOT instance_id -- see module docstring for why.")
    parser.add_argument("--allow-rerun", action="store_true",
                         help="Don't exclude previously-run instances when sampling. "
                              "Always applies when --instances is given explicitly.")
    parser.add_argument("--dataset", type=str, default="kjain14/testgenevallite",
                         help="HuggingFace dataset to sample from. TestGenEvalLite's "
                              "160 instance_ids are a strict subset of the full "
                              "kjain14/testgeneval (1,210) -- history entries from one "
                              "are valid exclusions against the other.")
    parser.add_argument("--output", type=str, default="validation_results.json")
    args = parser.parse_args()

    from kg_construction.extraction.patch import PatchParser
    from kg_construction.kg.repo_manager import RepoManager
    from kg_construction.pipeline import extract_and_validate

    history = _load_history()
    print(f"Loaded history: {len(history)} instances previously run", flush=True)

    if args.instances:
        instances = _load_specific(args.instances.split(","), args.dataset)
    else:
        exclude = set() if args.allow_rerun else set(history)
        instances = _load_sample(args.sample_size, args.seed, args.per_repo_cap, exclude, args.dataset)

    print(f"Running {len(instances)} instances...", flush=True)

    commit = _current_commit()
    run_at = datetime.now(timezone.utc).isoformat()
    print(f"Stamping results with commit={commit[:8]} run_at={run_at}", flush=True)

    repo_manager = RepoManager()
    results = {}
    for instance in instances:
        name = instance["name"]
        print(f"=== {name} ({instance['repo']}) [{instance['code_file']}] ===", flush=True)
        entry = {
            "repo": instance["repo"],
            "instance_id": instance["instance_id"],
            "code_file": instance["code_file"],
            "commit": commit,
            "run_at": run_at,
        }

        try:
            pre_patch_source = repo_manager.read_file_at_commit(
                instance["repo"], instance["base_commit"], instance["code_file"]
            )
            changed_names = PatchParser.extract_changed_functions(
                instance["patch"], instance["code_file"], pre_patch_source
            )
            if not changed_names:
                raise ValueError(
                    f"No changed function found in {instance['code_file']} for this patch"
                )
            target = sorted(changed_names)[0]
            print(f"  resolved target: {target}", flush=True)
        except Exception as e:
            entry.update(stage="resolve_target_function", error=f"{type(e).__name__}: {e}")
            results[name] = entry
            print(f"  FAILED at resolve_target_function: {type(e).__name__}: {e}", flush=True)
            continue

        try:
            extract_and_validate(instance, depth=2, verbose=False, strict=True)
            entry.update(stage="ok", target=target)
            results[name] = entry
            print("  OK", flush=True)
        except Exception as e:
            entry.update(stage="extract_and_validate", target=target, error=f"{type(e).__name__}: {e}")
            results[name] = entry
            print(f"  FAILED at extract_and_validate: {type(e).__name__}: {e}", flush=True)

    Path(args.output).write_text(json.dumps(results, indent=2))

    history.update(results)
    _save_history(history)
    print(f"\nHistory updated: {len(history)} total instances tracked", flush=True)

    print()
    print("=== SUMMARY ===")
    ok = sum(1 for r in results.values() if r["stage"] == "ok")
    print(f"{ok}/{len(results)} succeeded")
    for name, r in results.items():
        if r["stage"] != "ok":
            print(f"  FAIL [{r['stage']}] {name}: {r['error']}")


if __name__ == "__main__":
    main()
