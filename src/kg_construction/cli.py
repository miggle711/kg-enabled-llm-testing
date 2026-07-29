"""
cli.py

Scriptable, non-interactive command-line interface (kg_construction#83).

    pkg-run build psf/requests --commit a0df2cbb     # clone-by-SHA (existing path)
    pkg-run build . --name my-local-repo             # local working tree, no git
    pkg-run query kg_output/kg_x.json --callers send
    pkg-run query kg_output/kg_x.json --callees send
    pkg-run query kg_output/kg_x.json --file sessions.py

Every query subcommand prints a human-readable listing by default;
pass --json for the raw dict, for scripting/piping.

Running `pkg-run` with no arguments falls back to the pre-existing
interactive wizard (kg_construction.pipeline._interactive_mode) --
nothing that already depends on that entry point breaks.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from kg_construction.kg.builder import RepoKGBuilder
from kg_construction.kg.query import KGQueryEngine


def _print_or_json(data, as_json: bool, human_fn) -> None:
    if as_json:
        print(json.dumps(data, indent=2))
    else:
        human_fn(data)


def _cmd_build(args: argparse.Namespace) -> int:
    builder = RepoKGBuilder(max_workers=args.max_workers)

    if args.commit:
        kg = builder.build(args.repo, args.commit)
        builder.save(args.repo, kg)
    else:
        name = args.name or args.repo
        print(f"Building local KG for '{name}' from {args.repo}...")
        kg = builder.build_from_dir(name, Path(args.repo))
        builder.save_local(name, kg)

    return 0


def _load_engine(kg_path: str) -> KGQueryEngine:
    with open(kg_path) as f:
        kg = json.load(f)
    return KGQueryEngine(kg)


def _fmt_func(node: Dict) -> str:
    meta = node.get('metadata', {})
    filepath = meta.get('filepath', meta.get('path', '?'))
    lineno = meta.get('lineno', '?')
    cls = meta.get('class')
    label = f"{cls}.{node['label']}" if cls else node['label']
    return f"{filepath}:{lineno} -- {label} ({node['type']})"


def _resolve_function(engine: KGQueryEngine, name: str) -> Optional[Dict]:
    matches = engine.find_function_by_name(name)
    if not matches:
        print(f"No function/method named '{name}' found in this KG.", file=sys.stderr)
        return None
    if len(matches) > 1:
        print(f"'{name}' is ambiguous ({len(matches)} matches); using the first:", file=sys.stderr)
        for m in matches:
            print(f"  {_fmt_func(m)}", file=sys.stderr)
    return matches[0]


def _cmd_query(args: argparse.Namespace) -> int:
    engine = _load_engine(args.kg_file)

    if args.callers:
        node = _resolve_function(engine, args.callers)
        if node is None:
            return 1
        results = engine.find_callers(node['id'])
        _print_or_json(
            results, args.json,
            lambda data: print(f"Callers of {args.callers}:\n" + "\n".join(
                f"  {_fmt_func(n)}" for n in data
            ) if data else f"No callers found for {args.callers}.")
        )
        return 0

    if args.callees:
        node = _resolve_function(engine, args.callees)
        if node is None:
            return 1
        results = engine.find_callees(node['id'])
        _print_or_json(
            results, args.json,
            lambda data: print(f"Callees of {args.callees}:\n" + "\n".join(
                f"  {_fmt_func(n)}" for n in data
            ) if data else f"No callees found for {args.callees}.")
        )
        return 0

    if args.file:
        file_matches = engine.find_file_by_path(args.file)
        if not file_matches:
            print(f"No file matching '{args.file}' found in this KG.", file=sys.stderr)
            return 1
        if len(file_matches) > 1:
            print(f"'{args.file}' is ambiguous ({len(file_matches)} matches); using the first:", file=sys.stderr)
            for m in file_matches:
                print(f"  {m['metadata'].get('path')}", file=sys.stderr)
        contents = engine.get_file_contents(file_matches[0]['id'])
        _print_or_json(contents, args.json, _print_file_contents)
        return 0

    print("Specify one of --callers, --callees, --file.", file=sys.stderr)
    return 1


def _print_file_contents(contents: Dict) -> None:
    file_node = contents.get('file', {})
    print(f"{file_node.get('metadata', {}).get('path', '?')}")
    for cls in contents.get('classes', []):
        print(f"  class {cls['label']} (line {cls['metadata'].get('lineno', '?')})")
    for fn in contents.get('functions', []):
        print(f"  {_fmt_func(fn)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='pkg-run', description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest='command')

    build_p = subparsers.add_parser('build', help='Build a KG for a repo or local directory')
    build_p.add_argument('repo', help="'owner/name' for a GitHub repo, or a local directory path")
    build_p.add_argument('--commit', help='Commit SHA (clone-by-SHA path). Omit for a local directory.')
    build_p.add_argument('--name', help='Label for a local build (defaults to the directory path)')
    build_p.add_argument('--max-workers', type=int, default=4)
    build_p.set_defaults(func=_cmd_build)

    query_p = subparsers.add_parser('query', help='Query an already-built KG JSON file')
    query_p.add_argument('kg_file', help='Path to a KG JSON file (from build --commit or build_from_dir)')
    query_p.add_argument('--callers', metavar='FUNC_NAME', help='List callers of a function/method')
    query_p.add_argument('--callees', metavar='FUNC_NAME', help='List callees of a function/method')
    query_p.add_argument('--file', metavar='PATH', help='List classes/functions defined in a file')
    query_p.add_argument('--json', action='store_true', help='Print raw JSON instead of a human-readable listing')
    query_p.set_defaults(func=_cmd_query)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None:
        from kg_construction.pipeline import _interactive_mode
        _interactive_mode()
        return 0

    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
