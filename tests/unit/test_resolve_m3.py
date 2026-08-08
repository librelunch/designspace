"""Builder and resolve mechanics for choice, struct, subset and permutation.

Covers what `tests/conformance/test_structure.py` does not.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import ChoiceDomain, PermutationDomain, StructDomain, SubsetDomain


class TestSubsetDomain:
    def test_resolves(self):
        space = ds.space(ds.param("s").subset(("a", "b", "c"), min_size=1, max_size=2))
        assert space.params["s"].domain == SubsetDomain(("a", "b", "c"), 1, 2)

    def test_default_size_bounds(self):
        space = ds.space(ds.param("s").subset(("a", "b")))
        assert space.params["s"].domain == SubsetDomain(("a", "b"), 0, None)

    # Error-table row 28, nonsensical size bounds, in both its forms.
    def test_min_size_negative_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "b"), min_size=-1))

    def test_max_size_below_min_size_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "b"), min_size=2, max_size=1))

    def test_min_size_exceeds_universe_raises(self):
        with pytest.raises(ResolutionError, match="'s'"):
            ds.space(ds.param("s").subset(("a", "b"), min_size=3))

    def test_empty_item_universe_is_legal(self):
        space = ds.space(ds.param("s").subset(()))
        assert space.params["s"].domain.items == ()


class TestPermutationDomain:
    def test_resolves(self):
        space = ds.space(ds.param("p").permutation(("a", "b", "c")))
        assert space.params["p"].domain == PermutationDomain(("a", "b", "c"))

    def test_prior_unsupported(self):
        with pytest.raises(ResolutionError, match="'p'"):
            ds.space(ds.param("p").permutation(("a", "b")).prior(weights=[1.0, 2.0]))

    def test_zero_or_one_item_is_legal(self):
        space = ds.space(ds.param("p").permutation(("only",)))
        assert space.n_params == 1
        space0 = ds.space(ds.param("p").permutation(()))
        assert space0.n_params == 1


class TestChoiceDomain:
    def test_bare_and_tuple_and_keyword_forms(self):
        space = ds.space(
            ds.param("algo").choice(
                "linear",
                ("svm-rbf", ds.space(ds.param("gamma").real(1e-5, 10.0))),
                ("fast", None),
                mlp=ds.space(ds.param("depth").integer(1, 5)),
            )
        )
        domain = space.params["algo"].domain
        assert isinstance(domain, ChoiceDomain)
        assert domain.variants == ("linear", "svm-rbf", "fast", "mlp")
        assert domain.has_payload == {"svm-rbf", "mlp"}

    def test_single_variant_is_legal_constant_discriminator(self):
        space = ds.space(ds.param("algo").choice("only"))
        assert space.params["algo"].domain.variants == ("only",)

    def test_weights_align_to_declaration_order(self):
        space = ds.space(ds.param("algo").choice("a", "b", "c").prior(weights=[1.0, 2.0, 3.0]))
        assert space.params["algo"].prior.values == (1.0, 2.0, 3.0)

    def test_nested_choice_paths_are_fully_qualified(self):
        space = ds.space(ds.param("algo").choice(svm=ds.space(ds.param("gamma").real(0.0, 1.0))))
        assert "algo.svm.gamma" in space.params
        assert space.params["algo.svm.gamma"].type_kind == "real"


class TestStructDomain:
    def test_resolves_as_pure_namespace(self):
        space = ds.space(ds.param("layers").space(ds.param("width").integer(1, 10)))
        assert space.params["layers"].domain == StructDomain()
        assert space.params["layers"].chart is None
        assert "layers.width" in space.params

    def test_empty_struct_is_legal(self):
        space = ds.space(ds.param("layers").space())
        assert space.params["layers"].domain == StructDomain()

    def test_struct_condition_gates_all_members(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("layers")
            .space(ds.param("a").bool(), ds.param("b").bool())
            .when(ds.param("flag")),
        )
        assert space.params["layers.a"].condition is not None
        assert space.params["layers.b"].condition is not None

    def test_struct_member_own_when_folds_with_parent(self):
        space = ds.space(
            ds.param("outer_flag").bool(),
            ds.param("layers")
            .space(
                ds.param("inner_flag").bool(),
                ds.param("x").integer(0, 10).when(ds.param("inner_flag")),
            )
            .when(ds.param("outer_flag")),
        )
        cond = space.params["layers.x"].condition
        assert cond is not None
        assert cond.kind == "and"


class TestNoChartForStructuralKinds:
    def test_subset_permutation_choice_space_have_no_chart(self):
        space = ds.space(
            ds.param("s").subset(("a", "b")),
            ds.param("p").permutation(("a", "b")),
            ds.param("c").choice("x", "y"),
            ds.param("st").space(ds.param("z").bool()),
        )
        for path in ("s", "p", "c", "st"):
            assert space.params[path].chart is None


class TestUpReferenceDeferredChecks:
    """A condition up-reference is tolerated per-scope and re-checked later.

    The re-check happens at finalization, over the merged space, so the
    deferred error-table rows still fire, at the terminal operation rather
    than at construction.
    """

    def test_up_reference_into_struct_binds(self):
        # A struct payload (not only choice) may carry an up-reference too.
        space = ds.space(
            ds.param("enabled").bool(),
            ds.param("group").space(
                ds.param("width").integer(1, 8).when(ds.param("enabled")),  # up
            ),
        )
        condition = space.params["group.width"].condition
        assert condition is not None
        assert "enabled" in condition.params
        assert space.validate({"enabled": True, "group": {"width": 4}}).valid
        assert space.validate({"enabled": False, "group": {}}).valid
        assert not space.validate({"enabled": False, "group": {"width": 4}}).valid

    def test_cross_scope_cycle_caught_at_finalization(self):
        # An up-reference (gamma -> global_flag) plus a matching down-reference
        # (global_flag -> algo.svm.gamma) forms a cycle that neither scope's
        # own resolution can see; construction succeeds, finalization raises.
        space = ds.space(
            ds.param("global_flag").bool().when(ds.param("algo.svm.gamma") > 0),  # down
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("gamma").real(0.0, 10.0).when(ds.param("global_flag")),  # up
                ),
            ),
        )
        with pytest.raises(ResolutionError, match="cycle"):
            space.sample_one(seed=0)

    def test_up_reference_type_error_caught_at_finalization(self):
        # Ordering a categorical up-reference (row 14) is invisible standalone
        # the categorical not being in the payload's scope, and is caught
        # at finalization.
        space = ds.space(
            ds.param("mode").categorical("a", "b", "c"),
            ds.param("algo").choice(
                svm=ds.space(
                    ds.param("gamma").real(0.0, 10.0).when(ds.param("mode") > "a"),  # up
                ),
            ),
        )
        with pytest.raises(ResolutionError, match="categorical"):
            space.sample_one(seed=0)

    def test_genuine_typo_still_raises_at_finalization(self):
        space = ds.space(ds.param("x").bool().when(ds.param("nope")))
        with pytest.raises(ResolutionError, match="nope"):
            space.sample_one(seed=0)
