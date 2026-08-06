"""Conformance laws: Space: Partial Configs (API.md, "Space: Partial
Configs"; "Conformance Laws" > "Partial Configs").

- Three-valued activity collapses to binary activity under `unknown -> inactive`.
- The driver-loop coincidence: `next_assignable(c) == [] <=> is_complete(c)`.
- `remaining_domain` soundness (never excludes a still-feasible value; every
  descriptor value validates against the declared domain).
- The one-unset-operand reducer: positive (bound and single-forbid narrowing
  across kinds) and negative (a two-unset-operand implication is not
  propagated).
- The `PartialEval` evaluable/pending partition.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

import designspace as ds
from designspace import Space
from designspace.config import flatten, unflatten
from designspace.eval import compute_activity, compute_activity_partial


def _delivery_routes() -> Space:
    stop = ds.space(
        ds.param("location").integer(0, 9),
        ds.param("dwell_min").integer(5, 30),
    )
    return ds.space(
        ds.param("n_stops").integer(1, 5),
        ds.param("stops").space(stop).repeat(ds.param("n_stops")),
    )


def _greenhouse() -> Space:
    return ds.space(
        ds.param("heating").choice(
            "electric",
            gas=ds.space(ds.param("burner_power_kw").real(5.0, 50.0)),
        ),
        ds.param("target_temp_c").real(10.0, 35.0),
    )


class TestCollapseToBinary:
    @given(st.data())
    def test_collapses_to_compute_activity_over_sampled_configs(self, data):
        space = data.draw(st.sampled_from([_delivery_routes(), _greenhouse()]))
        seed = data.draw(st.integers(min_value=0, max_value=10_000))
        cfg = space.sample_dicts(1, seed=seed)[0]
        flat = flatten(cfg, space)
        binary = compute_activity(space, flat)
        partial = compute_activity_partial(space, flat)
        collapsed = {p: (s in ("set", "active_unset")) for p, s in partial.status.items()}
        # `compute_activity` (existing, pre-M6) also assigns a (harmless,
        # unused) activity entry to lift descendant *templates* themselves
        # (e.g. "stops[].location") since its own topological walk doesn't
        # filter them; the partial status map -- meant for real params and
        # instances only -- correctly omits them. Compare over the params
        # both sides actually agree are real.
        binary_real = {p: v for p, v in binary.items() if "[]" not in p}
        assert collapsed == binary_real


class TestNextAssignableInstanceSubstitutedDeps:
    """The coincidence law can't catch an *over-inclusive* readiness filter
    (both sides stay non-empty/False together) -- exercise the dependency
    substitution directly: a lifted struct's intra-element `.when()` must
    gate against the *instance* path (`items[0].a`), not the template
    (`items[].a`, which `next_assignable` would otherwise silently treat as
    always-ready via its `status.get(d, "set")` default)."""

    @staticmethod
    def _space() -> Space:
        return ds.space(
            ds.param("items")
            .space(
                ds.param("a").bool(),
                ds.param("b").real(0.0, 1.0).when(ds.param("a")),
            )
            .repeat(2),
        )

    def test_sibling_field_gated_behind_its_own_instance(self):
        space = self._space()
        na = space.next_assignable({})
        assert "items[0].a" in na and "items[1].a" in na
        assert "items[0].b" not in na and "items[1].b" not in na

    def test_becomes_ready_only_for_the_instance_whose_own_flag_is_set(self):
        space = self._space()
        na = space.next_assignable({"items": [{"a": True}, {"a": False}]})
        assert "items[0].b" in na
        assert "items[1].b" not in na  # items[1].a is False -> b is inactive, never assignable


class TestDriverLoopCoincidence:
    @given(st.data())
    def test_next_assignable_empty_iff_complete(self, data):
        space = data.draw(st.sampled_from([_delivery_routes(), _greenhouse()]))
        seed = data.draw(st.integers(min_value=0, max_value=10_000))
        full = space.sample_dicts(1, seed=seed)[0]
        flat_full = flatten(full, space)
        keys = list(flat_full)
        keep = data.draw(st.lists(st.sampled_from(keys), unique=True, max_size=len(keys)))
        partial = unflatten({k: flat_full[k] for k in keep}, space)

        assert (space.next_assignable(partial) == []) == space.is_complete(partial)

    def test_pending_count(self):
        space = _delivery_routes()
        assert space.next_assignable({}) == ["n_stops"]
        assert not space.is_complete({})

    def test_variant_switch_changes_active_fields(self):
        space = _greenhouse()
        assert (space.next_assignable({"heating": "electric"}) == []) == space.is_complete(
            {"heating": "electric"}
        )
        assert set(space.next_assignable({"heating": "gas"})) == {
            "heating.gas.burner_power_kw",
            "target_temp_c",
        }
        assert not space.is_complete({"heating": "gas"})

    def test_fully_defaulted_space(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).default(0.5))
        full = space.apply_defaults({})
        assert space.next_assignable(full) == []
        assert space.is_complete(full)


class TestRemainingDomainSoundness:
    def test_never_excludes_a_still_feasible_sampled_value(self):
        """Draw many feasible configs; every sampled value for a bound-
        coupled param must lie within `remaining_domain`'s reported bounds
        once its dependencies are known (soundness: never excludes a
        still-feasible value)."""
        space = ds.space(
            ds.param("total").integer(100, 1000),
            ds.param("part").integer(1, ds.param("total")),
        )
        for cfg in space.sample_dicts(200, seed=0):
            rd = space.remaining_domain("part", {"total": cfg["total"]})
            assert rd is not None
            assert rd.lo <= cfg["part"] <= rd.hi

    def test_descriptor_values_validate_against_declared_domain(self):
        space = ds.space(ds.param("color").categorical("red", "green", "blue")).forbid(
            ds.param("color") == "red"
        )
        rd = space.remaining_domain("color", {})
        assert rd is not None
        for v in rd.values:
            assert space.validate_param("color", v).valid

    def test_inactive_param_returns_none(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        assert space.remaining_domain("x", {"flag": False}) is None


class TestReducerPositiveAndNegative:
    def test_bound_origin_narrows_hi(self):
        space = ds.space(
            ds.param("total").integer(0, 1000),
            ds.param("part").integer(0, ds.param("total")),
        )
        rd = space.remaining_domain("part", {"total": 300})
        assert rd is not None
        assert (rd.lo, rd.hi) == (0, 300)

    def test_single_forbid_narrows_across_kinds(self):
        # numeric
        num_space = ds.space(ds.param("x").real(0.0, 10.0)).forbid(ds.param("x") > 5.0)
        rd_num = num_space.remaining_domain("x", {})
        assert rd_num is not None and rd_num.hi == 5.0

        # categorical
        cat_space = ds.space(ds.param("c").categorical("a", "b", "c")).forbid(ds.param("c") == "a")
        rd_cat = cat_space.remaining_domain("c", {})
        assert rd_cat is not None and "a" not in rd_cat.values

        # subset
        sub_space = ds.space(ds.param("s").subset(["a", "b", "c"])).forbid(
            ds.param("s").contains("a")
        )
        rd_sub = sub_space.remaining_domain("s", {})
        assert rd_sub is not None and "a" in rd_sub.forced_out

    def test_two_unset_operand_implication_is_not_propagated(self):
        """A coupling between two *unset* params is CSP propagation, out of
        the one-unset-operand guarantee's scope -- `remaining_domain` must
        leave both sides at their full declared domain rather than attempt
        it."""
        space = ds.space(
            ds.param("x").real(0.0, 10.0),
            ds.param("y").real(0.0, 10.0),
        ).forbid(ds.param("x") > ds.param("y"))
        rd_x = space.remaining_domain("x", {})
        rd_y = space.remaining_domain("y", {})
        assert rd_x is not None and (rd_x.lo, rd_x.hi) == (0.0, 10.0)
        assert rd_y is not None and (rd_y.lo, rd_y.hi) == (0.0, 10.0)


class TestPartialEvalPartition:
    def test_evaluable_includes_determined_and_inactivity_settled(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        ).encourage(ds.param("x") <= 0.5)
        pe = space.evaluate_partial({"flag": False})
        assert len(pe.evaluable_constraints) == 1
        ce = pe.evaluable_constraints[0]
        assert ce.applicable is False and ce.satisfied is None  # settled inapplicable

    def test_pending_when_operand_is_active_unset(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        ).encourage(ds.param("x") <= 0.5)
        pe = space.evaluate_partial({"flag": True})
        assert len(pe.pending_constraints) == 1
        assert len(pe.evaluable_constraints) == 0

    def test_pending_over_a_lift_aggregate_with_unset_instances(self):
        """M10.5/D-71: a constraint aggregating over an *active* lift whose
        own count is determined but whose instance leaves are still unset
        must land in `pending_constraints`, not `evaluable_constraints`
        with `applicable=False`. `c.params` for `bufs.sum() <= 10` holds
        only the *definition* path `"bufs"` (status `"set"` once the count
        is known) — never the `active_unset` instance paths — so the old
        syntactic `status.get(d) in _PENDING_STATUSES for d in c.params`
        scan could never see this case; Unknown's own provenance (rule 5)
        now carries the signal directly."""
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("bufs").integer(0, 100).repeat(ds.param("n")),
        ).require(ds.param("bufs").sum() <= 10)
        pe = space.evaluate_partial({"n": 3})
        assert pe.evaluable_constraints == ()
        assert len(pe.pending_constraints) == 1

    def test_determined_constraint_reports_margin(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).encourage(ds.param("x") <= 0.5)
        pe = space.evaluate_partial({"x": 0.3})
        assert len(pe.evaluable_constraints) == 1
        ce = pe.evaluable_constraints[0]
        assert ce.applicable and ce.satisfied and ce.margin == 0.2

    def test_n_remaining_counts_active_unset(self):
        space = ds.space(
            ds.param("a").real(0.0, 1.0),
            ds.param("b").real(0.0, 1.0),
        )
        pe = space.evaluate_partial({"a": 0.1})
        assert pe.n_remaining == 1
