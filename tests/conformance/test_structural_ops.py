"""Conformance laws: M8 structural operations (API.md, "Space — Structural
Operations"; PLAN.md M8 gate; DECISIONS.md D-44).

Gate items covered here: slice-substitution reaches conditions and
constraint expressions incl. bound-origin and require-origin (envelope
recompute test); select prefix-subtree brings variants; strict vs
best-effort; `extend` identity with `ds.space()`; rebuilt (post-op) spaces
fingerprint-equal to equivalent hand-built ones.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import IntegerDomain, ListDomain, RealDomain

# -- slice --------------------------------------------------------------------


class TestSlice:
    def test_removes_param(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").integer(0, 10))
        sliced = space.slice(y=5)
        assert set(sliced.params) == {"x"}

    def test_substitutes_into_condition(self):
        space = ds.space(
            ds.param("g").integer(0, 10),
            ds.param("x").real(0.0, 1.0).when(ds.param("g") > 5),
        )
        active = space.slice(g=8)
        # g > 5 is now `8 > 5` -- always active regardless of any config value.
        assert active.is_feasible({"x": 0.5})
        inactive = space.slice(g=2)
        assert set(inactive.params) == {"x"}
        # g is gone but x's own condition (now `2 > 5`, i.e. never active)
        # still resolves -- x should never need a value.
        assert inactive.is_feasible({})

    def test_substitutes_into_forbid_constraint(self):
        space = ds.space(ds.param("x").integer(0, 10), ds.param("y").integer(0, 10)).forbid(
            ds.param("x") > ds.param("y")
        )
        sliced = space.slice(x=8)
        assert sliced.is_feasible({"y": 9})
        assert not sliced.is_feasible({"y": 5})

    def test_substitutes_into_require_constraint(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").real(0.0, 1.0)).require(
            ds.param("x") <= ds.param("y")
        )
        sliced = space.slice(x=0.3)
        assert sliced.is_feasible({"y": 0.5})
        assert not sliced.is_feasible({"y": 0.1})

    def test_bound_origin_envelope_recompute(self):
        # y's declared bound is `y <= x`; slicing x to a fixed value must
        # recompute y's envelope from the loose [0, 10] hull down to the
        # tight [0, 5] the fixed x implies (API.md: "envelopes recompute
        # on re-resolution").
        space = ds.space(ds.param("x").real(0.0, 10.0), ds.param("y").real(0.0, ds.param("x")))
        sliced = space.slice(x=5.0)
        domain = sliced.params["y"].domain
        assert isinstance(domain, RealDomain)
        assert domain.lo == pytest.approx(0.0)
        assert domain.hi == pytest.approx(5.0)
        # The bound-origin constraint itself is substituted too.
        for cfg, expected in (({"y": 5.0}, True), ({"y": 6.0}, False)):
            assert sliced.is_feasible(cfg) is expected

    def test_bound_origin_envelope_recompute_integer(self):
        space = ds.space(ds.param("n").integer(0, 20), ds.param("k").integer(0, ds.param("n")))
        sliced = space.slice(n=7)
        domain = sliced.params["k"].domain
        assert isinstance(domain, IntegerDomain)
        assert domain.lo == 0
        assert domain.hi == 7

    def test_chained_bound_partial_substitution(self):
        # z <= x + w; slicing only x leaves a fresh expression bound over w.
        space = ds.space(
            ds.param("x").real(0.0, 10.0),
            ds.param("w").real(0.0, 5.0),
            ds.param("z").real(0.0, ds.param("x") + ds.param("w")),
        )
        sliced = space.slice(x=2.0)
        domain = sliced.params["z"].domain
        assert isinstance(domain, RealDomain)
        assert domain.hi == pytest.approx(7.0)  # 2.0 + [0, 5] hull

    def test_rebuilt_fingerprint_equal_to_hand_built(self):
        # Fingerprint identity is structural, not semantic (API.md,
        # "fingerprint()"): the sliced space still carries a (now
        # redundant-looking) bound-origin constraint from the original
        # expression bound, canonicalized by operator-flip like any other
        # bound — so the equivalent hand-built space needs the matching
        # `.forbid(y > 5.0)`, not bare literal bounds alone.
        sliced = ds.space(
            ds.param("x").real(0.0, 10.0), ds.param("y").real(0.0, ds.param("x"))
        ).slice(x=5.0)
        hand_built = ds.space(ds.param("y").real(0.0, 5.0)).forbid(ds.param("y") > 5.0)
        assert sliced.fingerprint("full") == hand_built.fingerprint("full")

    def test_invalid_value_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError):
            space.slice(x=5.0)

    def test_container_param_raises(self):
        space = ds.space(ds.param("s").space(ds.param("inner").integer(0, 5)))
        with pytest.raises(ResolutionError):
            space.slice(s={"inner": 1})

    def test_positional_dict_form_for_dotted_path(self):
        space = ds.space(ds.param("cfg").space(ds.param("depth").integer(1, 10)))
        sliced = space.slice({"cfg.depth": 5})
        assert "cfg.depth" not in sliced.params
        assert "cfg" in sliced.params

    def test_no_paths_raises_typeerror(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(TypeError):
            space.slice()

    def test_slicing_a_choice_discriminator_permanently_deactivates_other_variants(self):
        # .slice() only removes the *named* param; a sibling variant's
        # descendant, still declared, sees its own folded discriminator
        # condition substituted to a constant-false comparison ("dpll" ==
        # "cdcl") -- permanently inactive (Kleene rule 3), never sampled,
        # rather than being cascade-removed.
        space = ds.space(
            ds.param("solver").choice(
                "dpll", cdcl=ds.space(ds.param("restart").categorical("luby", "geometric"))
            ),
        )
        sliced = space.slice(solver="dpll")
        assert "solver.cdcl.restart" in sliced.params
        for cfg in sliced.sample_dicts(20, seed=0):
            assert cfg == {}
            assert sliced.validate(cfg).valid


class TestSliceAnchors:
    def test_matching_anchor_key_is_stripped_and_kept(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").integer(0, 10)).anchor(
            {"a": {"x": 0.5, "y": 5}}
        )
        sliced = space.slice(y=5)
        assert sliced.anchors == {"a": {"x": 0.5}}

    def test_conflicting_anchor_value_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").integer(0, 10)).anchor(
            {"a": {"x": 0.5, "y": 5}}
        )
        with pytest.raises(ResolutionError, match=r"anchor 'a'.*row 22"):
            space.slice(y=3)


# -- freeze ---------------------------------------------------------------------


class TestFreeze:
    def test_keeps_param_narrows_domain_real(self):
        space = ds.space(ds.param("x").real(0.0, 10.0))
        frozen = space.freeze(x=5.0)
        assert "x" in frozen.params
        domain = frozen.params["x"].domain
        assert isinstance(domain, RealDomain)
        assert (domain.lo, domain.hi) == (5.0, 5.0)
        assert frozen.params["x"].default == 5.0

    def test_keeps_param_narrows_domain_integer(self):
        frozen = ds.space(ds.param("n").integer(0, 10)).freeze(n=3)
        domain = frozen.params["n"].domain
        assert isinstance(domain, IntegerDomain)
        assert (domain.lo, domain.hi) == (3, 3)

    def test_narrows_categorical(self):
        frozen = ds.space(ds.param("c").categorical("a", "b", "c")).freeze(c="b")
        assert frozen.sample_dicts(20, seed=0) == [{"c": "b"}] * 20

    def test_narrows_ordinal(self):
        frozen = ds.space(ds.param("o").ordinal("lo", "mid", "hi")).freeze(o="mid")
        assert all(cfg["o"] == "mid" for cfg in frozen.sample_dicts(20, seed=0))

    def test_pins_bool_via_require(self):
        frozen_true = ds.space(ds.param("b").bool()).freeze(b=True)
        assert all(cfg["b"] is True for cfg in frozen_true.sample_dicts(20, seed=0))
        frozen_false = ds.space(ds.param("b").bool()).freeze(b=False)
        assert all(cfg["b"] is False for cfg in frozen_false.sample_dicts(20, seed=0))

    def test_conditions_use_the_fixed_value(self):
        space = ds.space(
            ds.param("x").integer(0, 10),
            ds.param("y").real(0.0, 1.0).when(ds.param("x") > 5),
        )
        frozen = space.freeze(x=8)
        assert frozen.is_feasible({"x": 8, "y": 0.5})

    def test_invalid_value_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError):
            space.freeze(x=5.0)


class TestFreezeAnchors:
    def test_conflicting_anchor_raises(self):
        space = ds.space(ds.param("x").integer(0, 10)).anchor({"a": {"x": 5}})
        with pytest.raises(ResolutionError, match=r"anchor 'a'.*row 22"):
            space.freeze(x=3)

    def test_matching_anchor_survives(self):
        space = ds.space(ds.param("x").integer(0, 10)).anchor({"a": {"x": 5}})
        frozen = space.freeze(x=5)
        assert frozen.anchors == {"a": {"x": 5}}


# -- freeze: subset / permutation / struct / choice / list (M9.5, DECISIONS.md D-50) --


class TestFreezeSubset:
    def test_fingerprint_equal_to_hand_written_pins(self):
        items = ("a", "b", "c", "d")

        def build():
            return ds.space(ds.param("s").subset(items, min_size=1, max_size=3))

        frozen = build().freeze(s=["a", "c"])
        hand_built = ds.space(
            ds.param("s").subset(items, min_size=1, max_size=3).default(["a", "c"]),
        ).require(
            ds.param("s").contains("a"),
            ~ds.param("s").contains("b"),
            ds.param("s").contains("c"),
            ~ds.param("s").contains("d"),
        )
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_samples_and_validates_only_the_fixed_membership(self):
        space = ds.space(ds.param("s").subset(("a", "b", "c"), min_size=1))
        frozen = space.freeze(s=["a", "c"])
        for cfg in frozen.sample_dicts(20, seed=0):
            assert sorted(cfg["s"]) == ["a", "c"]
        assert frozen.validate({"s": ["a", "c"]}).valid
        assert not frozen.validate({"s": ["a", "b"]}).valid

    def test_wrong_item_raises(self):
        space = ds.space(ds.param("s").subset(("a", "b", "c")))
        with pytest.raises(ResolutionError):
            space.freeze(s=["a", "z"])

    def test_out_of_size_bounds_raises(self):
        space = ds.space(ds.param("s").subset(("a", "b", "c"), max_size=2))
        with pytest.raises(ResolutionError):
            space.freeze(s=["a", "b", "c"])


class TestFreezePermutation:
    def test_fingerprint_equal_to_hand_written_pins(self):
        items = ("a", "b", "c")

        def build():
            return ds.space(ds.param("p").permutation(items))

        order = ["c", "a", "b"]
        frozen = build().freeze(p=order)
        hand_built = ds.space(
            ds.param("p").permutation(items).default(order),
        ).require(
            ds.param("p").position_of("c") == 0,
            ds.param("p").position_of("a") == 1,
            ds.param("p").position_of("b") == 2,
        )
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_samples_and_validates_only_the_fixed_order(self):
        space = ds.space(ds.param("p").permutation(("a", "b", "c")))
        frozen = space.freeze(p=["c", "a", "b"])
        for cfg in frozen.sample_dicts(20, seed=0):
            assert cfg["p"] == ["c", "a", "b"]
        assert frozen.validate({"p": ["c", "a", "b"]}).valid
        assert not frozen.validate({"p": ["a", "b", "c"]}).valid

    def test_wrong_length_raises(self):
        space = ds.space(ds.param("p").permutation(("a", "b", "c")))
        with pytest.raises(ResolutionError):
            space.freeze(p=["a", "b"])


class TestFreezeChoice:
    def _build(self):
        return ds.space(
            ds.param("algo").choice(
                "linear",
                svm=ds.space(ds.param("gamma").real(1e-5, 10.0)),
            ),
        )

    def test_fingerprint_equal_to_hand_written_pin_and_prune_for_payload_variant(self):
        # ".select()" brings a *whole* choice's variants (API.md), so it can
        # only stand in for freeze's own pruning when the surviving variant
        # is the payload-bearing one being kept, not the bare one (whose
        # hand-written equivalent would need `ChoiceDomain` itself to omit
        # "svm" — which freeze deliberately never does; see
        # test_bare_variant_prunes_payload_descendants below instead).
        space = self._build()
        frozen = space.freeze(algo="svm")
        hand_built = self._build().select("algo.svm.gamma").require(ds.param("algo") == "svm")
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_bare_variant_prunes_payload_descendants(self):
        space = self._build()
        frozen = space.freeze(algo="linear")
        assert "algo.svm.gamma" not in frozen.params
        assert frozen.n_params == 1

    def test_samples_only_the_fixed_variant(self):
        space = self._build()
        frozen = space.freeze(algo="linear")
        assert all(cfg["algo"] == "linear" for cfg in frozen.sample_dicts(20, seed=0))

    def test_payload_field_still_freely_sampled_unless_also_frozen(self):
        space = self._build()
        frozen = space.freeze(algo="svm")
        values = {cfg["algo"]["svm"]["gamma"] for cfg in frozen.sample_dicts(20, seed=0)}
        assert len(values) > 1

    def test_can_also_pin_a_payload_field_in_the_same_call(self):
        space = self._build()
        frozen = space.freeze(algo="svm", **{"algo.svm.gamma": 1.0})
        for cfg in frozen.sample_dicts(10, seed=0):
            assert cfg["algo"] == {"svm": {"gamma": 1.0}}

    def test_bad_variant_name_raises(self):
        space = self._build()
        with pytest.raises(ResolutionError):
            space.freeze(algo="not-a-variant")

    def test_conflicting_anchor_dropped_with_warning_not_hard_fail(self):
        # Choice is the only kind that removes params, so it uses
        # .select()'s strip/drop anchor machinery, not the hard-fail
        # _revalidate_anchors_unchanged_shape every other kind still uses.
        space = self._build().anchor({"a": {"algo": {"svm": {"gamma": 1.0}}}})
        with pytest.warns(UserWarning):
            frozen = space.freeze(algo="linear")
        assert "a" not in frozen.anchors

    def test_matching_anchor_survives_pruning(self):
        space = self._build().anchor({"a": {"algo": "linear"}})
        frozen = space.freeze(algo="linear")
        assert frozen.anchors == {"a": {"algo": "linear"}}


class TestFreezeStruct:
    def _build(self):
        return ds.space(
            ds.param("zone").space(
                ds.param("area_m2").real(1.0, 1000.0),
                ds.param("shade_cloth").bool(),
            ),
        )

    def test_fans_out_to_per_field_freeze(self):
        space = self._build()
        frozen = space.freeze(zone={"area_m2": 500.0, "shade_cloth": True})
        for cfg in frozen.sample_dicts(20, seed=0):
            assert cfg["zone"] == {"area_m2": 500.0, "shade_cloth": True}

    def test_fingerprint_equal_to_hand_written_per_field_freeze(self):
        space = self._build()
        frozen = space.freeze(zone={"area_m2": 500.0, "shade_cloth": True})
        hand_built = self._build().freeze(**{"zone.area_m2": 500.0, "zone.shade_cloth": True})
        assert frozen.fingerprint("full") == hand_built.fingerprint("full")

    def test_partial_dict_leaves_other_field_free(self):
        space = self._build()
        frozen = space.freeze(zone={"area_m2": 500.0})
        values = {cfg["zone"]["shade_cloth"] for cfg in frozen.sample_dicts(20, seed=0)}
        assert values == {True, False}

    def test_foreign_field_name_raises(self):
        space = self._build()
        with pytest.raises(ResolutionError):
            space.freeze(zone={"not_a_field": 1})

    def test_nested_struct_of_struct(self):
        space = ds.space(
            ds.param("outer").space(
                ds.param("inner").space(ds.param("v").integer(0, 10)),
            ),
        )
        frozen = space.freeze(outer={"inner": {"v": 7}})
        assert all(cfg["outer"]["inner"]["v"] == 7 for cfg in frozen.sample_dicts(10, seed=0))


class TestFreezeList:
    def test_count_and_list_default_set(self):
        frozen = ds.space(ds.param("xs").real(0.0, 1.0).repeat(3)).freeze(xs=[0.1, 0.2, 0.3])
        domain = frozen.params["xs"].domain
        assert isinstance(domain, ListDomain)
        assert domain.count == 3
        assert domain.list_default == [0.1, 0.2, 0.3]

    def test_literal_count_mismatch_raises(self):
        space = ds.space(ds.param("xs").real(0.0, 1.0).repeat(4))
        with pytest.raises(ResolutionError):
            space.freeze(xs=[0.1, 0.2])

    def test_scalar_elements_pinned(self):
        # A discrete (categorical) domain, not real: an exact-equality pin
        # over a continuous domain is measure-zero under rejection sampling
        # (API.md, "Continuous-equality warning") — orthogonal to freeze
        # itself (any hand-written `require(x == v)` over a continuous
        # param has the same property); a small discrete domain keeps this
        # test's sampling reliable.
        frozen = ds.space(ds.param("xs").categorical("a", "b", "c").repeat(4)).freeze(
            xs=["a", "b", "c", "a"]
        )
        for cfg in frozen.sample_dicts(10, seed=0):
            assert cfg["xs"] == ["a", "b", "c", "a"]

    def test_element_pins_are_separate_require_constraints(self):
        # Each element is its own hard `require` pin (mirroring
        # `_require_pin`'s uniform shape across every freeze kind) rather
        # than one combined expression — matching subset/permutation/
        # choice's own per-item/per-position/per-instance pin shape.
        frozen = ds.space(ds.param("xs").categorical("a", "b", "c").repeat(3)).freeze(
            xs=["a", "b", "c"]
        )
        assert len(frozen.constraints) == 3
        for c in frozen.constraints:
            assert c.kind == "require"
            assert c.hard is True

    def test_dynamic_count_narrows_and_leaves_driver_param_free(self):
        space = ds.space(
            ds.param("n").integer(1, 5),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )
        frozen = space.freeze(xs=[0.5, 0.5])
        domain = frozen.params["xs"].domain
        assert isinstance(domain, ListDomain)
        assert domain.count == 2
        int_domain = frozen.params["n"].domain
        assert isinstance(int_domain, IntegerDomain)
        assert (int_domain.lo, int_domain.hi) == (1, 5)

    def test_list_of_struct_elements(self):
        # Small discrete ranges (not delivery_routes-shaped 0-9/5-30): four
        # independent per-field equality pins under naive rejection sampling
        # need a high enough per-pin match probability to be reliable within
        # the sampler's fixed retry budget (`sample/_sample.py::_MAX_RETRIES`).
        stop = ds.space(ds.param("location").integer(0, 2), ds.param("dwell_min").integer(0, 2))
        space = ds.space(ds.param("stops").space(stop).repeat(2))
        frozen = space.freeze(
            stops=[{"location": 0, "dwell_min": 1}, {"location": 2, "dwell_min": 0}]
        )
        for cfg in frozen.sample_dicts(10, seed=0):
            assert cfg["stops"] == [
                {"location": 0, "dwell_min": 1},
                {"location": 2, "dwell_min": 0},
            ]

    def _pipeline_space(self, count: int):
        return ds.space(
            ds.param("pipeline")
            .choice(
                "shuffle",
                "crossover",
                mutation=ds.space(ds.param("rate").real(0.01, 0.5)),
                local_search=ds.space(ds.param("iters").integer(1, 100)),
            )
            .repeat(count),
        )

    def test_list_of_choice_prunes_variant_selected_by_no_instance(self):
        space = self._pipeline_space(3)
        frozen = space.freeze(pipeline=["shuffle", "local_search", "crossover"])
        assert "pipeline[].mutation.rate" not in frozen.params
        assert "pipeline[].local_search.iters" in frozen.params

    def test_list_of_choice_union_rule_keeps_variant_used_by_any_instance(self):
        space = self._pipeline_space(2)
        frozen = space.freeze(pipeline=["mutation", "local_search"])
        # Each instance uses only one of the two payload-bearing variants,
        # but the union across both instances uses both — neither is
        # pruned (the aggregation is over the whole call, not per-instance).
        assert "pipeline[].mutation.rate" in frozen.params
        assert "pipeline[].local_search.iters" in frozen.params

    def test_list_of_choice_prunes_even_when_uniformly_selected(self):
        # Every instance picks the same variant — proving the union is
        # computed once over the whole call: the pruning of "mutation"
        # doesn't depend on any single instance "driving" it alone.
        space = self._pipeline_space(2)
        frozen = space.freeze(pipeline=["local_search", "local_search"])
        assert "pipeline[].mutation.rate" not in frozen.params
        assert "pipeline[].local_search.iters" in frozen.params

    def test_list_of_choice_samples_only_the_fixed_sequence(self):
        space = self._pipeline_space(3)
        frozen = space.freeze(pipeline=["shuffle", "local_search", "crossover"])
        for cfg in frozen.sample_dicts(10, seed=0):
            variants = [next(iter(op)) if isinstance(op, dict) else op for op in cfg["pipeline"]]
            assert variants == ["shuffle", "local_search", "crossover"]

    def test_nested_list_of_list(self):
        # Discrete (integer), not real -- same measure-zero-under-rejection
        # reasoning as test_scalar_elements_pinned above.
        space = ds.space(ds.param("m").integer(0, 2).repeat(2).repeat(2))
        frozen = space.freeze(m=[[0, 1], [2, 0]])
        for cfg in frozen.sample_dicts(10, seed=0):
            assert cfg["m"] == [[0, 1], [2, 0]]


# -- active_subspace --------------------------------------------------------


class TestActiveSubspace:
    def test_drops_inactive_branch(self):
        space = ds.space(
            ds.param("g").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("g")),
        )
        sub = space.active_subspace({"g": False})
        assert "x" not in sub.params
        assert "g" in sub.params

    def test_keeps_active_branch(self):
        space = ds.space(
            ds.param("g").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("g")),
        )
        sub = space.active_subspace({"g": True, "x": 0.5})
        assert set(sub.params) == {"g", "x"}

    def test_choice_variant(self):
        space = ds.space(
            ds.param("solver").choice(
                "dpll", cdcl=ds.space(ds.param("restart").categorical("luby", "geometric"))
            )
        )
        sub = space.active_subspace({"solver": {"cdcl": {"restart": "luby"}}})
        assert "solver.cdcl.restart" in sub.params


# -- select / filter --------------------------------------------------------


class TestSelect:
    def test_selecting_a_nested_path_brings_back_its_ancestor_containers(self):
        # Selecting "cfg.inner" alone (skipping its enclosing struct "cfg")
        # would otherwise leave it unreachable via ordinary flatten/sample
        # traversal, which walks top-down through declared containers.
        space = ds.space(
            ds.param("cfg").space(
                ds.param("inner").choice("a", b=ds.space(ds.param("x").integer(0, 5))),
                ds.param("unrelated").bool(),
            ),
        )
        sel = space.select("cfg.inner")
        assert set(sel.params) == {"cfg", "cfg.inner", "cfg.inner.b.x"}
        assert "cfg.unrelated" not in sel.params  # ancestor's other field not dragged in
        for cfg in sel.sample_dicts(20, seed=0):
            assert sel.validate(cfg).valid

    def test_prefix_subtree_brings_variants(self):
        space = ds.space(
            ds.param("solver").choice(
                "dpll", cdcl=ds.space(ds.param("restart").categorical("luby", "geometric"))
            ),
            ds.param("timeout_s").integer(1, 100),
        )
        sel = space.select("solver")
        assert set(sel.params) == {"solver", "solver.cdcl.restart"}

    def test_prefix_subtree_brings_a_lifted_structs_element_templates(self):
        # A lifted struct's fields are relocated under a `"[]"`-bracketed
        # prefix, so they are descendants of the lift exactly as a
        # variant's params are descendants of its choice — "prefix
        # subtree" has to bring them, or the selected lift keeps a
        # ListDomain whose element fields no longer exist.
        space = ds.space(
            ds.param("layers")
            .space(
                ds.param("width").integer(16, 1024),
                ds.param("act").categorical("relu", "gelu"),
            )
            .repeat(3),
            ds.param("timeout_s").integer(1, 100),
        )
        sel = space.select("layers")
        assert set(sel.params) == {"layers", "layers[].width", "layers[].act"}
        for cfg in sel.sample_dicts(10, seed=0):
            assert sel.validate(cfg).valid

    def test_prefix_subtree_brings_a_lifted_choices_variants(self):
        space = ds.space(
            ds.param("pipeline")
            .choice("shuffle", pmx=ds.space(ds.param("swap_p").real(0.0, 1.0)))
            .repeat(2),
            ds.param("timeout_s").integer(1, 100),
        )
        sel = space.select("pipeline")
        assert set(sel.params) == {"pipeline", "pipeline[].pmx.swap_p"}
        for cfg in sel.sample_dicts(10, seed=0):
            assert sel.validate(cfg).valid

    def test_best_effort_drops_with_warning(self):
        space = ds.space(ds.param("x").integer(0, 10), ds.param("y").integer(0, 10)).forbid(
            ds.param("x") > ds.param("y")
        )
        with pytest.warns(UserWarning):
            sel = space.select("x")
        assert sel.constraints == ()

    def test_strict_raises_instead_of_dropping(self):
        space = ds.space(ds.param("x").integer(0, 10), ds.param("y").integer(0, 10)).forbid(
            ds.param("x") > ds.param("y")
        )
        with pytest.raises(ResolutionError):
            space.select("x", strict=True)

    def test_no_paths_raises_typeerror(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(TypeError):
            space.select()

    def test_unknown_path_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError):
            space.select("nonesuch")


class TestFilter:
    def test_any_mode(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).tag("perf"),
            ds.param("y").real(0.0, 1.0).tag("safety"),
        )
        filtered = space.filter(tags=("perf",))
        assert set(filtered.params) == {"x"}

    def test_all_mode(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).tag("perf", "core"),
            ds.param("y").real(0.0, 1.0).tag("perf"),
        )
        filtered = space.filter(tags=("perf", "core"), mode="all")
        assert set(filtered.params) == {"x"}

    def test_bad_mode_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).tag("perf"))
        with pytest.raises(TypeError):
            space.filter(tags=("perf",), mode="bogus")

    def test_strict_raises(self):
        space = ds.space(
            ds.param("x").real(0.0, 1.0).tag("perf"), ds.param("y").real(0.0, 1.0)
        ).forbid(ds.param("x") > ds.param("y"))
        with pytest.raises(ResolutionError):
            space.filter(tags=("perf",), strict=True)


class TestSelectFilterAnchors:
    def test_conflicting_anchor_key_dropped_with_warning(self):
        space = ds.space(ds.param("x").real(0.0, 1.0), ds.param("y").integer(0, 10)).anchor(
            {"a": {"x": 0.5, "y": 5}}
        )
        with pytest.warns(UserWarning):
            sel = space.select("x")
        assert sel.anchors == {"a": {"x": 0.5}}


# -- extend -----------------------------------------------------------------


class TestExtend:
    def test_adds_new_params(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        extended = space.extend(ds.param("y").integer(0, 10))
        assert set(extended.params) == {"x", "y"}

    def test_empty_extend_is_identity(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.5)
        assert space.extend().fingerprint("full") == space.fingerprint("full")

    def test_new_expr_can_reference_existing_param(self):
        space = ds.space(ds.param("g").bool())
        extended = space.extend(ds.param("x").real(0.0, 1.0).when(ds.param("g")))
        assert extended.is_feasible({"g": False})
        assert extended.is_feasible({"g": True, "x": 0.5})

    def test_duplicate_path_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(ResolutionError):
            space.extend(ds.param("x").integer(0, 5))

    def test_keeps_and_revalidates_anchors_when_still_valid(self):
        # A new param that stays inactive for the anchor's own config (here,
        # gated on a condition the anchor's x value never satisfies) does
        # not invalidate the anchor -- `.validate()` never requires an
        # inactive param's value.
        space = ds.space(ds.param("x").real(0.0, 1.0)).anchor({"a": {"x": 0.5}})
        extended = space.extend(ds.param("y").integer(0, 10).when(ds.param("x") > 100.0))
        assert extended.anchors == {"a": {"x": 0.5}}

    def test_extend_with_new_required_param_invalidates_anchor(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).anchor({"a": {"x": 0.5}})
        with pytest.raises(ResolutionError, match=r"anchor 'a'.*row 22"):
            space.extend(ds.param("y").integer(0, 10))
