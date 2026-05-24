"""Smoke tests for graph traversal."""

import pytest
from kg_construction.kg.traversal import GraphTraversal


class TestGraphTraversal:
    """Test GraphTraversal.bfs()."""

    @pytest.fixture
    def simple_graph(self):
        """Create a simple test graph."""
        nodes = {
            'n1': {'id': 'n1', 'label': 'func_a'},
            'n2': {'id': 'n2', 'label': 'func_b'},
            'n3': {'id': 'n3', 'label': 'func_c'},
            'n4': {'id': 'n4', 'label': 'func_d'},
        }
        edges = [
            {'source': 'n1', 'target': 'n2', 'relation': 'calls'},
            {'source': 'n2', 'target': 'n3', 'relation': 'calls'},
            {'source': 'n1', 'target': 'n4', 'relation': 'inherits'},
        ]
        return nodes, edges

    def test_bfs_single_node(self, simple_graph):
        """BFS from single node at depth 0."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()
        visited, traversed = traversal.bfs(['n1'], nodes, edges, depth=0)
        assert visited == {'n1'}
        assert len(traversed) == 0

    def test_bfs_depth_1(self, simple_graph):
        """BFS from single node at depth 1."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()
        visited, traversed = traversal.bfs(['n1'], nodes, edges, depth=1)
        assert 'n1' in visited
        assert 'n2' in visited  # n1 calls n2
        assert 'n4' in visited  # n1 inherits n4
        assert len(traversed) == 2  # Two outgoing edges

    def test_bfs_depth_2(self, simple_graph):
        """BFS from single node at depth 2."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()
        visited, traversed = traversal.bfs(['n1'], nodes, edges, depth=2)
        assert 'n1' in visited
        assert 'n2' in visited
        assert 'n3' in visited  # n1 -> n2 -> n3
        assert 'n4' in visited

    def test_bfs_no_duplicate_edges(self, simple_graph):
        """BFS with bidirectional edges should not duplicate."""
        nodes, edges = simple_graph
        # Add reverse edge to test deduplication
        edges.append({'source': 'n2', 'target': 'n1', 'relation': 'calls'})

        traversal = GraphTraversal()
        visited, traversed = traversal.bfs(
            ['n1'], nodes, edges, depth=2, directions={'outgoing', 'incoming'}
        )

        # Count occurrences of the n1->n2 edge
        n1_to_n2 = [e for e in traversed if e['source'] == 'n1' and e['target'] == 'n2']
        assert len(n1_to_n2) == 1, "Edge n1->n2 should appear only once"

    def test_bfs_edge_filter(self, simple_graph):
        """BFS respects edge filter."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()

        # Only traverse 'calls' edges
        visited, traversed = traversal.bfs(
            ['n1'], nodes, edges, depth=1, edge_filter={'calls'}
        )

        assert 'n2' in visited  # n1 calls n2
        assert 'n4' not in visited  # n1 inherits n4 (filtered out)
        assert len(traversed) == 1

    def test_bfs_empty_edge_filter(self, simple_graph):
        """BFS with empty edge filter traverses no edges."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()

        visited, traversed = traversal.bfs(
            ['n1'], nodes, edges, depth=1, edge_filter=set()
        )

        assert visited == {'n1'}  # Only start node
        assert len(traversed) == 0  # No edges traversed

    def test_bfs_multiple_starts(self, simple_graph):
        """BFS from multiple start nodes."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()

        visited, traversed = traversal.bfs(['n2', 'n3'], nodes, edges, depth=1)

        assert 'n2' in visited
        assert 'n3' in visited

    def test_bfs_outgoing_direction_only(self, simple_graph):
        """BFS with outgoing direction only."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()

        visited, traversed = traversal.bfs(
            ['n1'], nodes, edges, depth=2, directions={'outgoing'}
        )

        assert 'n1' in visited
        assert 'n2' in visited
        assert 'n3' in visited
        assert 'n4' in visited

    def test_bfs_invalid_node_ignored(self, simple_graph):
        """BFS ignores start nodes not in graph."""
        nodes, edges = simple_graph
        traversal = GraphTraversal()

        visited, traversed = traversal.bfs(
            ['n1', 'nonexistent'], nodes, edges, depth=1
        )

        # Should still work with valid nodes
        assert 'n1' in visited
        assert 'n2' in visited
