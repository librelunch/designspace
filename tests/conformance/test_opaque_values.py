"""Conformance laws: `ds.value`, the opaque derived quantity.

See API.md, "Expressions" > `ds.value`, Kleene rule 1's declared-operand
rule, the tier table under "Constraints", row 30, and the non-serializable
set.

Laws enforced here: `opaque_float_margin`, `opaque_bool_bare`,
`opaque_int_count`, `opaque_declaration_errors`, `opaque_calling_convention`,
`opaque_unknown_is_value_driven`, `opaque_identity`,
`opaque_dependency_graph`, `opaque_cardinality`, `opaque_no_narrowing`.

`tests/conformance/test_custom.py` covers `.prop()`'s own laws; this file is
the parity and extension surface for its generalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

import designspace as ds
from designspace.errors import ResolutionError, SerializationError
from designspace.ir import RealRemaining

# -- construction / row 30 ---------------------------------------------------


class TestConstructionRow30:
    def test_non_scalar_returns_raises(self):
        with pytest.raises(ResolutionError, match="row 30"):
            ds.value(lambda x: [x], ds.param("x").real(0.0, 1.0), returns=list)

    def test_non_expression_operand_raises(self):
        with pytest.raises(ResolutionError, match="row 30"):
            ds.value(lambda x: x, 5, returns=float)

    def test_non_callable_fn_raises_type_error(self):
        with pytest.raises(TypeError):
            ds.value("not-callable", ds.param("x").real(0.0, 1.0), returns=float)


# -- returns=float: margin parity with .prop() -------------------------------


class TestFloatMarginParity:
    def test_matches_the_b_minus_a_shape(self):
        # ds.value(deflection, ...) <= 0.005 reports 0.005 - deflection --
        # the same shape as .prop()'s parity baseline (test_custom.py).
        def deflection(load: float, length: float) -> float:
            return load * length / 1000.0

        space = ds.space(
            ds.param("load").real(0.0, 10.0),
            ds.param("length").real(0.0, 10.0),
        ).require(
            ds.value(deflection, ds.param("load"), ds.param("length"), returns=float) <= 0.005
        )
        (ce,) = space.evaluate_constraints({"load": 1.0, "length": 1.0})
        assert ce.applicable is True
        assert ce.margin == pytest.approx(0.005 - 0.001)


# -- returns=bool: bare usage --------------------------------------------------


class TestBoolBareUsage:
    @staticmethod
    def _ok(x: float) -> bool:
        return x > 0.5

    def test_usable_bare_in_require(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(self._ok, ds.param("x"), returns=bool)
        )
        assert space.is_feasible({"x": 0.6})
        assert not space.is_feasible({"x": 0.4})

    def test_margin_is_none(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(self._ok, ds.param("x"), returns=bool)
        )
        (ce,) = space.evaluate_constraints({"x": 0.6})
        assert ce.margin is None

    def test_composes_with_and_or_not(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("gate").bool()).require(
            ds.value(self._ok, ds.param("x"), returns=bool) & ds.param("gate")
        )
        assert space.is_feasible({"x": 0.6, "gate": True})
        assert not space.is_feasible({"x": 0.6, "gate": False})

    def test_none_absorbs_through_composition(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)).require(
            ds.value(self._ok, ds.param("x"), returns=bool) & (ds.param("y") <= 0.5)
        )
        (ce,) = space.evaluate_constraints({"x": 0.6, "y": 0.3})
        assert ce.margin is None  # min(None, 0.2) -> None (Margins composition rule)


# -- returns=int: drives a .repeat() count -------------------------------------


class TestIntDrivesRepeat:
    @staticmethod
    def _n_edges(k: int) -> int:
        return k + 1

    def test_returns_int_count_works(self):
        space = ds.space(
            ds.param("k").integer(0, 3),
            ds.param("edges")
            .real(0.0, 1.0)
            .repeat(ds.value(self._n_edges, ds.param("k"), returns=int)),
        )
        cfg = space.sample_one(seed=0)
        assert len(cfg["edges"]) == self._n_edges(cfg["k"])

    def test_returns_float_count_is_row_12(self):
        with pytest.raises(ResolutionError, match="row 12"):
            ds.space(
                ds.param("k").integer(0, 3),
                ds.param("edges")
                .real(0.0, 1.0)
                .repeat(ds.value(lambda k: float(k), ds.param("k"), returns=float)),
            )


# -- the calling convention ---------------------------------------------------


class TestCallingConvention:
    def test_fn_receives_exactly_operand_values_positionally(self):
        calls: list[tuple[float, float]] = []

        def spy(a: float, b: float) -> float:
            calls.append((a, b))
            return a + b

        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)).require(
            ds.value(spy, ds.param("x"), ds.param("y"), returns=float) <= 1.0
        )
        space.evaluate_constraints({"x": 0.3, "y": 0.4})
        assert calls == [(0.3, 0.4)]

    def test_fn_called_exactly_once_despite_satisfaction_and_margin_both_needing_it(self):
        # evaluate_constraint (eval/_constraint_eval.py) computes
        # satisfaction via evaluate_bool and then, separately, a margin via
        # margin() -- which independently re-walks the same Compare leaf.
        # A shared, call-scoped value_cache (threaded through both) means
        # fn is invoked once per evaluate_constraints()/validate()/
        # is_feasible() call, not twice -- important for an expensive or
        # side-effecting fn.
        calls = 0

        def spy(x: float) -> float:
            nonlocal calls
            calls += 1
            return x

        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(spy, ds.param("x"), returns=float) <= 0.5
        )
        (ce,) = space.evaluate_constraints({"x": 0.3})
        assert ce.applicable and ce.satisfied and ce.margin == pytest.approx(0.2)
        assert calls == 1

    def test_fn_never_receives_the_config(self):
        # If fn were handed the config dict instead of the operand's own
        # value, this type assertion would trip -- asserted directly, since
        # the calling convention is the whole contract (API.md).
        def spy(a: float) -> bool:
            assert isinstance(a, float)
            return a >= 0.0

        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(spy, ds.param("x"), returns=bool)
        )
        space.evaluate_constraints({"x": 0.5})

    def test_fn_exception_propagates_uncaught(self):
        def boom(x: float) -> bool:
            raise ValueError("boom")

        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(boom, ds.param("x"), returns=bool)
        )
        with pytest.raises(ValueError, match="boom"):
            space.is_feasible({"x": 0.5})

    def test_shared_value_node_referenced_twice_in_one_constraint_calls_once(self):
        # The same literal Value object used on both sides of a composite
        # condition -- the value_cache is keyed on the node's identity, so
        # this collapses to one call too, not just the satisfaction/margin
        # pairing.
        calls = 0

        def spy(x: float) -> float:
            nonlocal calls
            calls += 1
            return x

        v = ds.value(spy, ds.param("x"), returns=float)
        space = ds.space(ds.param("x").real(0.0, 1.0)).require((v > 0.1) & (v < 0.9))
        assert space.is_feasible({"x": 0.5})
        assert calls == 1

    def test_fn_called_once_under_partial_evaluation_too(self):
        # partial/_partial.py::_classify_constraint pairs evaluate_bool and
        # margin() exactly like evaluate_constraint does.
        calls = 0

        def spy(x: float) -> float:
            nonlocal calls
            calls += 1
            return x

        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)).require(
            ds.value(spy, ds.param("x"), returns=float) <= 0.5
        )
        pe = space.evaluate_partial({"x": 0.3})
        assert len(pe.evaluable_constraints) == 1
        assert calls == 1


# -- Kleene provenance -------------------------------------------------------


class TestKleeneProvenance:
    @staticmethod
    def _spy_ok(calls: list[float]):
        def ok(x: float) -> bool:
            calls.append(x)
            return x > 0.5

        return ok

    def test_inactive_operand_is_unknown_fn_never_called(self):
        calls: list[float] = []
        space = ds.space(
            ds.param("gate").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("gate")),
        ).require(ds.value(self._spy_ok(calls), ds.param("x"), returns=bool))
        (ce,) = space.evaluate_constraints({"gate": False})
        assert ce.applicable is False
        assert ce.margin is None
        assert calls == []

    def test_if_inactive_inside_operand_composes(self):
        calls: list[float] = []
        space = ds.space(
            ds.param("gate").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("gate")),
        ).require(ds.value(self._spy_ok(calls), ds.param("x").if_inactive(0.9), returns=bool))
        (ce,) = space.evaluate_constraints({"gate": False})
        assert ce.applicable is True
        assert ce.satisfied is True
        assert calls == [0.9]

    def test_pending_under_partial_eval_never_coalesced(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(lambda x: x > 0.5, ds.param("x"), returns=bool)
        )
        pe = space.evaluate_partial({})
        assert pe.evaluable_constraints == ()
        assert len(pe.pending_constraints) == 1

    def test_if_inactive_does_not_coalesce_pending(self):
        # rule 5: .if_inactive() coalesces inactivity alone -- an operand
        # that is merely *unset* (active, present nowhere in the config)
        # must stay pending even wrapped in .if_inactive().
        space = ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(lambda x: x > 0.5, ds.param("x").if_inactive(0.9), returns=bool)
        )
        pe = space.evaluate_partial({})
        assert pe.evaluable_constraints == ()
        assert len(pe.pending_constraints) == 1


# -- row 30's comparison clause ----------------------------------------------


@dataclass(frozen=True)
class _TaggedInt:
    """A minimal full-protocol custom type declaring one int property, for
    the mixed `ds.value`-vs-`.prop()` comparison test below."""

    n: int = 1

    @property
    def type_key(self) -> str:
        return "tagged_int_cmp"

    def sample(self, rng: Any) -> Any:
        return _TaggedInt(int(rng.integers(0, 10)))

    def validate(self, value: Any) -> bool:
        return isinstance(value, _TaggedInt)

    def to_json(self, value: Any) -> Any:
        return {"n": value.n}

    def from_json(self, data: Any) -> Any:
        return _TaggedInt(data["n"])

    def describe(self) -> dict[str, Any]:
        return {}

    def properties(self) -> dict[str, type]:
        return {"n": int}

    def extract(self, value: Any, prop: str) -> Any:
        return value.n


class TestCompareTypeMismatch:
    def test_value_vs_literal_mismatch_is_row_30(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="row 30"):
            space.require(ds.value(lambda x: x, ds.param("x"), returns=float) == "not-a-float")

    def test_no_int_float_leniency(self):
        # Strict type match, mirroring .prop(). An int-
        # declared value compared against a float literal is still row 30.
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="row 30"):
            space.require(ds.value(lambda x: int(x), ds.param("x"), returns=int) == 1.0)

    def test_value_vs_value_mismatch_is_row_30(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0))
        with pytest.raises(ResolutionError, match="row 30"):
            space.require(
                ds.value(lambda x: x, ds.param("x"), returns=float)
                == ds.value(lambda y: y > 0, ds.param("y"), returns=bool)
            )

    def test_value_vs_prop_mismatch_cites_row_30_when_value_is_checked_first(self):
        # The cited row follows whichever side of the comparison is being
        # checked (left-to-right); a Value on the left cites row 30.
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("t").custom(_TaggedInt()))
        with pytest.raises(ResolutionError, match="row 30"):
            space.require(
                ds.value(lambda x: x, ds.param("x"), returns=float) == ds.param("t").prop("n")
            )

    def test_prop_vs_value_mismatch_cites_row_16_when_prop_is_checked_first(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("t").custom(_TaggedInt()))
        with pytest.raises(ResolutionError, match="row 16"):
            space.require(
                ds.param("t").prop("n") == ds.value(lambda x: x, ds.param("x"), returns=float)
            )


# -- identity opacity --------------------------------------------------------


class TestOpacity:
    @staticmethod
    def _space_with_constraint_value() -> ds.Space:
        return ds.space(ds.param("x").real(0.0, 1.0)).require(
            ds.value(lambda x: x > 0.5, ds.param("x"), returns=bool)
        )

    def test_to_json_raises_by_default(self):
        with pytest.raises(SerializationError, match="opaque"):
            self._space_with_constraint_value().to_json()

    def test_to_json_mark_sentinel(self):
        doc = self._space_with_constraint_value().to_json(on_unserializable="mark")
        (c,) = doc["constraints"]
        assert c["expr"] == {"kind": "opaque", "$opaque": True}

    def test_to_json_drop_manifests_and_names_the_site(self):
        doc = self._space_with_constraint_value().to_json(on_unserializable="drop")
        (c,) = doc["constraints"]
        assert c["expr"] == {"kind": "opaque", "$opaque": True}
        assert any("constraint 0" in entry for entry in doc["dropped"])

    def test_fingerprint_raises_by_default(self):
        with pytest.raises(SerializationError):
            self._space_with_constraint_value().fingerprint()

    def test_fingerprint_mark_differs_from_no_constraint(self):
        marked = self._space_with_constraint_value().fingerprint(on_unserializable="mark")
        bare = ds.space(ds.param("x").real(0.0, 1.0)).fingerprint()
        assert marked != bare

    def test_from_json_on_marked_document_raises(self):
        doc = self._space_with_constraint_value().to_json(on_unserializable="mark")
        with pytest.raises(SerializationError):
            ds.Space.from_json(doc)

    def test_opacity_in_when_condition(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).when(ds.value(lambda: True, returns=bool)),
        )
        with pytest.raises(SerializationError, match="'x'"):
            space.to_json()
        doc = space.to_json(on_unserializable="mark")
        (p,) = doc["params"]
        assert p["condition"] == {"kind": "opaque", "$opaque": True}

    def test_opacity_in_dynamic_repeat_count(self):
        space = ds.space(
            ds.param("k").integer(0, 3),
            ds.param("edges")
            .real(0.0, 1.0)
            .repeat(ds.value(lambda k: k, ds.param("k"), returns=int)),
        )
        with pytest.raises(SerializationError, match="'edges'"):
            space.to_json()
        doc = space.to_json(on_unserializable="mark")
        edges_param = next(p for p in doc["params"] if p["path"] == "edges")
        assert edges_param["domain"]["count"] == {
            "kind": "dynamic",
            "expr": {"kind": "opaque", "$opaque": True},
        }


# -- expression bounds: a ds.value has no computable hull (row 20) -----------


class TestBoundHullRow20:
    def test_value_in_bound_expression_is_row_20(self):
        with pytest.raises(ResolutionError, match="row 20"):
            ds.space(
                ds.param("k").integer(0, 5),
                ds.param("x").integer(0, ds.value(lambda k: k, ds.param("k"), returns=int)),
            )


# -- dependency_graph / topological_order -------------------------------------


class TestDependencyGraph:
    def _space(self) -> ds.Space:
        return ds.space(ds.param("a").real(0.0, 1.0), ds.param("b").real(0.0, 1.0)).require(
            ds.value(lambda a, b: a + b, ds.param("a"), ds.param("b"), returns=float) <= 1.0
        )

    def test_operands_params_included_symmetrically(self):
        graph = self._space().dependency_graph
        assert graph["a"] == frozenset({"b"})
        assert graph["b"] == frozenset({"a"})

    def test_topological_order_unaffected(self):
        order = self._space().topological_order
        assert set(order) == {"a", "b"}


# -- .cardinality()'s conservative None ---------------------------------------


class TestCardinalityConservativeNone:
    def test_independent_ds_value_condition_on_a_choice_variant_field(self):
        # A variant field's condition beyond what the discriminator alone
        # would inject makes cardinality() conservatively None:
        # exercised here through a ds.value-based guard specifically, which
        # forces `_condition_matches_injection`'s structural-equality check
        # to hit an opaque node (encode_expr raises; degrades to identity
        # comparison, never crashing .cardinality() itself).
        space = ds.space(
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("kernel").categorical("linear", "rbf"),
                    ds.param("flag").bool().when(ds.value(lambda: True, returns=bool)),
                ),
            ),
        )
        assert space.cardinality() is None


# -- tier table: no narrowing off a grey/black predicate ----------------------


class TestTierNoNarrowing:
    def test_remaining_domain_does_not_narrow_off_a_bare_value_predicate(self):
        space = ds.space(ds.param("x").real(0.0, 10.0)).forbid(
            ds.value(lambda x: x > 5.0, ds.param("x"), returns=bool)
        )
        rd = space.remaining_domain("x", {})
        assert isinstance(rd, RealRemaining)
        assert (rd.lo, rd.hi) == (0.0, 10.0)

    def test_remaining_domain_does_not_narrow_off_a_grey_comparison(self):
        space = ds.space(ds.param("x").real(0.0, 10.0)).forbid(
            ds.value(lambda x: x, ds.param("x"), returns=float) > 5.0
        )
        rd = space.remaining_domain("x", {})
        assert isinstance(rd, RealRemaining)
        assert (rd.lo, rd.hi) == (0.0, 10.0)


# -- relocation: Prop/Value inside a struct/choice payload --------------------


class TestRelocationInsideRepeatElement:
    """A `.prop()`-based condition survives relocation into a lift element.

    `rewrite_expr` in `resolve/_relocate.py` needs a `Prop` branch. Without
    one, any `.prop()`-based condition on a struct or choice payload field
    raises `TypeError`, and it surfaces per instance inside a `.repeat()`
    struct-lift element, `instantiate_element` calling the same
    `rewrite_bool` and `rewrite_expr` walk.
    """

    def test_prop_based_condition_on_a_repeat_struct_element_field(self):
        # Two walks have to handle this space. Resolving it renames the
        # struct-lift element's own field condition for per-instance
        # expansion, which needs `rewrite_expr`'s Prop branch. Evaluating
        # it, through .validate() below, needs `_resolve_param_domain` in
        # eval/_kleene.py to return the domain its bracket walk found for a
        # struct or custom element, which is what `_evaluate_prop`'s
        # `assert isinstance(domain, CustomDomain)` rests on.
        space = ds.space(
            ds.param("stops")
            .space(
                ds.param("tagged").custom(_TaggedInt()),
                ds.param("flag").bool().when(ds.param("tagged").prop("n") > 0),
            )
            .repeat(2),
        )
        # Native config shape: a struct lift is a list of per-instance
        # dicts (a custom leaf holds its JSON-safe phenotype form --
        # "Protocols" > "Value convention"). stops[1].flag is correctly
        # absent: tagged.n <= 0 deactivates it.
        cfg = {"stops": [{"tagged": {"n": 1}, "flag": True}, {"tagged": {"n": 0}}]}
        result = space.validate(cfg)
        assert result.valid

    def test_value_based_condition_on_a_repeat_struct_element_field(self):
        space = ds.space(
            ds.param("stops")
            .space(
                ds.param("gate").real(0.0, 1.0),
                ds.param("flag")
                .bool()
                .when(ds.value(lambda g: g > 0.5, ds.param("gate"), returns=bool)),
            )
            .repeat(2),
        )
        # stops[1].flag correctly absent -- gate <= 0.5 deactivates it.
        cfg = {"stops": [{"gate": 0.6, "flag": True}, {"gate": 0.1}]}
        result = space.validate(cfg)
        assert result.valid

    def test_value_based_per_element_constraint_on_a_repeat_struct(self):
        element = ds.space(ds.param("load").real(0.0, 10.0)).forbid(
            ds.value(lambda load: load > 5.0, ds.param("load"), returns=bool)
        )
        space = ds.space(ds.param("stops").space(element).repeat(2))
        assert not space.is_feasible({"stops": [{"load": 6.0}, {"load": 1.0}]})
        assert space.is_feasible({"stops": [{"load": 4.0}, {"load": 1.0}]})
