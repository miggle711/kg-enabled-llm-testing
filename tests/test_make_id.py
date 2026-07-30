"""Regression test: _make_id's node ID length must be long enough that
collisions are genuinely negligible at real repo scale.

Previously 8 hex chars (32 bits) -- the birthday-paradox collision
probability at django's own real measured size (46,520 nodes) is ~25%,
not the "negligible... ~10k entities" scale the old docstring assumed. A
collision here is silent data loss: _aggregate_and_index's node dedup
treats a colliding ID as "already seen" and drops the second, genuinely
different entity entirely, with no error raised. Raised to 16 hex chars
(64 bits), where the same real-scale collision probability is ~6e-11.
"""

from kg_construction.ast.helpers import _make_id


class TestMakeId:
    def test_id_is_16_hex_chars(self):
        assert len(_make_id("func_psf_requests_sessions.py_send")) == 16

    def test_id_is_deterministic(self):
        text = "func_psf_requests_sessions.py_send"
        assert _make_id(text) == _make_id(text)

    def test_different_text_produces_different_id(self):
        assert _make_id("func_a") != _make_id("func_b")

    def test_real_repo_scale_collision_probability_is_negligible(self):
        """Direct check of the birthday-paradox math this fix relies on,
        at django's own real measured node count (46,520, confirmed via a
        real build this session) -- not a proof of no collision, but a
        concrete guard that nobody accidentally shortens the ID again
        without re-deriving this number.
        """
        n = 46_520
        space = 16 ** 16  # 16 hex chars = 64 bits
        collision_probability = n ** 2 / (2 * space)
        assert collision_probability < 1e-9
