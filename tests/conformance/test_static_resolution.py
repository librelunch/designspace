"""Conformance laws: `.slice()` and `.freeze()` fold determined structure.

See API.md, "Space: Structural Operations".

Laws enforced here: `count_folds_to_int`, `condition_folds_to_none`,
`fold_reach_differs`, `fold_is_best_effort`.

Both operations already substitute a fixed value at its reference sites.
What they additionally owe is the fold: once every param a piece of derived
structure reads is determined, that structure is no longer derived, and
leaving it in expression form makes the resulting space misreport itself.

A `.repeat()` count is a reference site like a condition or a bound, so
`.slice()` removes the count param and leaves a static `int` count. That is
the only route from a dynamic-count space to a fixed layout.

`.freeze()` folds only where the frozen param's domain admits a single
value. Freeze keeps the param, and the kinds it pins by a hard `require`
rather than by domain narrowing, meaning bool, choice, subset, permutation,
custom and program, keep a domain admitting their other values. Folding
against the pinned value would then misreport activity on a config that
merely fails the pin. `.slice()`, having removed the param, faces no such
config and folds unconditionally.

Folding to `int` rather than to a constant expression is the operative part:
every static-ness surface, meaning `has_variable_length`,
`coordinate_paths()`, `cardinality()` and the `Array`-against-`List` dtype
rule, tests `isinstance(count, int)`.

A condition folding to literal `True` becomes no condition at all. Literal
`False` is deliberately not pruned, since that would remove a declared name
from the path namespace.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import ListDomain


def _count_of(space: ds.Space, path: str) -> object:
    domain = space.params[path].domain
    assert isinstance(domain, ListDomain)
    return domain.count


class TestSliceFoldsACount:
    """`.slice()` on a count param removes it and leaves a static count.

    This is the substitution it already performs for a bound reference.
    """

    @staticmethod
    def _space() -> ds.Space:
        return ds.space(
            ds.param("n").integer(1, 8),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )

    def test_count_param_is_removed_and_count_becomes_a_static_int(self) -> None:
        sliced = self._space().slice(n=3)
        assert set(sliced.params) == {"xs"}
        assert _count_of(sliced, "xs") == 3
        assert isinstance(_count_of(sliced, "xs"), int)

    def test_sliced_space_samples_at_the_fixed_length(self) -> None:
        sliced = self._space().slice(n=3)
        for seed in range(5):
            config = sliced.sample_one(seed=seed)
            assert len(config["xs"]) == 3
            assert sliced.validate(config).valid

    def test_slicing_a_count_yields_a_fixed_layout(self) -> None:
        """The motivating consequence: `coordinate_paths()` requires every
        count to be a literal integer, so slicing is the route to one."""
        base = self._space()
        with pytest.raises(
            ResolutionError,
            match=r"has a dynamic repeat\(\) count, so the space has no fixed layout",
        ):
            base.coordinate_paths()
        sliced = base.slice(n=3)
        assert sliced.coordinate_paths() == ("xs[0]", "xs[1]", "xs[2]")
        assert sliced.has_variable_length is False

    def test_arithmetic_over_the_sliced_value_folds(self) -> None:
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n") * 2),
        )
        assert _count_of(space.slice(n=3), "xs") == 6

    def test_count_inside_a_relocated_scope_folds(self) -> None:
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("grp").space(ds.param("xs").real(0.0, 1.0).repeat(ds.param("n"))),
        )
        sliced = space.slice(n=2)
        assert _count_of(sliced, "grp.xs") == 2
        assert len(sliced.sample_one(seed=0)["grp"]["xs"]) == 2

    def test_a_partially_determined_count_stays_an_expression(self) -> None:
        """Soundness of the best-effort posture: with `m` still free the
        count cannot fold, and not folding is always safe."""
        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("m").integer(1, 4),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n") + ds.param("m")),
        )
        sliced = space.slice(n=2)
        assert not isinstance(_count_of(sliced, "xs"), int)
        assert sliced.has_variable_length is True
        for seed in range(4):
            config = sliced.sample_one(seed=seed)
            assert len(config["xs"]) == 2 + config["m"]


class TestFreezeFoldsACount:
    """`.freeze()` folds the same structure while keeping the param.

    Its domain is narrowed to the single value, which is what makes the fold
    sound.
    """

    @staticmethod
    def _space() -> ds.Space:
        return ds.space(
            ds.param("n").integer(1, 8),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
        )

    def test_count_becomes_a_static_int_and_the_param_remains(self) -> None:
        frozen = self._space().freeze(n=3)
        assert set(frozen.params) == {"n", "xs"}
        assert _count_of(frozen, "xs") == 3

    def test_static_ness_surfaces_all_agree(self) -> None:
        frozen = self._space().freeze(n=3)
        assert frozen.has_variable_length is False
        assert frozen.coordinate_paths() == ("n", "xs[0]", "xs[1]", "xs[2]")

    def test_samples_at_the_fixed_length(self) -> None:
        frozen = self._space().freeze(n=3)
        for seed in range(5):
            config = frozen.sample_one(seed=seed)
            assert config["n"] == 3
            assert len(config["xs"]) == 3
            assert frozen.validate(config).valid

    def test_fingerprint_equals_the_hand_written_static_space(self) -> None:
        """The folded space fingerprints equal to the hand-written static one.

        Equal fingerprints must mean identical valid-config sets, and these
        two spaces have exactly that, so the equality is the correct outcome
        of folding rather than an accident.
        """
        frozen = self._space().freeze(n=3)
        hand = ds.space(
            ds.param("n").integer(3, 3).default(3),
            ds.param("xs").real(0.0, 1.0).repeat(3),
        )
        assert frozen.fingerprint() == hand.fingerprint()
        assert frozen.fingerprint(scope="sampling") == hand.fingerprint(scope="sampling")


class TestConditionsResolveStatically:
    """API.md's `.freeze()` row says "conditions resolve statically"; the
    fold is what makes that true, for `.slice()` alike."""

    @staticmethod
    def _space() -> ds.Space:
        return ds.space(
            ds.param("flag").bool(),
            ds.param("y").real(0.0, 1.0).when(ds.param("flag")),
        )

    def test_slice_true_drops_the_condition(self) -> None:
        sliced = self._space().slice(flag=True)
        assert sliced.params["y"].condition is None
        assert sliced.is_conditional is False
        for seed in range(5):
            assert "y" in sliced.sample_one(seed=seed)

    def test_freeze_folds_a_domain_narrowed_kind(self) -> None:
        """Categorical freeze narrows the domain to the single value, so
        the condition is provably True and folds."""
        space = ds.space(
            ds.param("mode").categorical("a", "b"),
            ds.param("y").real(0.0, 1.0).when(ds.param("mode") == "a"),
        )
        frozen = space.freeze(mode="a")
        assert frozen.params["y"].condition is None
        assert frozen.is_conditional is False
        assert [c.target for c in frozen.conditions] == []
        for seed in range(5):
            assert "y" in frozen.sample_one(seed=seed)

    def test_slice_folds_a_comparison_condition_too(self) -> None:
        space = ds.space(
            ds.param("mode").categorical("a", "b"),
            ds.param("y").real(0.0, 1.0).when(ds.param("mode") == "a"),
        )
        assert space.slice(mode="a").params["y"].condition is None

    def test_freeze_does_not_fold_a_constraint_pinned_kind(self) -> None:
        """The asymmetry between the two operations, stated as a law.

        `.freeze()` keeps the param, and bool/choice/subset/permutation/
        custom/program are pinned by a hard `require` rather than by domain
        narrowing (API.md's per-kind mechanism), so their domain still
        admits the other values: a config may hold one and merely be
        infeasible. Folding there would report `y` active in a config where
        evaluation says it is not. `.slice()`, having removed the param,
        has no such config to worry about, so it folds where freeze does
        not.
        """
        frozen = self._space().freeze(flag=True)
        assert frozen.params["y"].condition is not None
        assert frozen.is_conditional is True

    def test_freeze_on_a_choice_keeps_the_variant_activation_condition(self) -> None:
        space = ds.space(
            ds.param("algo").choice("linear", svm=ds.space(ds.param("gamma").real(1e-5, 10.0))),
        )
        frozen = space.freeze(algo="svm")
        assert frozen.params["algo.svm.gamma"].condition is not None

    def test_false_is_not_pruned(self) -> None:
        """Deliberate asymmetry: `True -> None` is information-preserving,
        while pruning a `False` param would remove a declared name from the
        path namespace (fingerprint- and `flatten`-visible)."""
        sliced = self._space().slice(flag=False)
        assert "y" in sliced.params
        assert sliced.params["y"].condition is not None
        assert sliced.sample_one(seed=0) == {}

    def test_a_still_free_operand_leaves_the_condition_alone(self) -> None:
        space = ds.space(
            ds.param("a").bool(),
            ds.param("b").bool(),
            ds.param("y").real(0.0, 1.0).when(ds.param("a") & ds.param("b")),
        )
        sliced = space.slice(a=True)
        assert sliced.params["y"].condition is not None
        assert sliced.is_conditional is True


class TestFoldIsBestEffortAndOpaqueSafe:
    """The fold never calls a user function: a `ds.value` operand keeps the
    expression unfolded rather than invoking `fn` at structural-op time,
    which would be a call site the calling convention never promised."""

    def test_ds_value_count_is_not_folded_and_fn_is_not_called(self) -> None:
        calls: list[int] = []

        def triple(k: int) -> int:
            calls.append(k)
            return 3 * k

        space = ds.space(
            ds.param("n").integer(1, 4),
            ds.param("xs").real(0.0, 1.0).repeat(ds.value(triple, ds.param("n"), returns=int)),
        )
        sliced = space.slice(n=2)
        assert calls == []
        assert not isinstance(_count_of(sliced, "xs"), int)
        assert len(sliced.sample_one(seed=0)["xs"]) == 6
