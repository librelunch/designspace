"""Conformance laws: The Representation Layer (API.md, "The Representation
Layer"; the Representation conformance bullet; PLAN.md M11 gate;
DECISIONS.md D-52…D-64, D-76…D-78).

**Stage 1** section: the laws that hold for a **supplied** `Representation`
— built directly, with no derived-tier machinery to lean on — plus the
`ChartApply` node's serialization round-trip, since Stage 2's transport
depends on the codec added here being correct first.

**Stage 2** section: `Space.represent()` and the induced chart
representation (`represent/_charts.py`, `_transport.py`, `_build.py`) —
shape, path/arity preservation, rows 31/32 message content, struct-lift
and dynamic-lift transport, bound-origin constraint transport, and
defaults/anchors settling. Stage 3 completes the full law block (decode
totality over the whole corpus, measure preservation, the supplied
hierarchy-flattening morphism, the grep assertion) and adds the
`mixture_stickbreaking` corpus fixture.

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
- **The induced representation's shape** — exactly the chart-bearing
  params (own or element level), excluding count/prop-read ones; `real(0,
  1)` targets; `periodic` mirrored (D-58).
- **Path and arity preservation** — `set(target.params) ==
  set(source.params)` over definition-path keys; a count param stays
  `integer`.
- **Rows 31/32** — message-content tests naming the offending path.
- **Struct-lift and dynamic-lift transport** — a per-element constraint on
  a chart-bearing struct field, and a dynamic-count lift, both decode
  totally and agree on feasibility.
- **Bound-origin transport** — an expression-bounded param's generated
  constraint still enforces correctly once its operands are chart-wrapped.
- **Defaults and anchors** — encoded and validated where possible; dropped
  and reported otherwise (an anchor drops whole).
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

import designspace as ds
from designspace.build._paramexpr import ParamExpr
from designspace.charts._external import build_external_chart
from designspace.errors import ResolutionError, SerializationError
from designspace.expr import ChartApply, Compare, Literal
from designspace.identity._tags import EncodeContext, decode_expr, encode_expr
from designspace.ir import Constraint, ParamDef, RealDomain
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


# =============================================================================
# Stage 2: Space.represent() and the induced chart representation
# =============================================================================


class TestInducedRepresentationShape:
    def test_touches_exactly_chart_bearing_params(self):
        space = ds.space(
            ds.param("lr").real(1e-5, 1.0).log_scale(),
            ds.param("algo").categorical("adam", "sgd"),
            ds.param("flag").bool(),
            ds.param("items").subset(["a", "b", "c"]),
        )
        rep = space.represent()
        assert rep.encoded == ("lr",)
        for path in ("algo", "flag", "items"):
            assert rep.target.params[path].type_kind == space.params[path].type_kind

    def test_scalar_lift_element_chart_is_touched(self):
        # ListDomain.element_chart, not ParamDef.chart -- D-58's "not
        # ParamDef.chart is not None" case.
        space = ds.space(ds.param("dropout").real(0.0, 1.0).repeat(5))
        rep = space.represent()
        assert rep.encoded == ("dropout",)
        target_domain = rep.target.params["dropout"].domain
        assert target_domain.element_domain == ds.RealDomain(0.0, 1.0)

    def test_struct_lift_field_chart_is_touched_at_its_relocated_key(self):
        stop = ds.space(ds.param("dwell").real(0.0, 10.0), ds.param("active").bool())
        space = ds.space(ds.param("stops").space(stop).repeat(3))
        rep = space.represent()
        assert rep.encoded == ("stops[].dwell",)

    def test_targets_are_all_real_0_1(self):
        space = ds.space(
            ds.param("lr").real(1e-5, 1.0).log_scale(),
            ds.param("n").integer(1, 100),
        )
        rep = space.represent()
        for path in rep.encoded:
            pd = rep.target.params[path]
            assert pd.type_kind == "real"
            assert pd.domain == ds.RealDomain(0.0, 1.0)
            assert pd.prior is None
            assert pd.quantized is None

    def test_periodic_is_mirrored(self):
        space = ds.space(ds.param("angle").real(0.0, 360.0, periodic=True))
        rep = space.represent()
        assert rep.target.params["angle"].periodic is True
        # Without the mirror, from_unit(1.0) == hi, which validates as
        # invalid for a periodic domain -- decode must stay total at the
        # boundary the target's own periodic domain actually samples up to.
        boundary_genotype = {"angle": 0.0}
        assert rep.source.validate(rep.decode(boundary_genotype)).param_errors == ()

    def test_count_and_prop_read_params_are_excluded(self):
        space = ds.space(
            ds.param("n").integer(1, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        rep = space.represent()
        assert "n" not in rep.encoded
        assert "n" in rep.excluded_by_prop
        assert "xs" in rep.encoded


class TestPathAndArityPreservation:
    def test_key_set_is_unchanged(self):
        space = ds.space(
            ds.param("n").integer(1, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
            ds.param("algo").categorical("a", "b"),
        )
        rep = space.represent()
        assert set(rep.target.params) == set(space.params)

    def test_count_param_stays_integer(self):
        space = ds.space(
            ds.param("n").integer(1, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        rep = space.represent()
        assert rep.target.params["n"].type_kind == "integer"
        assert rep.target.params["n"].domain == space.params["n"].domain


class TestRow31Row32Messages:
    def test_row_32_relocated_descendants(self):
        stop = ds.space(ds.param("dwell").real(0.0, 10.0))
        space = ds.space(ds.param("stops").space(stop).repeat(3))

        def bad_rule(pd: ParamDef) -> None:
            return None

        # A struct lift's own base ("stops") has relocated descendants
        # ("stops[].dwell") -- matching it directly must raise row 32, even
        # though nothing here ever calls bad_rule (dispatch never matches
        # "stops" under the induced rule, since it is chartless -- so this
        # exercises the check through a rule that *does* match it).
        class _AnyRule:
            def target(self, param: ParamDef) -> ParamDef:
                return param

            def decode(self, param: ParamDef, value):
                return value

        def rule(pd: ParamDef):
            return _AnyRule() if pd.path == "stops" else None

        with pytest.raises(ResolutionError, match="row 32"):
            space.represent(rule)

    def test_row_32_count_read_is_strict_even_for_a_user_rule(self):
        space = ds.space(
            ds.param("n").integer(1, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )

        class _AnyRule:
            def target(self, param: ParamDef) -> ParamDef:
                return param

            def decode(self, param: ParamDef, value):
                return value

        def rule(pd: ParamDef):
            return _AnyRule() if pd.path == "n" else None

        with pytest.raises(ResolutionError, match="row 32"):
            space.represent(rule)

    def test_row_32_prop_read_without_prop_expr(self):
        pytest.importorskip("designspace.custom")

        class _Custom:
            type_key = "counter"

            def validate(self, value):
                return isinstance(value, int)

            def to_json(self, value):
                return value

            def from_json(self, data):
                return data

            def describe(self):
                return {}

            def properties(self):
                return {"n": int}

            def extract(self, value, prop):
                return value

        space = ds.space(
            ds.param("c").custom(_Custom()),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("c").prop("n")),
        )

        class _NoPropExpr:
            def target(self, param: ParamDef) -> ParamDef:
                return param

            def decode(self, param: ParamDef, value):
                return value

        def rule(pd: ParamDef):
            return _NoPropExpr() if pd.path == "c" else None

        with pytest.raises(ResolutionError, match="row 32"):
            space.represent(rule)

    def test_row_31_target_must_return_the_same_path(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))

        class _WrongPath:
            def target(self, param: ParamDef) -> ParamDef:
                from dataclasses import replace

                return replace(param, path="y")

            def decode(self, param: ParamDef, value):
                return value

        def rule(pd: ParamDef):
            return _WrongPath() if pd.path == "x" else None

        with pytest.raises(ResolutionError, match="row 31"):
            space.represent(rule)


class TestStructLiftTransport:
    def test_per_element_constraint_on_a_chart_bearing_field(self):
        stop = ds.space(
            ds.param("dwell").real(0.5, 10.0).log_scale(),
            ds.param("active").bool(),
        )
        space = ds.space(
            ds.param("n_stops").integer(1, 4),
            ds.param("stops").space(stop).repeat(ds.param("n_stops")),
        ).forbid(ds.param("stops").field("dwell").sum() > 15.0)

        rep = space.represent()
        for g in rep.target.sample_dicts(100, seed=10):
            p = rep.decode(g)
            assert space.validate(p).param_errors == ()
            assert rep.target.is_feasible(g) == space.is_feasible(p)


class TestDynamicLiftTransport:
    def test_dynamic_count_lift_decodes_totally(self):
        space = ds.space(
            ds.param("n_layers").integer(1, 5),
            ds.param("widths").integer(8, 256).log_scale().repeat(ds.param("n_layers")),
        )
        rep = space.represent()
        assert rep.excluded_by_prop == ("n_layers",)
        for g in rep.target.sample_dicts(100, seed=11):
            p = rep.decode(g)
            assert space.validate(p).param_errors == ()


class TestBoundOriginTransport:
    def test_expression_bound_still_enforces_after_chart_wrapping(self):
        space = ds.space(
            ds.param("total").integer(100, 1000),
            ds.param("buf_a").integer(1, ds.param("total")),
        )
        rep = space.represent()
        for g in rep.target.sample_dicts(100, seed=12):
            p = rep.decode(g)
            assert space.validate(p).param_errors == ()
            assert rep.target.is_feasible(g) == space.is_feasible(p)
            assert p["buf_a"] <= p["total"]  # the bound-origin constraint itself


class TestDefaultsAndAnchorsSettling:
    class _ExternalPrior:
        """ppf-only: chart decodes but cannot encode (API.md, "Charts")."""

        def ppf(self, q: float) -> float:
            return q

    def test_default_encodes_when_invertible(self):
        space = ds.space(ds.param("y").real(0.0, 10.0).default(5.0))
        rep = space.represent()
        assert "y" not in rep.dropped_defaults
        assert rep.target.params["y"].default == pytest.approx(0.5)

    def test_default_drops_when_the_chart_is_not_invertible(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).prior(self._ExternalPrior()).default(0.3)
        )
        rep = space.represent()
        assert rep.dropped_defaults == ("x",)
        assert rep.target.params["x"].default is None

    def test_anchor_drops_whole_when_one_key_cannot_encode(self):
        space = (
            ds.space(
                ds.param("x").real(0.0, 1.0).prior(self._ExternalPrior()),
                ds.param("y").real(0.0, 10.0),
            )
            .anchor({"baseline": {"x": 0.3, "y": 5.0}})
        )
        rep = space.represent()
        assert rep.dropped_anchors == ("baseline",)
        assert dict(rep.target.anchors) == {}

    def test_anchor_survives_when_every_key_encodes(self):
        space = ds.space(ds.param("y").real(0.0, 10.0)).anchor({"baseline": {"y": 5.0}})
        rep = space.represent()
        assert rep.dropped_anchors == ()
        assert "baseline" in rep.target.anchors
        assert rep.target.anchors["baseline"]["y"] == pytest.approx(0.5)


class TestIdentityLaw:
    def test_no_rules_no_chart_bearing_params_is_the_identity(self):
        space = ds.space(
            ds.param("algo").categorical("a", "b", "c"),
            ds.param("flag").bool(),
            ds.param("items").subset(["x", "y", "z"], min_size=1),
        )
        rep = space.represent()
        assert rep.encoded == ()
        assert rep.target.fingerprint("full") == space.fingerprint("full")
        assert rep.invertible is True
        assert rep.measure_preserving is True
        c = space.sample_one(seed=13)
        assert rep.decode(c) == c
        assert rep.encode(c) == c


_CORPUS_FIXTURES = [
    "flat_hpo",
    "greenhouse",
    "flow_chemistry",
    "job_shop",
    "sat_solver",
    "wind_farm_grid",
    "delivery_routes",
    "solver_portfolio",
    "memetic_pipeline",
    "firmware_buffers",
    "pump_configurator",
    "compiler_pipeline",
    "vi_family",
]


class TestRepresentCorpus:
    """The measured baseline PLAN.md's M11 gate names by name: decode
    totality and feasibility agreement for every corpus fixture, under the
    induced representation. `mixture_stickbreaking` joins the corpus and
    this parametrization at Stage 3, alongside the full 200/200 gate."""

    @pytest.fixture(autouse=True)
    def _corpus_path(self):
        import sys
        from pathlib import Path

        corpus_dir = Path(__file__).resolve().parents[1] / "corpus"
        if str(corpus_dir) not in sys.path:
            sys.path.insert(0, str(corpus_dir))

    @pytest.mark.parametrize("name", _CORPUS_FIXTURES)
    def test_decode_totality_and_feasibility_agreement(self, name):
        import importlib

        space = importlib.import_module(name).build_space()
        rep = space.represent()
        for g in rep.target.sample_dicts(50, seed=0):
            p = rep.decode(g)
            assert space.validate(p).param_errors == (), f"{name}: decode totality violated"
            assert rep.target.is_feasible(g) == space.is_feasible(p), (
                f"{name}: feasibility agreement violated"
            )
