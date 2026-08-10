"""Conformance laws: the cheap introspection accessors.

See API.md, "Space: Introspection".

Covered here: `.subspaces`, `.dependency_graph`, `.param_constraints`,
`.param_conditions`, `.is_hierarchical`, `.has_variable_length` and
`.is_finite`. `.cardinality()` and `.has_nongenerative_params` are covered
by `test_custom.py`, alongside the surface that gives them something to
report.
"""

from __future__ import annotations

import pytest

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


class TestParamDef:
    """`.param_def()` resolves either path form to its definition.

    A lift reports instance paths, `workers[0].timeout_s`, from every
    surface that names a parameter given a config: `next_assignable`,
    `missing_params`, `param_activity` and `evaluate_partial`. Those are
    not keys of `.params`, which holds the one definition each instance
    shares, `workers[].timeout_s`. Assigning what those surfaces report
    needs the chart, prior and grid on the definition, so this crosses
    between them, as `.param_constraints` and `.param_conditions`
    already do.
    """

    @staticmethod
    def _space():
        return ds.space(
            ds.param("n").integer(0, 3),
            ds.param("workers")
            .space(ds.space(ds.param("timeout_s").integer(1, 3600).log_scale()))
            .repeat(ds.param("n")),
        )

    def test_a_definition_path_resolves(self):
        space = self._space()
        assert space.param_def("n") is space.params["n"]
        assert space.param_def("workers[].timeout_s") is space.params["workers[].timeout_s"]

    def test_an_instance_path_resolves_to_its_template(self):
        space = self._space()
        template = space.params["workers[].timeout_s"]
        for index in range(3):
            assert space.param_def(f"workers[{index}].timeout_s") is template

    def test_it_answers_what_next_assignable_reports(self):
        """The loop's own output is a legal argument, which is the point."""
        space = self._space()
        for path in space.next_assignable({"n": 3}):
            defn = space.param_def(path)
            assert defn.type_kind == "integer"
            assert defn.chart is not None

    def test_a_scalar_lift_element_resolves_to_its_own_definition(self):
        """A scalar lift stores no field template, so the element is derived.

        `params` holds only the container, whose kind is `list` and whose
        `chart` is `None`, the element's kind and chart living on the
        `ListDomain`. Handing the container back would tell a caller the
        thing at `timeouts[0]` is a list without a chart.
        """
        space = ds.space(
            ds.param("n").integer(0, 3),
            ds.param("timeouts").integer(1, 3600).log_scale().repeat(ds.param("n")),
        )
        assert list(space.params) == ["n", "timeouts"]
        for path in space.next_assignable({"n": 2}):
            defn = space.param_def(path)
            assert defn.type_kind == "integer"
            assert defn.chart is not None
            assert defn.chart.from_unit(0.0) == 1
            assert defn.chart.from_unit(1.0) == 3600

    def test_a_nested_scalar_lift_resolves_at_the_innermost_level(self):
        space = ds.space(ds.param("grid").real(0.0, 1.0).repeat(2).repeat(3))
        defn = space.param_def("grid[0][1]")
        assert defn.type_kind == "real"
        assert defn.chart is not None

    def test_a_nested_lift_resolves_at_every_level(self):
        space = ds.space(
            ds.param("grid").space(ds.space(ds.param("cells").real(0.0, 1.0).repeat(2))).repeat(2),
        )
        template = space.params["grid[].cells"]
        assert space.param_def("grid[0].cells") is template
        assert space.param_def("grid[1].cells") is template

    def test_an_unknown_path_raises_naming_it(self):
        space = self._space()
        with pytest.raises(Exception) as caught:
            space.param_def("nope")
        assert "nope" in str(caught.value)
