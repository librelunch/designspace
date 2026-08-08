"""Conformance laws: the cheap introspection accessors.

See API.md, "Space: Introspection".

Covered here: `.subspaces`, `.dependency_graph`, `.param_constraints`,
`.param_conditions`, `.is_hierarchical`, `.has_variable_length` and
`.is_finite`. `.cardinality()` and `.has_nongenerative_params` are covered
by `test_custom.py`, alongside the surface that gives them something to
report.
"""

from __future__ import annotations

import designspace as ds
from designspace.ir import SubspaceInfo


def _elaborate_space() -> ds.Space:
    return (
        ds.space(
            ds.param("solver").choice(
                "dpll",
                cdcl=ds.space(ds.param("restart").categorical("luby", "geometric")),
            ),
            ds.param("cfg").space(ds.param("depth").integer(1, 10)),
            ds.param("verbosity").ordinal("silent", "normal", "verbose"),
            ds.param("count").integer(0, 5),
            ds.param("items").real(0.0, 1.0).repeat(ds.param("count")),
        )
        .forbid(ds.param("verbosity") >= "verbose")
        .encourage((ds.param("cfg.depth") < 5) & (ds.param("count") > 0), tags=("perf",))
    )


class TestSubspaces:
    def test_struct_entry(self):
        space = _elaborate_space()
        subs = space.subspaces
        assert "cfg." in subs
        info = subs["cfg."]
        assert isinstance(info, SubspaceInfo)
        assert info.kind == "struct"
        assert info.member_paths == ("cfg.depth",)
        assert info.condition is None
        assert info.variant_name is None

    def test_variant_entry_only_for_payload_bearing_variants(self):
        space = _elaborate_space()
        subs = space.subspaces
        assert "solver.cdcl." in subs
        assert "solver.dpll." not in subs  # "dpll" has no payload
        info = subs["solver.cdcl."]
        assert info.kind == "variant"
        assert info.variant_name == "cdcl"
        assert info.member_paths == ("solver.cdcl.restart",)
        assert info.condition is not None

    def test_variant_condition_gates_correctly(self):
        space = _elaborate_space()
        for cfg in space.sample_dicts(50, seed=0):
            solver = cfg["solver"]
            has_cdcl_payload = isinstance(solver, dict) and "cdcl" in solver
            assert has_cdcl_payload == (solver != "dpll")

    def test_no_entry_for_scalar_params(self):
        space = _elaborate_space()
        assert "verbosity." not in space.subspaces
        assert not any(k.startswith("count") for k in space.subspaces)


class TestDependencyGraph:
    def test_condition_edge(self):
        space = ds.space(
            ds.param("g").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("g")),
        )
        graph = space.dependency_graph
        assert graph["x"] == frozenset({"g"})
        assert graph["g"] == frozenset()

    def test_constraint_edge_is_symmetric(self):
        space = ds.space(ds.param("a").integer(0, 5), ds.param("b").integer(0, 5)).forbid(
            ds.param("a") > ds.param("b")
        )
        graph = space.dependency_graph
        assert graph["a"] == frozenset({"b"})
        assert graph["b"] == frozenset({"a"})

    def test_repeat_count_edge(self):
        space = ds.space(
            ds.param("n").integer(0, 5),
            ds.param("items").real(0.0, 1.0).repeat(ds.param("n")),
        )
        graph = space.dependency_graph
        assert graph["items"] == frozenset({"n"})

    def test_every_param_path_has_an_entry(self):
        space = _elaborate_space()
        assert set(space.dependency_graph) == set(space.params)


class TestParamConstraintsAndConditions:
    def test_param_constraints_filters_by_membership(self):
        space = ds.space(ds.param("a").integer(0, 5), ds.param("b").integer(0, 5)).forbid(
            ds.param("a") > ds.param("b")
        )
        assert len(space.param_constraints("a")) == 1
        assert len(space.param_constraints("b")) == 1
        c = space.param_constraints("a")[0]
        assert c.params == frozenset({"a", "b"})

    def test_param_constraints_empty_when_unreferenced(self):
        space = ds.space(ds.param("a").integer(0, 5), ds.param("z").bool()).forbid(
            ds.param("a") > 2
        )
        assert space.param_constraints("z") == []

    def test_param_conditions_includes_target_and_references(self):
        space = ds.space(
            ds.param("g").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("g")),
        )
        assert len(space.param_conditions("x")) == 1  # x is the target
        assert len(space.param_conditions("g")) == 1  # g is referenced by x's condition


class TestBooleanFlags:
    def test_is_hierarchical(self):
        assert _elaborate_space().is_hierarchical is True
        assert ds.space(ds.param("x").real(0.0, 1.0)).is_hierarchical is False

    def test_has_variable_length(self):
        assert _elaborate_space().has_variable_length is True
        static_list = ds.space(ds.param("x").real(0.0, 1.0).repeat(3))
        assert static_list.has_variable_length is False

    def test_is_finite(self):
        assert ds.space(ds.param("x").integer(0, 10)).is_finite is True
        assert ds.space(ds.param("x").real(0.0, 1.0)).is_finite is False
        quantized = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1))
        assert quantized.is_finite is True

    def test_is_finite_false_for_unquantized_list_element(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).repeat(3))
        assert space.is_finite is False

    def test_is_finite_true_for_quantized_list_element(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.1).repeat(3))
        assert space.is_finite is True
