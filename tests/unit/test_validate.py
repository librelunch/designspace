"""M2 gate: `.validate()` / `.validate_param()` / `.is_feasible()` /
`.infeasibility_reasons()` / `.evaluate_constraints()` (API_v3.md,
"Space — Validation").

`ParamError.reason` values: "missing", "out_of_bounds", "wrong_type",
"inactive_but_present", "not_on_grid".
"""

from __future__ import annotations

import designspace as ds


def _reasons(result):
    return {pe.param: pe.reason for pe in result.param_errors}


class TestParamErrorReasons:
    def test_missing(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        result = space.validate({})
        assert _reasons(result) == {"x": "missing"}
        assert result.valid is False

    def test_out_of_bounds_real(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        result = space.validate({"x": 5.0})
        assert _reasons(result) == {"x": "out_of_bounds"}

    def test_out_of_bounds_integer(self):
        space = ds.space(ds.param("n").integer(1, 10))
        result = space.validate({"n": 20})
        assert _reasons(result) == {"n": "out_of_bounds"}

    def test_wrong_type_real(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        result = space.validate({"x": "not a number"})
        assert _reasons(result) == {"x": "wrong_type"}

    def test_wrong_type_bool_rejects_int(self):
        space = ds.space(ds.param("flag").bool())
        result = space.validate({"flag": 1})
        assert _reasons(result) == {"flag": "wrong_type"}

    def test_wrong_type_integer_rejects_float(self):
        space = ds.space(ds.param("n").integer(0, 10))
        result = space.validate({"n": 5.0})
        assert _reasons(result) == {"n": "wrong_type"}

    def test_inactive_but_present(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        )
        result = space.validate({"flag": False, "x": 0.5})
        assert _reasons(result) == {"x": "inactive_but_present"}

    def test_not_on_grid(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.25))
        result = space.validate({"x": 0.1})
        assert _reasons(result) == {"x": "not_on_grid"}

    def test_on_grid_is_valid(self):
        space = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.25))
        result = space.validate({"x": 0.25})
        assert result.valid is True

    def test_categorical_out_of_bounds(self):
        space = ds.space(ds.param("c").categorical("a", "b"))
        result = space.validate({"c": "z"})
        assert _reasons(result) == {"c": "out_of_bounds"}

    def test_categorical_type_tagged_membership(self):
        space = ds.space(ds.param("c").categorical(1, 2))
        result = space.validate({"c": 1.0})  # float, not int -- distinct value
        assert _reasons(result) == {"c": "out_of_bounds"}

    def test_periodic_hi_is_invalid(self):
        space = ds.space(ds.param("angle").real(0.0, 360.0, periodic=True))
        result = space.validate({"angle": 360.0})
        assert _reasons(result) == {"angle": "out_of_bounds"}
        assert space.validate({"angle": 0.0}).valid is True


class TestFeasibilityRelations:
    def test_is_feasible_matches_validate_valid(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.5)
        for x in (0.1, 0.9):
            config = {"x": x}
            assert space.is_feasible(config) == space.validate(config).valid

    def test_constrain_never_affects_feasibility(self):
        space = ds.space(ds.param("x").real(0.0, 100.0)).constrain(ds.param("x") <= 1.0)
        assert space.is_feasible({"x": 50.0}) is True

    def test_infeasibility_reasons_reports_param_and_forbid(self):
        space = ds.space(ds.param("x").real(0.0, 1.0)).forbid(ds.param("x") > 0.5)
        reasons = space.infeasibility_reasons({"x": 0.9})
        assert any("forbid" in r for r in reasons)

    def test_evaluate_constraints_reports_hard_and_soft(self):
        space = (
            ds.space(ds.param("x").real(0.0, 1.0))
            .forbid(ds.param("x") > 0.9)
            .constrain(ds.param("x") < 0.5)
        )
        evals = space.evaluate_constraints({"x": 0.6})
        assert len(evals) == 2


class TestUnknownIsInapplicable:
    def test_forbid_referencing_inactive_param_is_inapplicable(self):
        space = ds.space(
            ds.param("flag").bool(),
            ds.param("x").real(0.0, 1.0).when(ds.param("flag")),
        ).forbid(ds.param("x") > 0.5)
        result = space.validate({"flag": False})
        ce = result.constraint_evals[0]
        assert ce.applicable is False
        assert ce.satisfied is None
        assert ce.margin is None
        assert result.valid is True  # inapplicable forbid never causes infeasibility


class TestValidateParam:
    def test_validate_param_domain_check(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        assert space.validate_param("x", 0.5).valid is True
        assert space.validate_param("x", 5.0).valid is False

    def test_validate_param_unknown_path_raises(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        try:
            space.validate_param("nonexistent", 1.0)
            raised = False
        except TypeError:
            raised = True
        assert raised

    def test_validate_param_without_context_omits_multi_param_constraint(self):
        space = ds.space(
            ds.param("x").real(0.0, 10.0), ds.param("y").real(0.0, 10.0)
        ).forbid(ds.param("x") + ds.param("y") > 15)  # type: ignore[operator]
        result = space.validate_param("x", 5.0)
        assert result.constraint_evals == ()

    def test_validate_param_with_context_evaluates_multi_param_constraint(self):
        space = ds.space(
            ds.param("x").real(0.0, 10.0), ds.param("y").real(0.0, 10.0)
        ).forbid(ds.param("x") + ds.param("y") > 15)  # type: ignore[operator]
        result = space.validate_param("x", 10.0, context={"y": 10.0})
        assert len(result.constraint_evals) == 1
        assert result.valid is False

    def test_validate_param_single_param_constraint_needs_no_context(self):
        space = ds.space(ds.param("x").real(0.0, 10.0)).forbid(ds.param("x") > 5)
        result = space.validate_param("x", 8.0)
        assert len(result.constraint_evals) == 1
        assert result.valid is False
