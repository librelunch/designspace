"""Conformance laws: partial configs (API.md, "Space: Partial Configs").

Laws enforced here: `activity_collapse`, `driver_loop_coincidence`,
`remaining_domain_soundness`, `one_unset_operand_reduction`,
`no_multi_operand_propagation`, `partial_eval_partition`.
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


def _lifted_choice() -> Space:
    return ds.space(
        ds.param("c").choice(a=ds.space(), b=ds.space(ds.param("v").integer(1, 5))).repeat(2)
    )


def _sibling_gated_lift() -> Space:
    element = ds.space(
        ds.param("flag").bool(),
        ds.param("x").integer(1, 9).when(ds.param("flag")),
    )
    return ds.space(ds.param("ws").space(element).repeat(2))


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
        # `compute_activity` also assigns a harmless, unused activity entry
        # to a lift descendant template itself, such as "stops[].location",
        # its topological walk not filtering them. The partial status map,
        # which covers real params and instances only, omits them. Compare
        # over the params
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

    def test_an_element_gated_on_its_own_instance_is_reported(self):
        """A lift element's own condition reads a sibling of that instance:
        a lifted choice's discriminator, or a struct field's `when` on
        another field of the same element. The payload behind it is active
        once that sibling is set, so the loop must report it and completeness
        must wait for it.
        """
        for space, discriminated in (
            (_lifted_choice(), {"c[0]": "b", "c[1]": "b"}),
            (_sibling_gated_lift(), {"ws[0].flag": True, "ws[1].flag": True}),
        ):
            assert not space.is_complete(discriminated)
            assert (space.next_assignable(discriminated) == []) == space.is_complete(discriminated)

    def test_an_element_gated_on_its_own_instance_is_reported_from_empty(self):
        """The same law at the start of the loop, before any leaf is set:
        the gating sibling is what is assignable, and nothing is complete."""
        for space in (_lifted_choice(), _sibling_gated_lift()):
            assert (space.next_assignable({}) == []) == space.is_complete({})

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
        """An aggregate over unset instance leaves is pending, not evaluable.

        A constraint aggregating over an active lift whose own count is
        determined but whose instance leaves are still unset lands in
        `pending_constraints` rather than in `evaluable_constraints` with
        `applicable=False`.

        A syntactic scan over `c.params` cannot see this case: for
        `bufs.sum() <= 10` that holds only the definition path `"bufs"`,
        whose status is `"set"` once the count is known, and never the
        `active_unset` instance paths. Unknown's own provenance, under rule
        5, carries the signal instead.
        """
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


class TestActiveEmptyLiftIsAssignable:
    """An active lift carries its key, and the driver loop produces it.

    Presence marks activity: an active lift is present in a complete
    config, holding one element per unit of its count, and holds `[]`
    when that count is zero. Absence marks inactivity and nothing else,
    so a reader never has to tell an inactive lift from an empty one.

    A count of zero is the case that has to be assigned deliberately.
    Every other count leaves instance leaves to assign, and assigning
    them creates the container on the way. With no leaf to assign,
    nothing creates it, so the container itself is what
    `next_assignable` reports. This is the one place a container is
    assignable and the one place its own status is `active_unset`.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("on").bool(),
            ds.param("n").integer(0, 3),
            ds.param("items")
            .space(ds.space(ds.param("v").integer(1, 9)))
            .repeat(ds.param("n"))
            .when(ds.param("on")),
        )

    def test_zero_count_container_is_assignable(self):
        space = self._space()
        config = {"on": True, "n": 0}
        assert space.next_assignable(config) == ["items"]
        assert space.missing_params(config) == ["items"]
        assert not space.is_complete(config)

    def test_assigning_the_empty_list_completes_it(self):
        space = self._space()
        config = {"on": True, "n": 0, "items": []}
        assert space.next_assignable(config) == []
        assert space.is_complete(config)
        assert space.validate(config).valid

    def test_stripping_an_empty_list_reopens_it(self):
        """The empty list is what completeness was waiting on, not nothing."""
        space = self._space()
        empty = [
            config
            for seed in range(60)
            for config in [space.sample_one(seed=seed)]
            if config["on"] and config["n"] == 0
        ]
        assert empty, "never drew the active zero-length case"
        for config in empty:
            assert config["items"] == []
            assert space.is_complete(config)
            stripped = {k: v for k, v in config.items() if k != "items"}
            assert space.next_assignable(stripped) == ["items"]
            assert not space.is_complete(stripped)

    def test_an_inactive_lift_stays_absent(self):
        space = self._space()
        config = {"on": False, "n": 0}
        assert space.next_assignable(config) == []
        assert space.is_complete(config)
        assert space.validate(config).valid
        assert "items" not in config

    def test_a_nonzero_count_still_assigns_leaves_not_the_container(self):
        space = self._space()
        assert space.next_assignable({"on": True, "n": 2}) == ["items[0].v", "items[1].v"]

    def test_a_static_zero_count_behaves_the_same(self):
        space = ds.space(
            ds.param("items").space(ds.space(ds.param("v").integer(1, 9))).repeat(0),
        )
        assert space.next_assignable({}) == ["items"]
        assert not space.is_complete({})
        assert space.is_complete({"items": []})


