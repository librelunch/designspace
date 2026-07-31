"""Conformance laws: The Representation Layer (API.md, "The Representation
Layer"; the Representation conformance bullet; PLAN.md M11 gate;
DECISIONS.md D-52…D-64, D-76…D-78).

**Stage 1** (this file, opened): the laws that hold for a **supplied**
`Representation` — built directly, with no derived-tier machinery yet to
lean on — plus the `ChartApply` node's serialization round-trip, since
Stage 2's transport depends on the codec added here being correct first.
Stage 2 adds the induced chart representation and `Space.represent()`;
Stage 3 completes the full law block (decode totality over the corpus,
rows 31-32, measure preservation, the supplied hierarchy-flattening
morphism, the grep assertion) against the derived tier those stages build.

Laws covered here:

- **Decode totality** — `source.validate(rep.decode(g)).param_errors == ()`
  for every `g` drawn from `target` (D-62: domain membership, not `.valid`).
- **Feasibility agreement** — `target.is_feasible(g) ==
  source.is_feasible(rep.decode(g))`, for a representation whose target
  correctly mirrors the source's constraint.
- **Round-trip** — `decode(encode(x)) == x` when invertible;
  `encode(decode(g)) == g` is explicitly *not* a law, witnessed with an
  integer-chart-shaped many-to-one decode (D-59's asymmetry, generalized).
- **`then`** — associative, with an identity representation a two-sided
  unit — asserted extensionally (decode/encode agreement on sampled
  configs), since `Representation` equality is closure identity.
- **Never enters the IR / `to_json` / the fingerprint preimage** — `target`
  serializes as an ordinary `Space`.
- **`ChartApply` serialization** — round-trips through `to_json`/
  `from_json` inside an ordinary constraint, byte-identical fingerprint;
  its external-`Prior` case rides the existing raise/mark/drop path.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

import designspace as ds
from designspace.build._paramexpr import ParamExpr
from designspace.charts._external import build_external_chart
from designspace.errors import SerializationError
from designspace.expr import ChartApply, Compare, Literal
from designspace.identity._tags import EncodeContext, decode_expr, encode_expr
from designspace.ir import Constraint, RealDomain
from designspace.represent import Representation

# -- supplied-tier fixtures ---------------------------------------------------


def _scaled_pair(factor: float, *, hi_source: float, forbid_above: float | None = None):
    """A source `real(0, hi_source)` and a target `real(0, 1)`, related by
    `x_source = x_target * factor` — exact under floating point since every
    `factor` used below is a power of two. `forbid_above` (in source units),
    when given, is mirrored onto the target in target units, so the two
    spaces' feasible sets agree by construction — exactly what a correct
    transport is responsible for (Stage 2)."""
    source = ds.space(ds.param("x").real(0.0, hi_source))
    target = ds.space(ds.param("x").real(0.0, 1.0))
    if forbid_above is not None:
        source = source.forbid(ds.param("x") > forbid_above)
        target = target.forbid(ds.param("x") > forbid_above / factor)
    rep = Representation(
        source=source,
        target=target,
        decode=lambda g: {"x": g["x"] * factor},
        encode=lambda p: {"x": p["x"] / factor},
    )
    return source, target, rep


class TestDecodeTotality:
    def test_every_decoded_draw_is_domain_valid_in_source(self):
        _source, target, rep = _scaled_pair(4.0, hi_source=8.0)
        for g in target.sample_dicts(200, seed=0):
            phenotype = rep.decode(g)
            assert rep.source.validate(phenotype).param_errors == ()


class TestFeasibilityAgreement:
    def test_agrees_when_the_constraint_is_correctly_mirrored(self):
        source, target, rep = _scaled_pair(10.0, hi_source=10.0, forbid_above=8.0)
        for g in target.sample_dicts(300, seed=1):
            phenotype = rep.decode(g)
            assert target.is_feasible(g) == source.is_feasible(phenotype)

    def test_law_is_not_vacuous(self):
        # A representation that forgets to mirror the constraint really can
        # disagree -- confirms the test above is not trivially true.
        source = ds.space(ds.param("x").real(0.0, 10.0)).forbid(ds.param("x") > 8.0)
        target = ds.space(ds.param("x").real(0.0, 1.0))  # no mirrored forbid
        rep = Representation(
            source=source, target=target, decode=lambda g: {"x": g["x"] * 10.0}
        )
        disagreements = sum(
            1
            for g in target.sample_dicts(300, seed=2)
            if target.is_feasible(g) != source.is_feasible(rep.decode(g))
        )
        assert disagreements > 0


class TestRoundTrip:
    def test_decode_encode_is_identity_when_invertible(self):
        _source, target, rep = _scaled_pair(2.0, hi_source=2.0)
        for g in target.sample_dicts(100, seed=3):
            phenotype = rep.decode(g)
            assert rep.decode(rep.encode(phenotype)) == phenotype

    def test_encode_decode_is_not_a_law(self):
        """An integer-chart-shaped many-to-one decode: every unit
        coordinate in the same quarter-bucket decodes to the same integer,
        and `encode` returns that bucket's midpoint (mirroring `to_unit`'s
        own integer convention, API.md "Charts"). `decode(encode(k)) == k`
        holds; `encode(decode(g)) == g` does not — two different `g`s in
        the same bucket decode to the same `k` and then re-encode to the
        *same* midpoint, losing the original `g` (D-57's stated asymmetry:
        "integer charts ... are many-to-one")."""
        n_buckets = 4

        def decode(g: dict) -> dict:
            k = min(int(g["g"] * n_buckets), n_buckets - 1)
            return {"k": k}

        def encode(p: dict) -> dict:
            return {"g": (p["k"] + 0.5) / n_buckets}

        source = ds.space(ds.param("k").integer(0, n_buckets - 1))
        target = ds.space(ds.param("g").real(0.0, 1.0))
        rep = Representation(source=source, target=target, decode=decode, encode=encode)

        # decode(encode(k)) == k for every declared k.
        for k in range(n_buckets):
            assert rep.decode(rep.encode({"k": k})) == {"k": k}

        # encode(decode(g)) == g fails for at least one pair sharing a bucket.
        g_a, g_b = 0.01, 0.20  # both land in bucket 0 for n_buckets=4
        assert rep.decode({"g": g_a}) == rep.decode({"g": g_b}) == {"k": 0}
        recovered = rep.encode(rep.decode({"g": g_a}))
        assert recovered != {"g": g_a}


class TestThenAlgebra:
    def _identity_rep(self, space: ds.Space) -> Representation:
        return Representation(
            source=space, target=space, decode=lambda g: dict(g), encode=lambda p: dict(p)
        )

    def test_identity_is_a_two_sided_unit(self):
        _source, target, rep = _scaled_pair(3.0, hi_source=3.0)
        left = self._identity_rep(rep.source).then(rep)
        right = rep.then(self._identity_rep(rep.target))
        for g in target.sample_dicts(30, seed=4):
            assert left.decode(g) == rep.decode(g) == right.decode(g)
        for p in rep.source.sample_dicts(30, seed=5):
            assert left.encode(p) == rep.encode(p) == right.encode(p)

    def test_associative(self):
        space_a = ds.space(ds.param("x").real(0.0, 8.0))
        space_b = ds.space(ds.param("x").real(0.0, 4.0))
        space_c = ds.space(ds.param("x").real(0.0, 2.0))
        space_d = ds.space(ds.param("x").real(0.0, 1.0))

        def rep_between(source: ds.Space, target: ds.Space, factor: float) -> Representation:
            return Representation(
                source=source,
                target=target,
                decode=lambda g, f=factor: {"x": g["x"] * f},
                encode=lambda p, f=factor: {"x": p["x"] / f},
            )

        r1 = rep_between(space_a, space_b, 2.0)
        r2 = rep_between(space_b, space_c, 2.0)
        r3 = rep_between(space_c, space_d, 2.0)

        left_assoc = (r1.then(r2)).then(r3)
        right_assoc = r1.then(r2.then(r3))
        for g in space_d.sample_dicts(30, seed=6):
            assert left_assoc.decode(g) == right_assoc.decode(g)
        for p in space_a.sample_dicts(30, seed=7):
            assert left_assoc.encode(p) == right_assoc.encode(p)


class TestNeverEntersIdentityOrSerialization:
    def test_representation_has_no_to_json_or_fingerprint(self):
        _source, _target, rep = _scaled_pair(2.0, hi_source=2.0)
        assert not hasattr(rep, "to_json")
        assert not hasattr(rep, "fingerprint")

    def test_target_serializes_as_an_ordinary_space(self):
        _source, target, rep = _scaled_pair(2.0, hi_source=2.0)
        doc = rep.target.to_json()
        rebuilt = ds.Space.from_json(doc)
        assert rebuilt.fingerprint("full") == target.fingerprint("full")


# -- ChartApply serialization -------------------------------------------------


def _target_shaped_space() -> ds.Space:
    return ds.space(ds.param("u").real(0.0, 1.0))


def _log_chart_apply() -> ChartApply:
    from designspace.charts._builtin import LogChart

    # `prior=Log()` matters, not just `chart=LogChart(...)`: `decode_expr`
    # rebuilds the chart from the *declaration* (type_kind/domain/prior/
    # quantized), never trusting a serialized `Chart` object (none exists
    # on the wire) -- omitting it here would round-trip to a *uniform*
    # chart instead, silently.
    return ChartApply(
        ParamExpr(path="u"), LogChart(1.0, 100.0), "real", RealDomain(1.0, 100.0), prior=ds.Log()
    )


class TestChartApplySerialization:
    def test_round_trips_through_encode_decode_expr(self):
        node = _log_chart_apply()
        tree = encode_expr(node, ctx=None, site="test")
        rebuilt = decode_expr(tree)
        assert isinstance(rebuilt, ChartApply)
        assert rebuilt.type_kind == node.type_kind
        assert rebuilt.domain == node.domain
        assert rebuilt.periodic == node.periodic
        assert rebuilt.chart.from_unit(0.5) == pytest.approx(node.chart.from_unit(0.5))

    def test_round_trips_inside_a_whole_space(self):
        target = _target_shaped_space()
        node = _log_chart_apply()
        # A synthetic transported-looking constraint: "the SOURCE value of
        # u (after a log-chart decode) exceeds 10".
        constraint = Constraint(
            expr=Compare("gt", node, Literal(10.0)),
            hard=True,
            origin="user",
            tags=frozenset(),
            meta=MappingProxyType({}),
            params=frozenset({"u"}),
        )
        space = ds.space_from_ir(target.params, target.conditions, (constraint,))
        doc = space.to_json()
        rebuilt = ds.Space.from_json(doc)
        assert rebuilt.fingerprint("full") == space.fingerprint("full")
        assert rebuilt.fingerprint("sampling") == space.fingerprint("sampling")
        assert rebuilt.to_json() == doc

        # log_chart.from_unit(u=0.5) == 10.0 exactly (sqrt(1*100)) -- confirm
        # the reconstructed constraint still evaluates identically either
        # side of the boundary.
        assert space.is_feasible({"u": 0.6}) == rebuilt.is_feasible({"u": 0.6})
        assert space.is_feasible({"u": 0.4}) == rebuilt.is_feasible({"u": 0.4})

    def test_from_json_never_trusts_the_document_chart(self):
        """`rebuild_charts`'s rule ("charts are always derived, never
        trusted from input") applies here too -- decode reconstructs the
        chart from the declaration, not from anything resembling a
        serialized `Chart` object (no such thing is ever written)."""
        node = _log_chart_apply()
        tree = encode_expr(node, ctx=None, site="test")
        assert "chart" not in tree  # only the declaration is on the wire
        rebuilt = decode_expr(tree)
        assert isinstance(rebuilt, ChartApply)
        assert rebuilt.chart is not node.chart  # a fresh object, not the same instance


class _ExternalPpfOnlyPrior:
    """Opaque external `Prior` (ppf-only, contained in bounds): the one
    case an M11 `ChartApply` can carry that is not fully structural
    (API.md, "Identity and Serialization": external `Prior` objects join
    the non-serializable set; DECISIONS.md D-31)."""

    def ppf(self, q: float) -> float:
        return q


class TestChartApplyOpaquePrior:
    def _node(self) -> ChartApply:
        prior = _ExternalPpfOnlyPrior()
        chart = build_external_chart("u", prior, 0.0, 1.0)
        return ChartApply(ParamExpr(path="u"), chart, "real", RealDomain(0.0, 1.0), prior=prior)

    def test_raises_by_default(self):
        with pytest.raises(SerializationError, match="has no structural encoding"):
            encode_expr(self._node(), ctx=None, site="test")

    def test_mark_degrades_only_the_prior_not_the_whole_node(self):
        # Mirrors `encode_param`: the node stays fully structural (kind,
        # children, type_kind, domain, periodic) -- only the *nested*
        # `prior` sub-value degrades to the opaque marker, the same
        # precedent an ordinary chart-bearing `ParamDef` already sets.
        ctx = EncodeContext(mode="mark")
        tree = encode_expr(self._node(), ctx=ctx, site="test")
        assert tree["kind"] == "chart_apply"
        assert tree["prior"].get("$opaque") is True

    def test_drop_records_a_manifest_entry(self):
        # "drop" mode omits the key entirely (matching `encode_param`'s own
        # prior handling) -- distinct from "mark", which writes the inline
        # sentinel; both route through `ctx.dropped` for "drop"'s manifest.
        ctx = EncodeContext(mode="drop")
        tree = encode_expr(self._node(), ctx=ctx, site="my site")
        assert "prior" not in tree
        assert any("my site" in entry for entry in ctx.dropped)
