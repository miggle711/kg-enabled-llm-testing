"""Smoke tests for validators."""

import pytest
from kg_construction.kg.validator import KGValidator
from kg_construction.extraction.validator import TestContextValidator
from kg_construction.extraction.context import TestContext


class TestKGValidator:
    """Test KGValidator for knowledge graphs."""

    @pytest.fixture
    def valid_kg(self):
        """Create a valid minimal KG."""
        return {
            'nodes': [
                {'id': 'n1', 'label': 'func_a', 'type': 'function', 'metadata': {'filepath': 'a.py'}},
                {'id': 'n2', 'label': 'func_b', 'type': 'function', 'metadata': {'filepath': 'b.py'}},
            ],
            'edges': [
                {'source': 'n1', 'target': 'n2', 'relation': 'calls'},
            ],
            'metadata': {'repo': 'test/repo', 'commit': 'abc123'},
        }

    @pytest.fixture
    def kg_with_orphans(self):
        """Create KG with orphaned nodes."""
        return {
            'nodes': [
                {'id': 'n1', 'label': 'func_a', 'type': 'function', 'metadata': {'filepath': 'a.py'}},
                {'id': 'n2', 'label': 'func_b', 'type': 'function', 'metadata': {'filepath': 'b.py'}},
                {'id': 'n3', 'label': 'func_c', 'type': 'function', 'metadata': {'filepath': 'c.py'}},
            ],
            'edges': [
                {'source': 'n1', 'target': 'n2', 'relation': 'calls'},
            ],
            'metadata': {'repo': 'test/repo'},
        }

    def test_validate_valid_kg(self, valid_kg):
        """Validate a valid KG."""
        validator = KGValidator(valid_kg)
        is_valid, report = validator.validate()
        assert is_valid is True
        assert '✅' in report or 'passed' in report.lower()

    def test_validate_kg_with_orphans(self, kg_with_orphans):
        """Detect orphaned nodes."""
        validator = KGValidator(kg_with_orphans)
        is_valid, report = validator.validate()
        assert is_valid is False
        assert 'Orphaned' in report or 'orphan' in report.lower()

    def test_validate_self_loops(self):
        """Detect self-loops (non-recursive calls)."""
        kg = {
            'nodes': [
                {'id': 'n1', 'label': 'func_a', 'type': 'function', 'metadata': {'filepath': 'a.py'}},
            ],
            'edges': [
                {'source': 'n1', 'target': 'n1', 'relation': 'uses'},
            ],
            'metadata': {'repo': 'test/repo'},
        }
        validator = KGValidator(kg)
        is_valid, report = validator.validate()
        # Self-loop with non-'calls' relation should warn
        assert 'Self-loops' in report or 'self-loop' in report.lower()

    def test_report_includes_stats(self, valid_kg):
        """Report includes node/edge statistics."""
        validator = KGValidator(valid_kg)
        is_valid, report = validator.validate()
        assert 'Nodes:' in report or 'nodes' in report.lower()
        assert 'Edges:' in report or 'edges' in report.lower()


class TestTestContextValidator:
    """Test TestContextValidator for subgraph validation."""

    @pytest.fixture
    def valid_context(self):
        """Create a valid TestContext."""
        return TestContext(
            seeds=[
                {'id': 's1', 'label': 'send', 'type': 'method', 'metadata': {'filepath': 'session.py'}},
            ],
            context_nodes=[
                {'id': 'c1', 'label': 'request', 'type': 'function', 'metadata': {'filepath': 'session.py'}},
            ],
            edges=[
                {'source': 's1', 'target': 'c1', 'relation': 'calls'},
            ],
            test_nodes=[
                {'id': 't1', 'label': 'test_send', 'type': 'test_function', 'metadata': {'filepath': 'test_session.py'}},
            ],
            repo='test/repo',
            base_commit='abc123def456',
        )

    @pytest.fixture
    def context_with_orphans(self):
        """Create TestContext with orphaned nodes."""
        return TestContext(
            seeds=[
                {'id': 's1', 'label': 'send', 'type': 'method', 'metadata': {'filepath': 'session.py'}},
            ],
            context_nodes=[
                {'id': 'c1', 'label': 'request', 'type': 'function', 'metadata': {'filepath': 'session.py'}},
                {'id': 'c2', 'label': 'orphan', 'type': 'function', 'metadata': {'filepath': 'other.py'}},
            ],
            edges=[
                {'source': 's1', 'target': 'c1', 'relation': 'calls'},
            ],
            test_nodes=[],
            repo='test/repo',
            base_commit='abc123def456',
        )

    def test_validate_valid_context(self, valid_context):
        """Validate a valid TestContext."""
        validator = TestContextValidator(valid_context)
        is_valid, report = validator.validate()
        assert is_valid is True

    def test_validate_context_with_orphans(self, context_with_orphans):
        """Detect orphaned nodes in TestContext."""
        validator = TestContextValidator(context_with_orphans)
        is_valid, report = validator.validate()
        assert is_valid is False
        assert 'Orphaned' in report or 'orphan' in report.lower()

    def test_validate_broken_edges(self):
        """Detect broken edges in TestContext."""
        context = TestContext(
            seeds=[{'id': 's1', 'label': 'send', 'type': 'method', 'metadata': {'filepath': 'session.py'}}],
            context_nodes=[],
            edges=[
                {'source': 's1', 'target': 'nonexistent', 'relation': 'calls'},
            ],
            test_nodes=[],
            repo='test/repo',
            base_commit='abc123def456',
        )
        validator = TestContextValidator(context)
        is_valid, report = validator.validate()
        assert is_valid is False

    def test_validate_disconnected_seeds(self):
        """Detect seeds with no outgoing edges."""
        context = TestContext(
            seeds=[
                {'id': 's1', 'label': 'send', 'type': 'method', 'metadata': {'filepath': 'session.py'}},
            ],
            context_nodes=[
                {'id': 'c1', 'label': 'request', 'type': 'function', 'metadata': {'filepath': 'session.py'}},
            ],
            edges=[],  # No edges
            test_nodes=[],
            repo='test/repo',
            base_commit='abc123def456',
        )
        validator = TestContextValidator(context)
        is_valid, report = validator.validate()
        assert is_valid is False
        assert 'Disconnected' in report or 'disconnected' in report.lower()

    def test_report_includes_context_stats(self, valid_context):
        """Report includes context statistics."""
        validator = TestContextValidator(valid_context)
        is_valid, report = validator.validate()
        assert 'Seeds:' in report or 'seeds' in report.lower()
        assert 'Context:' in report or 'context' in report.lower()
