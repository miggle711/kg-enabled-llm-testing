"""
test_context_validator.py

Validate TestContext subgraphs for LLM test generation.

Runs after TestContextExtractor.extract() to ensure the subgraph is:
  ✓ Structurally valid (no orphans, no broken edges, closed graph)
  ✓ Semantically meaningful (seeds connected, test coverage, proper types)
  ✓ LLM-friendly (good density, diverse edges, documented)

Errors block use; warnings flag issues to monitor.
"""

from typing import Dict, List, Set, Tuple
from collections import defaultdict

from kg_construction.extraction.context import TestContext
from kg_construction.validation.base import ValidationBase


class TestContextValidator(ValidationBase):
    """Validate TestContext subgraphs for LLM test generation."""

    def __init__(self, context: TestContext):
        """
        Args:
            context: TestContext as returned by TestContextExtractor.extract().
        """
        super().__init__()
        self.context = context
        self.repo = context.repo
        self.base_commit = context.base_commit[:8]

        # Build lookup structures
        all_nodes = context.seeds + context.context_nodes
        self.all_nodes = all_nodes
        self.node_ids: Set[str] = {n['id'] for n in all_nodes}
        self.node_by_id: Dict[str, Dict] = {n['id']: n for n in all_nodes}
        self.node_types: Dict[str, str] = {n['id']: n['type'] for n in all_nodes}

        self.edges = context.edges
        self.edges_by_source: Dict[str, List[Dict]] = defaultdict(list)
        self.edges_by_target: Dict[str, List[Dict]] = defaultdict(list)
        self.edges_by_relation: Dict[str, List[Dict]] = defaultdict(list)

        for edge in self.edges:
            self.edges_by_source[edge['source']].append(edge)
            self.edges_by_target[edge['target']].append(edge)
            self.edges_by_relation[edge['relation']].append(edge)

    def validate(self) -> Tuple[bool, str]:
        """Run all validations and return (is_valid, report_string).

        Returns:
            (is_valid, report_string) where is_valid is True if no errors.
        """
        self.errors.clear()
        self.warnings.clear()

        # --- Must-haves (6) ---
        self._check_no_orphaned_nodes()
        self._check_no_broken_edges()
        self._check_seed_connectivity()
        self._check_closed_subgraph()
        self._check_no_duplicate_edges()
        self._check_no_ambiguous_seed_names()

        # --- Should-haves (3) ---
        self._check_test_coverage()
        self._check_seed_types()
        self._check_context_coverage()

        return self._format_report()

    # --- Must-haves ---

    def _check_no_orphaned_nodes(self) -> None:
        """Flag nodes with no incoming or outgoing edges.

        A node marked newly_created_file (kg_construction#93) is exempt --
        see _check_seed_connectivity for why zero edges is expected there.
        """
        orphaned = []
        for node_id in self.node_ids:
            node = self.node_by_id[node_id]
            if node['metadata'].get('newly_created_file'):
                continue
            has_edges = bool(
                self.edges_by_source.get(node_id) or
                self.edges_by_target.get(node_id)
            )
            if not has_edges:
                orphaned.append(f"{node['label']} ({node['type']})")

        if orphaned:
            self.errors.append(
                f"Orphaned nodes ({len(orphaned)}): {', '.join(orphaned[:3])}"
                f"{'...' if len(orphaned) > 3 else ''}"
            )

    def _check_no_broken_edges(self) -> None:
        """Flag edges where source or target is not in the subgraph.

        Shows the full node ID, not a truncated prefix. Truncation
        risks different nodes looking identical in a report.
        """
        broken = []
        for edge in self.edges:
            if edge['source'] not in self.node_ids or edge['target'] not in self.node_ids:
                broken.append(f"{edge['source']}...→{edge['target']}... ({edge['relation']})")

        if broken:
            self.errors.append(
                f"Broken edges ({len(broken)}): {', '.join(broken[:3])}"
                f"{'...' if len(broken) > 3 else ''}"
            )

    def _check_seed_connectivity(self) -> None:
        """Flag seeds with no edges in either direction (no context).

        Checks both outgoing and incoming edges, matching
        _check_no_orphaned_nodes below -- a seed with only incoming edges
        (callers) still has real, usable context: BFS already found it, and
        LLMSerializer's own callers section knows how to serialize it.
        Checking outgoing edges alone wrongly rejected leaf-like seeds
        whose own calls aren't resolvable (property access, external
        library calls) but that real callers elsewhere in the repo do
        reach (kg_construction#91; confirmed on a real matplotlib
        instance, _tick_only, which has 0 outgoing but 2 incoming edges
        and real BFS-found context).

        A seed marked newly_created_file (kg_construction#93) is exempt: the
        file the patch creates has no prior history in the repo, so nothing
        at base_commit could reference it -- zero edges there is the
        correct, expected answer, not a sign of a lookup bug.
        """
        disconnected = []
        seed_ids = {n['id'] for n in self.context.seeds}

        for seed_id in seed_ids:
            node = self.node_by_id[seed_id]
            if node['metadata'].get('newly_created_file'):
                continue
            has_edges = bool(
                self.edges_by_source.get(seed_id) or
                self.edges_by_target.get(seed_id)
            )
            if not has_edges:
                disconnected.append(node['label'])

        if disconnected:
            self.errors.append(
                f"Disconnected seeds ({len(disconnected)}): {', '.join(disconnected)}"
                " — no edges in either direction (no context)"
            )

    def _check_closed_subgraph(self) -> None:
        """Ensure all edge endpoints are in the node set.

        Shows the full node ID, same reasoning as _check_no_broken_edges.
        """
        dangling = set()
        for edge in self.edges:
            if edge['source'] not in self.node_ids:
                dangling.add(f"source {edge['source']}")
            if edge['target'] not in self.node_ids:
                dangling.add(f"target {edge['target']}")

        if dangling:
            self.errors.append(
                f"Dangling edges ({len(dangling)}): {', '.join(list(dangling)[:3])}"
            )

    def _check_no_duplicate_edges(self) -> None:
        """Flag duplicate edges (same source, target, relation)."""
        seen = set()
        duplicates = []

        for edge in self.edges:
            key = (edge['source'], edge['target'], edge['relation'])
            if key in seen:
                duplicates.append(f"{edge['relation']}")
            seen.add(key)

        if duplicates:
            self.errors.append(
                f"Duplicate edges ({len(duplicates)}): {', '.join(set(duplicates))}"
            )

    # --- Should-haves ---

    def _check_no_ambiguous_seed_names(self) -> None:
        """Flag when the same seed LABEL resolves to more than one distinct
        node -- e.g. two unrelated classes each defining their own
        'aclose' method, and a patch's changed-function detection finding
        the name 'aclose' with no way to tell which class's version it
        actually belongs to (kg_construction#63, found via a real
        encode/httpx patch to AsyncClient.aclose that also matched the
        unrelated BoundAsyncStream.aclose in the same file).

        This is an ERROR, not a warning: LLMSerializer._build_seed_section
        trusts seeds[0] unconditionally, so an unresolved name collision
        means the model may be shown a completely unrelated function's
        code as if it were the one the patch actually changed, depending
        on subgraph node ordering (BFS visited-order, confirmed
        non-deterministic across runs during kg_construction#54's
        investigation) -- not a lesser-severity issue than #54's
        test-file-as-seed defect, just a different trigger for the same
        failure shape.

        Distinct from a genuine multi-function patch (e.g.
        api_multi_verb_2012 changing patch/put/request/post together,
        which correctly produces multiple seeds with DIFFERENT labels):
        the signal here is specifically the same label resolving to more
        than one node, not "more than one seed" in general.

        A seed marked newly_created_file (kg_construction#93) is exempt:
        for a wholly new file, EVERY symbol in it genuinely is
        changed/new, so two different classes each having their own
        '__init__' isn't an unresolved collision the way #63 was -- #63's
        real bug was that only ONE of two same-named methods was actually
        changed by the patch, and seed resolution couldn't tell which;
        here, every seed is already correctly, individually resolved --
        there's no "which one is real" question to fail to answer.
        Confirmed on a real wholly-new-file instance
        (src/_pytest/mark/expression.py, pytest-dev/pytest) with several
        classes each defining their own '__init__'/'__str__'.
        """
        seen_ids_by_label: Dict[str, Set[str]] = defaultdict(set)
        for seed in self.context.seeds:
            if seed.get('metadata', {}).get('newly_created_file'):
                continue
            seen_ids_by_label[seed['label']].add(seed['id'])

        ambiguous = [
            label for label, ids in seen_ids_by_label.items() if len(ids) > 1
        ]

        if ambiguous:
            self.errors.append(
                f"Ambiguous seed names ({len(ambiguous)}): {', '.join(ambiguous[:3])}"
                " — this name matches more than one distinct function/method "
                "in this file; seed selection cannot tell them apart"
            )

    def _check_test_coverage(self) -> None:
        """Warn if code_file exists but test_file is missing."""
        if not self.context.test_nodes:
            self.warnings.append(
                "Test coverage: no test_nodes found — may indicate missing test file"
            )

    def _check_seed_types(self) -> None:
        """Warn if seeds are not functions/methods/classes."""
        bad_seeds = []
        for seed in self.context.seeds:
            if seed['type'] not in ('function', 'method', 'class', 'test_function'):
                bad_seeds.append(f"{seed['label']} ({seed['type']})")

        if bad_seeds:
            self.warnings.append(
                f"Seed types: {len(bad_seeds)} seed(s) are not function/class: "
                f"{', '.join(bad_seeds[:2])}"
            )

    def _check_context_coverage(self) -> None:
        """Warn if context is empty or very small."""
        if len(self.context.context_nodes) == 0:
            self.warnings.append(
                "Context coverage: no context nodes (only seeds) — very narrow view"
            )
        elif len(self.context.context_nodes) < 2:
            self.warnings.append(
                "Context coverage: only 1 context node — may be insufficient context"
            )

    def _format_report(self) -> Tuple[bool, str]:
        """Format validation report using base class formatter."""
        stats = (f"Seeds: {len(self.context.seeds)} | Context: {len(self.context.context_nodes)} "
                 f"| Edges: {len(self.edges)} | Tests: {len(self.context.test_nodes)}")
        return super()._format_report(
            title=f"TestContext Validation Report: {self.repo} @ {self.base_commit}",
            stats_line=stats,
        )
