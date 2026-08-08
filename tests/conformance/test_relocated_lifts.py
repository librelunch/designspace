"""Conformance laws: a lift's domain-carried references survive relocation.

API.md, "Paths and Scoping" states that "Composed spaces are therefore
*relocatable*: nesting a space under a variant or struct never rewrites its
internal references".

Laws enforced here: `relocation_preserves_count`,
`relocation_preserves_element_constraints`, `finalization_enforces_row_6`,
`enclosing_count_reference_deferred`.

`ParamDef.condition` and `Space.constraints` are not the only places a
param's references live. A lift's `count` expression and its per-element
constraint templates live inside `ListDomain`, so relocating a child `Space`
under a struct, variant or lift prefix must rewrite those too, or they keep
pre-relocation paths that bind to nothing in the merged space.

Both then degrade silently rather than raising. A dangling count reads as
Kleene Unknown from inactivity, which the Defaults count rule turns into
`0`, so every list materializes as `[]`. A dangling element constraint goes
inapplicable under Kleene rule 4, the permissive direction, so a hard
`.forbid()` stops enforcing while `validate()` still reports `valid`.

Also asserted: `dependency_graph` names only real `space.params` keys, so a
dangling reference is observable there before it is observable in a sample.
"""

from __future__ import annotations

import pytest

import designspace as ds
from designspace.errors import ResolutionError
from designspace.ir import ListDomain


def _span_element() -> ds.Space:
    """A prebuilt element `Space` carrying its own per-element forbid.

    This is the only route to a per-element constraint; API.md notes that
    "the inline form has nowhere to hang a `.forbid`".
    """
    return ds.space(
        ds.param("lo").integer(0, 5),
        ds.param("hi").integer(0, 5),
    ).forbid(ds.param("lo") > ds.param("hi"))


class TestCountReferenceSurvivesRelocation:
    """A count expression is rewritten by the same rename that reprefixes
    the params it references, through every nesting route."""

    def test_struct_body(self) -> None:
        space = ds.space(
            ds.param("grp").space(
                ds.param("n").integer(2, 4),
                ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
            ),
        )
        count = space.params["grp.xs"].domain
        assert isinstance(count, ListDomain)
        assert count.count.params == frozenset({"grp.n"})  # type: ignore[union-attr]
        for seed in range(8):
            config = space.sample_one(seed=seed)
            assert len(config["grp"]["xs"]) == config["grp"]["n"]

    def test_choice_variant_payload(self) -> None:
        space = ds.space(
            ds.param("algo").choice(
                "plain",
                fancy=ds.space(
                    ds.param("k").integer(2, 4),
                    ds.param("ws").real(0.0, 1.0).repeat(ds.param("k")),
                ),
            ),
        )
        domain = space.params["algo.fancy.ws"].domain
        assert isinstance(domain, ListDomain)
        assert domain.count.params == frozenset({"algo.fancy.k"})  # type: ignore[union-attr]
        for seed in range(12):
            payload = ds.payload(space.sample_one(seed=seed), "algo")
            if payload is not None:
                assert len(payload["ws"]) == payload["k"]

    def test_lifted_struct_element(self) -> None:
        space = ds.space(
            ds.param("rows")
            .space(
                ds.param("n").integer(2, 3),
                ds.param("cells").real(0.0, 1.0).repeat(ds.param("n")),
            )
            .repeat(2),
        )
        domain = space.params["rows[].cells"].domain
        assert isinstance(domain, ListDomain)
        assert domain.count.params == frozenset({"rows[].n"})  # type: ignore[union-attr]
        for seed in range(6):
            for row in space.sample_one(seed=seed)["rows"]:
                assert len(row["cells"]) == row["n"]

    def test_chained_lift_renames_at_every_level(self) -> None:
        """`rewrite_domain` recurses through `element_domain`, so a
        nested lift's inner count relocates too."""
        space = ds.space(
            ds.param("grp").space(
                ds.param("m").integer(2, 3),
                ds.param("g").real(0.0, 1.0).repeat(ds.param("m")).repeat(2),
            ),
        )
        for seed in range(6):
            config = space.sample_one(seed=seed)
            grid = config["grp"]["g"]
            assert len(grid) == 2
            assert all(len(row) == config["grp"]["m"] for row in grid)

    def test_dependency_graph_names_only_real_params(self) -> None:
        """The dangling reference is observable here first: every value in
        the graph must be a key of `.params`."""
        space = ds.space(
            ds.param("grp").space(
                ds.param("n").integer(2, 4),
                ds.param("xs").real(0.0, 1.0).repeat(ds.param("n")),
            ),
        )
        assert space.dependency_graph["grp.xs"] == frozenset({"grp.n"})
        for deps in space.dependency_graph.values():
            assert deps <= set(space.params)


