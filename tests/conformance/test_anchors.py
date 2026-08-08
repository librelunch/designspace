"""Conformance laws: space-level `.anchor()` and `.meta()`.

See API.md, "Constraints and Feasibility".

Row 22: an anchor invalid against the space, whether through an
out-of-domain value or a violated hard constraint, raises `ResolutionError`
naming the anchor key. Row 22's other clause, an anchor conflicting with a
frozen or sliced value, is exercised by the `freeze` and `slice` tests.

Row 23: a non-JSON-serializable space-level `.meta()` value raises.

Scope: anchors and metadata are `full`-scope only, and are excluded from
`sampling`.

Round trip: `to_json` and `from_json` preserve anchors and metadata exactly,
and fingerprints match at both scopes.

Byte identity: a space with no anchors and no metadata carries no `anchors`
or `meta` key at all, in either its preimage or its `to_json` document. That
is `identity/_ir_codec.py`'s guarantee that an additive field costs nothing
when absent, and every committed corpus vector depends on it.

A known-answer vector: `_anchor_demo.py`'s space fingerprints and serializes
to a committed, byte-stable digest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import designspace as ds
from designspace import Space
from designspace.errors import ResolutionError

_CONF_DIR = Path(__file__).resolve().parent
if str(_CONF_DIR) not in sys.path:
    sys.path.insert(0, str(_CONF_DIR))

from _anchor_demo import build_space as build_anchor_demo  # noqa: E402

VECTORS_DIR = _CONF_DIR / "vectors"


def _xy() -> Space:
    return ds.space(ds.param("x").real(0.0, 1.0), ds.param("k").integer(0, 10))


# -- Row 22: anchor validation ----------------------------------------------


class TestAnchorValidation:
    def test_row22_out_of_domain_value_raises(self):
        space = _xy()
        with pytest.raises(ResolutionError, match=r"anchor 'bad'.*row 22"):
            space.anchor({"bad": {"x": 5.0, "k": 3}})  # x outside [0, 1]

    def test_row22_violated_constraint_raises(self):
        space = _xy().forbid(ds.param("k") > 5)
        with pytest.raises(ResolutionError, match=r"anchor 'bad'.*row 22"):
            space.anchor({"bad": {"x": 0.5, "k": 8}})

    def test_valid_anchor_accepted_and_readable(self):
        space = _xy().anchor({"ok": {"x": 0.5, "k": 3}})
        assert space.anchors == {"ok": {"x": 0.5, "k": 3}}

    def test_anchors_accumulate_and_last_write_wins_per_key(self):
        space = (
            _xy()
            .anchor({"a": {"x": 0.1, "k": 1}})
            .anchor({"b": {"x": 0.2, "k": 2}})
            .anchor({"a": {"x": 0.3, "k": 3}})
        )
        assert set(space.anchors) == {"a", "b"}
        assert space.anchors["a"] == {"x": 0.3, "k": 3}

    def test_defaults_vs_anchors_convenience(self):
        # API.md ("Defaults vs. anchors"): `.anchor(configs={"shipped":
        # space.apply_defaults({})})` derives an anchor from complete
        # defaults rather than duplicating them.
        space = ds.space(
            ds.param("x").real(0.0, 1.0).default(0.5),
            ds.param("k").integer(0, 10).default(3),
        )
        anchored = space.anchor({"shipped": space.apply_defaults({})})
        assert anchored.anchors["shipped"] == {"x": 0.5, "k": 3}


# -- Row 23: space-level meta validation -------------------------------------


class TestSpaceMetaValidation:
    def test_row23_non_serializable_value_raises(self):
        space = _xy()
        with pytest.raises(ResolutionError):
            space.meta(cost_model=object())

    def test_row23_dollar_prefixed_key_raises(self):
        space = _xy()
        with pytest.raises(ResolutionError):
            space.meta({"$reserved": 1})

    def test_meta_accumulates_kwargs_and_mapping_tagged_in_to_json(self):
        space = _xy().meta({"a": 1}, b="two")
        doc = space.to_json()
        assert doc["meta"] == {
            "a": {"$t": "int", "v": 1},
            "b": {"$t": "str", "v": "two"},
        }


# -- Scope: full-only, excluded from sampling --------------------------------


class TestAnchorMetaScope:
    def test_excluded_from_sampling_scope_present_in_full(self):
        plain = _xy()
        decorated = _xy().anchor({"ok": {"x": 0.5, "k": 3}}).meta(note="x")
        assert decorated.fingerprint("sampling") == plain.fingerprint("sampling")
        assert decorated.fingerprint("full") != plain.fingerprint("full")


# -- Round-trip law -----------------------------------------------------------


class TestAnchorMetaRoundTrip:
    def test_round_trips(self):
        space = build_anchor_demo()
        restored = Space.from_json(space.to_json())
        assert restored.fingerprint("full") == space.fingerprint("full")
        assert restored.fingerprint("sampling") == space.fingerprint("sampling")
        assert restored.anchors == space.anchors


# -- Byte-identity guard for anchor/meta-free spaces -------------------------


class TestByteIdentityGuard:
    def test_anchor_meta_free_space_has_no_keys_in_to_json(self):
        doc = _xy().to_json()
        assert "anchors" not in doc
        assert "meta" not in doc


# -- Known-answer digest vector -----------------------------------------------


def _load_vector() -> dict:
    path = VECTORS_DIR / "anchor_demo.json"
    if not path.exists():
        raise FileNotFoundError(
            f"missing known-answer vector {path}; generate it with "
            "`uv run python tests/conformance/vectors/_generate.py` "
            "(deliberately; never auto-generated)"
        )
    return json.loads(path.read_text())


class TestAnchorKnownAnswer:
    def test_fingerprint_matches_known_answer(self):
        space = build_anchor_demo()
        vector = _load_vector()
        assert space.fingerprint("full") == vector["fingerprint_full"]
        assert space.fingerprint("sampling") == vector["fingerprint_sampling"]

    def test_to_json_matches_known_answer(self):
        space = build_anchor_demo()
        vector = _load_vector()
        assert space.to_json() == vector["to_json"]
