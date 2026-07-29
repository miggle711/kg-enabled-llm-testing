# `kg/builder.py` deep dive

A complete, top-to-bottom walkthrough of the KG construction module: every
constant, data shape, function, and how they chain together into one
`build()` call.

## Module layout

This file used to be one monolith; it's since split into three:
- **`ast/helpers.py`** -- pure, stateless AST-in/data-out functions (no I/O,
  no KG concepts). Things like `_get_signature`, `_get_exceptions`,
  `_build_func_metadata`. Re-imported and re-exported here so old code
  importing them *from* `builder.py` still works.
- **`kg/repo_manager.py`** -- `RepoManager`, all git/subprocess concerns
  (clone, archive, extract).
- **`kg/builder.py`** (this file) -- the actual KG-specific logic:
  node/edge data shapes, per-file parsing, the two-pass resolution driver,
  and the top-level `RepoKGBuilder` entry point.

## Module-level constants

**`SKIP_DIRS`** -- directories whose content is assumed non-source and
never parsed: `docs`, `doc`, `examples`, `example`, `vendor`, `.git`.

**`_GENERATED_MIGRATION_FILENAME`** -- a regex (`^\d{4}_`) matching
Django-style auto-generated migration filenames like `0001_initial.py`.
Exists as a narrower, file-level check specifically *because* a blanket
"skip any directory named `migrations`" rule was wrong (#70): Django's own
migration *framework* code (the hand-written logic that processes
migrations) lives at `django/db/migrations/`, a directory also literally
named `migrations` -- treating the whole directory as generated would
have wrongly excluded real source. So this only skips individual files
whose *name* matches the numeric-prefix convention, not the directory
wholesale.

**`MAX_FILE_LINES`** -- currently `20000`. Originally `5000`, raised after
a 400-instance validation run found real, actively-maintained files this
size being silently skipped (`sphinx/domains/cpp.py` at 7813 lines,
matplotlib's `_axes.py` at 8451) at ~2.5% prevalence -- and confirmed
`ast.parse`'s actual cost at this size is trivial (~37ms), so the original
"pathological parse times" concern didn't hold at these sizes. The cap
still exists as a backstop against genuinely pathological (e.g.
megabyte-scale generated) files.

**`SCHEMA_VERSION`** -- bumped whenever the KG's node/edge shape changes.
Every build stamps this into its own metadata, and `load()` checks it --
so a KG cached under an old schema is treated as a cache miss and
rebuilt, rather than silently served in a shape current code doesn't
expect.

## `KGNode` / `KGEdge` -- the two data shapes

Both are plain `@dataclass`es, converted to dicts via `asdict()` everywhere
they're constructed -- this is what makes the final KG trivially
JSON-serializable.

**`KGNode`**: `id` (deterministic MD5-derived hash of the entity's
qualified name -- same entity across different commits/instances maps to
the same ID), `type` (`file`/`test_file`/`class`/`function`/`method`/
`test_function`/`import`), `label` (human name), `metadata` (a free-form
dict, shape varies per node type).

**`KGEdge`**: `source`, `target` (node IDs, or bare name strings before
resolution), `relation` (`contains`/`imports`/`calls`/`accesses`/
`inherits`/`uses`/`overrides`/`depends_on`/`tests`/`module_depends_on`),
`metadata` (carries `confidence` after resolution -- `qualified`/`exact`/
`ambiguous` -- plus resolution hints before that).

## `_parse_file` -- per-file parsing (runs in a worker process)

Reads one file, `ast.parse`s it (skipping if unreadable, over
`MAX_FILE_LINES`, or a `SyntaxError` -- silently, no node emitted at all),
and walks its **top-level** statements only (`ast.iter_child_nodes(tree)`,
not `ast.walk`).

For each class: emits the class node (bases, decorators, docstring, class
attributes), unresolved `inherits` edges (one per base) and `uses` edges
(one per class instantiated in any of its methods), then walks its
methods -- each emitted as its own node with a `contains` edge from the
class, guessed `overrides` edges (one per base class, confirmed or
discarded in pass 2), and calls into three closures:

- **`_emit_call_edges`**: walks the function body for every `ast.Call`,
  emits one unresolved `calls` edge per unique callee name, with
  priority-ordered resolution hints computed right here while the AST and
  local context are still in hand: `class_hint` (from `self.method()`),
  `local_type_hint` (from `x.method()` where `x`'s type was inferred
  locally), `import_resolved` (from an imported name, module-qualified or
  bare). Special-cases `super().method()` (`is_super_call`, deferred to a
  dedicated pass 2 step rather than ever falling back to bare-name
  matching -- #61 found that guessing here linked `ErrorList.copy()` to an
  unrelated class's `copy()`).
- **`_emit_access_edges`**: same idea for `@property` reads (`obj.attr`,
  no parentheses) -- these never show up as `ast.Call` nodes, so they need
  separate AST detection (`_extract_property_accesses`).
- **`_emit_func_edges`**: two more edge types -- `depends_on` (imports
  actually referenced in the function body, resolved immediately since
  import node IDs are already known) and `tests` (a self-referential
  placeholder edge for any `test_*` function, resolved in pass 2 by
  stripping the `test_` prefix and matching the target name).

For each top-level function (not inside a class): same treatment, minus
the class-specific parts (no bases, no `overrides` guesses).

Nested functions/closures inside either are found via
`_emit_nested_functions`'s own recursion -- Python's real lexical scoping
means a closure is never a *direct* child of the module, so it's only
discovered by recursing into whatever encloses it. This is #74's fix:
previously closures had no KG node at all, so a patch whose changed
function was a nested closure had nothing to seed from.

Every `calls`/`accesses` edge, even though unresolved at this point,
carries those hints -- this is what makes cross-file resolution possible
later without re-walking any AST. A single file genuinely cannot resolve
a call target itself; it has zero visibility into any other file.

`_record_factory_sites` is a narrower, optional enrichment: records
assignment sites like `self.x = SomeFactory()` so an optional later
pyright pass (`type_inference.py`) can try to resolve what the factory
call actually returns, for cases the plain AST heuristics can't infer.

## `RepoASTParser.parse_repo` -- the orchestrator

Runs sequentially after all files' `_parse_file` calls finish (via
`ProcessPoolExecutor`):

1. **`_aggregate_and_index`** merges every file's nodes into one list
   (deduped by ID) and builds five name -> ID lookup tables:
   `label_to_ids` (bare name across the whole repo), `class_label_to_ids`,
   `class_method_to_ids` (the precise `(class, method)` lookup),
   `qualified_to_ids` (fully dotted module path), and a derived
   `property_method_to_ids` (filtered to `@property`-decorated methods
   only, so `accesses` resolution can't mismatch a property read against
   a same-named plain method).

2. **`_resolve_edges`** walks every unresolved edge and, using the hints
   from step 1, resolves it against those indices -- tagging confidence
   `qualified` > `exact` > `ambiguous`, or dropping it outright if nothing
   trustworthy matches. Deliberately biased toward dropping over guessing:
   two real historical bugs motivated this --
   - **#61**: `super()` calls misattributed via bare-name fallback.
   - **#65**: bare-name calls (no receiver, e.g. `request(...)`) fanning
     out to every same-named candidate in the repo was wrong 80-93% of the
     time on real repos (`psf/requests`, `django/django`). Fixed with a
     same-file preference for a bare call with multiple candidates (a real,
     principled Python scoping rule, not a guess -- confirmed necessary on
     a real case where `api.py`'s `post()` calls bare `request(...)`,
     meaning its own module-level `request()`, not an unrelated same-named
     method elsewhere).

   Two categories are deferred to dedicated passes *after* the main loop,
   since they need the fully-resolved `inherits` graph first:
   - **`_resolve_overrides`**: walks the transitive ancestor chain to find
     which ancestor genuinely defines a same-named method, matching real
     Python MRO semantics -- correctly skips an intermediate class that
     doesn't itself define the method.
   - **`_resolve_super_calls`**: resolves `super().method()` against the
     caller's own now-resolved inheritance chain, never falling back to a
     risky bare-name guess.

   A third derived pass, **`_derive_tests_edges_from_calls`**, re-tags any
   resolved `calls` edge whose source is a `test_function` node as *also*
   a `tests` edge. Added because a real audit (#57) found the
   naming-convention approach (`test_foo` -> `foo`) only held for 1 of 159
   real test functions in `psf/requests` -- most tests use descriptive
   names with no derivable link to what they test. A calls-based signal
   (a test that genuinely calls the function it's testing) is a far
   stronger, naming-independent proxy.

3. **`module_depends_on`** edges are added last, at the file level:
   matching each `import` node's module path against real file paths in
   the repo (trying progressively shorter path suffixes, so identically
   -named files in different packages don't collide), producing a coarse
   file-to-file dependency graph layered on top of the function-level one.

4. **`_add_call_context`** annotates every function/method/test_function
   node's own metadata with `caller_count` and `direct_callers`, derived
   from the now-fully-resolved `calls` edges -- a convenience so a
   consumer can see "who calls this" without a separate graph query.

## `RepoKGBuilder` -- the top-level entry point

Orchestrates `RepoManager` (git operations) and `RepoASTParser` (parsing)
into one call:

- **`build(repo, commit)`** -- extracts the source tree into a
  `tempfile.TemporaryDirectory` (auto-cleaned), calls `parse_repo`, stamps
  `base_commit` and `schema_version` into the result's metadata.
- **`build_from_dir(repo_name, local_path)`** -- a thin alternate entry
  point for a plain local directory, no git/commit involved at all:
  `parse_repo` never actually needed anything git-specific, just a
  directory of `.py` files, so this reuses it directly. Its `base_commit`
  is stamped `None`, since there's no single commit a working-tree
  snapshot corresponds to.
- **`save`/`load`** -- persist to/from
  `kg_output/kg_{repo}_{commit[:8]}.json`, keyed on `(repo, commit)` so a
  KG built at one commit is never silently served for a different commit
  of the same repo (#45). `load` returns `None` (never raises) on any
  kind of miss -- missing file, commit mismatch, or stale
  `schema_version` -- so callers always get a clean "build fresh" signal.
- **`save_local`/`load_local`** -- a separate, uncommitted cache path
  (`kg_output/kg_local_{repo_name}.json`) for `build_from_dir` results,
  deliberately kept apart from the commit-keyed cache: a local build has
  no real commit to key on, and can go stale the instant the working tree
  changes again, so it must never risk being confused with -- or silently
  served in place of -- a real commit-pinned build. `save()` itself
  raises if handed a `build_from_dir()` result (no `base_commit`), rather
  than silently deriving a malformed cache filename.