class TestPartialSurfaceAcceptsEitherSpelling:
    """The partial-config surface reads a flat config as well as a nested one.

    Every one of these reports instance paths, which is the flat
    vocabulary, so a driver loop naturally accumulates its answers in a
    flat dict. Reading that back has to mean the same thing as reading
    the nested form, or the loop's own bookkeeping is misread. It was:
    a flat config was flattened a second time, which drops every lift
    key, and completeness then came back false for a complete config.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("n").integer(0, 3),
            ds.param("workers")
            .space(ds.space(ds.param("timeout_s").integer(1, 3600)))
            .repeat(ds.param("n")),
        )

    def _both(self, space, nested):
        return nested, flatten(nested, space)

    def test_completeness_agrees_across_spellings(self):
        space = self._space()
        nested = {"n": 2, "workers": [{"timeout_s": 30}, {"timeout_s": 900}]}
        for config in self._both(space, nested):
            assert space.is_complete(config)
            assert space.next_assignable(config) == []
            assert space.missing_params(config) == []

    def test_incompleteness_agrees_across_spellings(self):
        space = self._space()
        nested = {"n": 2, "workers": [{"timeout_s": 30}]}
        for config in self._both(space, nested):
            assert not space.is_complete(config)
            assert space.next_assignable(config) == ["workers[1].timeout_s"]

    def test_activity_agrees_across_spellings(self):
        space = self._space()
        nested = {"n": 1, "workers": [{"timeout_s": 30}]}
        nested_status, flat_status = (space.param_activity(c) for c in self._both(space, nested))
        assert nested_status == flat_status

    def test_evaluate_partial_agrees_across_spellings(self):
        space = self._space()
        nested = {"n": 1, "workers": [{"timeout_s": 30}]}
        a, b = (space.evaluate_partial(c) for c in self._both(space, nested))
        assert a.param_status == b.param_status
        assert a.n_remaining == b.n_remaining

    def test_a_loop_driven_in_flat_form_terminates_and_validates(self):
        """The whole point: assign what it reports, where it reports it."""
        space = self._space()
        config: dict = {"n": 2}
        for _ in range(10):
            assignable = space.next_assignable(config)
            if not assignable:
                break
            for path in assignable:
                config[path] = 30
        else:
            raise AssertionError("the loop did not terminate")
        assert space.is_complete(config)
        assert space.validate(unflatten(config, space)).valid

    def test_a_loop_over_an_element_gated_on_its_own_instance_completes(self):
        """The container key is `flatten`'s bookkeeping, and a loop building
        its own flat config never writes one. API.md, "Space: Partial
        Configs" says assigning an instance leaf creates the container on the
        way, so a determined count above zero needs nothing further: an
        element condition reading a sibling of its own instance resolves
        against the leaves alone.
        """
        for space, value in ((_lifted_choice(), "b"), (_sibling_gated_lift(), True)):
            config: dict = {}
            for _ in range(10):
                assignable = space.next_assignable(config)
                if not assignable:
                    break
                for path in assignable:
                    config[path] = value if space.param_def(path).type_kind != "integer" else 3
            else:
                raise AssertionError("the loop did not terminate")
            assert space.is_complete(config)
            assert space.validate(unflatten(config, space)).valid

    def test_a_space_without_lifts_reads_the_same_either_way(self):
        space = ds.space(ds.param("a").integer(0, 4), ds.param("b").real(0.0, 1.0))
        config = {"a": 1, "b": 0.5}
        assert flatten(config, space) == config
        assert space.is_complete(config)