class TestLiftedChoiceSurvivesRelocation:
    """A lifted choice's **discriminator template** (`"pipe[]"`) is not a
    `space.params` key. The lift itself is `"pipe"`, and the variant
    payloads relocate to `"pipe[].b.w"`. It is nonetheless referenced, by
    the discriminator-equality condition folded into each payload at
    relocation, so a rename map derived from `params` keys alone misses it
    and the condition keeps a path that binds to nothing.

    `instantiate_element` already handles this explicitly for the
    `"[]" -> "[k]"` expansion; `relocate_child` owes the same treatment for
    the prefix rename.
    """

    @staticmethod
    def _lifted_choice() -> tuple[object, ...]:
        return (ds.param("pipe").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(2),)

    def test_root_scope_baseline(self) -> None:
        space = ds.space(*self._lifted_choice())
        assert space.params["pipe[].b.w"].condition is not None
        for seed in range(5):
            assert space.validate(space.sample_one(seed=seed)).valid

    @pytest.mark.parametrize(
        ("label", "build", "prefix"),
        [
            ("struct", lambda inner: ds.space(ds.param("g").space(*inner)), "g."),
            (
                "variant",
                lambda inner: ds.space(ds.param("m").choice("off", on=ds.space(*inner))),
                "m.on.",
            ),
            (
                "struct_in_struct",
                lambda inner: ds.space(ds.param("a").space(ds.param("b").space(*inner))),
                "a.b.",
            ),
        ],
    )
    def test_relocated_under_each_route(self, label: str, build: object, prefix: str) -> None:
        space = build(self._lifted_choice())  # type: ignore[operator]
        payload = f"{prefix}pipe[].b.w"
        assert payload in space.params
        condition = space.params[payload].condition
        assert condition is not None
        # The discriminator reference must have moved with everything else.
        assert f"{prefix}pipe[]" in condition.params
        assert "pipe[]" not in condition.params
        for seed in range(5):
            assert space.validate(space.sample_one(seed=seed)).valid

    def test_relocated_lifted_choice_activity_is_per_element(self) -> None:
        """The payoff: each element's payload activates on *its own*
        discriminator, which is what the reference has to name."""
        space = ds.space(
            ds.param("g").space(
                ds.param("pipe").choice("a", b=ds.space(ds.param("w").real(0.0, 1.0))).repeat(3),
            ),
        )
        seen_bare, seen_payload = False, False
        for seed in range(30):
            for element in space.sample_one(seed=seed)["g"]["pipe"]:
                if element == "a":
                    seen_bare = True
                else:
                    assert set(element) == {"b"} and "w" in element["b"]
                    seen_payload = True
        assert seen_bare and seen_payload


class TestElementConstraintsSurviveRelocation:
    """`ListDomain.element_constraints` templates are rewritten by the
    same rename, so a per-element hard constraint keeps deciding
    feasibility after relocation."""

    @staticmethod
    def _violating() -> list[dict[str, int]]:
        return [{"lo": 5, "hi": 0}, {"lo": 0, "hi": 1}]

    def test_root_scope_baseline(self) -> None:
        space = ds.space(ds.param("spans").space(_span_element()).repeat(2))
        assert space.validate({"spans": self._violating()}).valid is False

    def test_struct_body(self) -> None:
        space = ds.space(
            ds.param("grp").space(ds.param("spans").space(_span_element()).repeat(2)),
        )
        domain = space.params["grp.spans"].domain
        assert isinstance(domain, ListDomain)
        assert domain.element_constraints[0].params == frozenset(
            {"grp.spans[].lo", "grp.spans[].hi"}
        )
        result = space.validate({"grp": {"spans": self._violating()}})
        assert result.valid is False
        assert [e.instance_path for e in result.constraint_evals] == [
            "grp.spans[0]",
            "grp.spans[1]",
        ]
        assert all(e.applicable for e in result.constraint_evals)

    def test_choice_variant_payload(self) -> None:
        space = ds.space(
            ds.param("mode").choice(
                "off",
                on=ds.space(ds.param("spans").space(_span_element()).repeat(2)),
            ),
        )
        domain = space.params["mode.on.spans"].domain
        assert isinstance(domain, ListDomain)
        assert domain.element_constraints[0].params == frozenset(
            {"mode.on.spans[].lo", "mode.on.spans[].hi"}
        )
        assert space.validate({"mode": {"on": {"spans": self._violating()}}}).valid is False

    def test_sampler_never_emits_a_violating_element(self) -> None:
        space = ds.space(
            ds.param("grp").space(ds.param("spans").space(_span_element()).repeat(3)),
        )
        for seed in range(20):
            for span in space.sample_one(seed=seed)["grp"]["spans"]:
                assert span["lo"] <= span["hi"]


