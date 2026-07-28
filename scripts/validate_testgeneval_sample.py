"""
validate_testgeneval_sample.py

Ad-hoc validation of this repo's KG construction + context extraction
(RepoKGBuilder, PatchParser, extract_and_validate) against a sample of
real TestGenEvalLite instances, across all 11 source repos -- independent
of any hand-curated dataset, to check whether the pipeline holds up on
real, unfiltered patches it wasn't specifically built against.

Instances already run are tracked in HISTORY_PATH (committed to the repo)
and automatically excluded from future random samples, so repeated runs
expand real coverage instead of re-testing the same instances. Each run
merges its results into that history rather than overwriting it.

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
import sys
from collections import defaultdict
from pathlib import Path

HISTORY_PATH = Path(__file__).parent.parent / "data" / "testgeneval_validation_history.json"


def _load_history() -> dict:
    if not HISTORY_PATH.exists():
        return {}
    return json.loads(HISTORY_PATH.read_text())


def _save_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2, sort_keys=True))


def _load_sample(sample_size: int, seed: int, per_repo_cap: int, exclude: set) -> list:
    from datasets import load_dataset

    dataset = load_dataset("kjain14/testgenevallite")
    by_repo = defaultdict(list)
    for row in dataset["test"]:
        if row["instance_id"] in exclude:
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


def _load_specific(names: list) -> list:
    from datasets import load_dataset

    dataset = load_dataset("kjain14/testgenevallite")
    wanted = set(names)
    instances = [_to_instance(row) for row in dataset["test"] if row["instance_id"] in wanted]
    missing = wanted - {i["name"] for i in instances}
    if missing:
        print(f"WARNING: instance_ids not found in dataset: {sorted(missing)}", file=sys.stderr)
    return instances


def _to_instance(row: dict) -> dict:
    return {
        "name": row["instance_id"],
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
                         help="Comma-separated instance_ids to run instead of a random sample.")
    parser.add_argument("--allow-rerun", action="store_true",
                         help="Don't exclude previously-run instances when sampling. "
                              "Always applies when --instances is given explicitly.")
    parser.add_argument("--output", type=str, default="validation_results.json")
    args = parser.parse_args()

    from kg_construction.extraction.patch import PatchParser
    from kg_construction.kg.repo_manager import RepoManager
    from kg_construction.pipeline import extract_and_validate

    history = _load_history()
    print(f"Loaded history: {len(history)} instances previously run", flush=True)

    if args.instances:
        instances = _load_specific(args.instances.split(","))
    else:
        exclude = set() if args.allow_rerun else set(history)
        instances = _load_sample(args.sample_size, args.seed, args.per_repo_cap, exclude)

    print(f"Running {len(instances)} instances...", flush=True)

    repo_manager = RepoManager()
    results = {}
    for instance in instances:
        name = instance["name"]
        print(f"=== {name} ({instance['repo']}) ===", flush=True)

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
            results[name] = {
                "repo": instance["repo"], "stage": "resolve_target_function",
                "error": f"{type(e).__name__}: {e}",
            }
            print(f"  FAILED at resolve_target_function: {type(e).__name__}: {e}", flush=True)
            continue

        try:
            extract_and_validate(instance, depth=2, verbose=False, strict=True)
            results[name] = {"repo": instance["repo"], "stage": "ok", "target": target}
            print("  OK", flush=True)
        except Exception as e:
            results[name] = {
                "repo": instance["repo"], "stage": "extract_and_validate", "target": target,
                "error": f"{type(e).__name__}: {e}",
            }
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