class TestRow6OverDomainCarriedStores:
    """Finalization audits both domain-carried stores, so a reference
    binding nowhere raises (row 6) instead of degrading to Unknown."""

    def test_typo_in_a_count_raises(self) -> None:
        space = ds.space(
            ds.param("n").integer(1, 3),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("nope")),
        )
        with pytest.raises(ResolutionError, match="nope"):
            space.sample_one(seed=0)

    def test_typo_in_a_count_raises_from_introspection(self) -> None:
        space = ds.space(
            ds.param("n").integer(1, 3),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("nope")),
        )
        with pytest.raises(ResolutionError, match="nope"):
            space.fingerprint()

    def test_count_referencing_a_non_integer_param_is_row_12(self) -> None:
        space = ds.space(
            ds.param("grp").space(ds.param("f").real(0.0, 1.0)),
            ds.param("xs").real(0.0, 1.0).repeat(ds.param("grp.f")),
        )
        with pytest.raises(
            ResolutionError, match=r"references 'grp\.f', which is 'real', not integer"
        ):
            space.sample_one(seed=0)


class TestCrossScopeCountIsDeferred:
    """A count referencing an enclosing scope's param resolves like a
    condition: tolerated per-scope, bound at finalization.

    Unlike an expression bound, a count is evaluated at runtime, so nothing
    needs it resolved while the declaring scope builds its charts.
    """

    def test_struct_body_up_reference(self) -> None:
        space = ds.space(
            ds.param("n").integer(2, 4),
            ds.param("grp").space(ds.param("xs").real(0.0, 1.0).repeat(ds.param("n"))),
        )
        assert space.dependency_graph["grp.xs"] == frozenset({"n"})
        for seed in range(8):
            config = space.sample_one(seed=seed)
            assert len(config["grp"]["xs"]) == config["n"]

    def test_choice_variant_up_reference(self) -> None:
        space = ds.space(
            ds.param("n").integer(2, 3),
            ds.param("algo").choice(
                "plain",
                fancy=ds.space(ds.param("ws").real(0.0, 1.0).repeat(ds.param("n"))),
            ),
        )
        for seed in range(12):
            config = space.sample_one(seed=seed)
            payload = ds.payload(config, "algo")
            if payload is not None:
                assert len(payload["ws"]) == config["n"]

    def test_up_reference_joins_topological_order(self) -> None:
        """Row 7's ordering guarantee: the count's referent is assigned
        before the list it sizes."""
        space = ds.space(
            ds.param("n").integer(2, 4),
            ds.param("grp").space(ds.param("xs").real(0.0, 1.0).repeat(ds.param("n"))),
        )
        order = space.topological_order
        assert order.index("n") < order.index("grp.xs")

    def test_cross_scope_cycle_still_raises(self) -> None:
        """Deferral moves *when* the check runs, never whether it runs:
        a cycle formed through an up-referencing count is caught over the
        merged graph (row 7)."""
        space = ds.space(
            ds.param("n").integer(0, 3).when(ds.param("grp.xs").length() > 1),
            ds.param("grp").space(ds.param("xs").real(0.0, 1.0).repeat(ds.param("n"))),
        )
        with pytest.raises(ResolutionError, match="cycle"):
            space.sample_one(seed=0)
