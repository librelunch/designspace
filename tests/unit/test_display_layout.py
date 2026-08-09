"""Unit tests for human-readable rendering: exact golden layouts.

The conformance suite (`tests/conformance/test_display.py`) checks the
properties every rendering must have, across the whole corpus. This file
pins the exact text a handful of fixed cases produce: column alignment,
lift indentation, elision, and the standalone (non-table) renderings.
Brittleness is deliberately concentrated here rather than spread through
the conformance suite, so a layout tweak breaks one file, not many.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import designspace as ds

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))


def _package_example_space() -> ds.Space:
    """The `designspace` package docstring's own example."""
    return ds.space(
        ds.param("optimizer").categorical("adam", "sgd"),
        ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
    )


class TestSpaceLayout:
    def test_flat_space_column_alignment(self):
        space = _package_example_space()
        assert str(space) == (
            "Space: 3 params, 1 conditional, 0 constraints\n"
            "  optimizer  categorical  {'adam', 'sgd'}\n"
            "  lr         real         [0.0001, 0.1]  log\n"
            "  momentum   real         [0.0, 0.99]  when optimizer == 'sgd'"
        )

    def test_lift_indentation_and_constraint_block(self):
        import delivery_routes

        space = delivery_routes.build_space()
        assert str(space) == (
            "Space: 4 params, 0 conditional, 2 constraints\n"
            "  n_stops         integer  [1, 5]\n"
            "  stops           list     count = n_stops, of struct\n"
            "    [].location   integer  [0, 9]\n"
            "    [].dwell_min  integer  [5, 30]\n"
            "\n"
            "  encourage  sum(stops[].dwell_min) <= 90\n"
            "  forbid     stops[0].location != 0"
        )

    def test_struct_row_collapses_kind_and_domain(self):
        space = ds.space(ds.param("zone").space(ds.param("area").real(0.0, 1.0)))
        text = str(space)
        assert "struct   struct" not in text  # kind and domain would otherwise both say it
        assert text.splitlines()[1].rstrip() == "  zone    struct"

    def test_choice_payload_row_and_suppressed_when(self):
        space = ds.space(
            ds.param("heating").choice(
                "electric", gas=ds.space(ds.param("burner_power_kw").real(5.0, 50.0))
            )
        )
        text = str(space)
        assert "one of electric, gas(...)" in text
        assert "gas.burner_power_kw" in text
        # The payload field's own condition is exactly the discriminator
        # test `heating == 'gas'`; nesting under `heating` already states
        # it, so it is not repeated on the row.
        assert "when heating == 'gas'" not in text
        assert "1 conditional" in text  # the header count is unaffected


class TestElision:
    def test_long_categorical_elides_with_a_count_not_a_cut_token(self):
        values = tuple(f"opt_{i}" for i in range(40))
        text = str(ds.space(ds.param("p").categorical(*values)))
        assert "'opt_0'" in text
        assert "more}" in text
        for line in text.splitlines():
            assert len(line) <= 88


class TestStandaloneRenderings:
    def test_domain(self):
        assert str(ds.RealDomain(0.0, 1.0)) == "[0.0, 1.0]"

    def test_param_def(self):
        import delivery_routes

        space = delivery_routes.build_space()
        assert str(space.params["n_stops"]) == "n_stops: integer [1, 5]"

    def test_bare_param_expr_has_no_domain_yet(self):
        assert str(ds.param("x")) == "param('x')"

    def test_declared_param_expr(self):
        pe = ds.param("lr").real(1e-4, 1e-1).log_scale()
        assert str(pe) == "param('lr'): real [0.0001, 0.1] log"

    def test_condition(self):
        space = _package_example_space()
        assert str(space.conditions[0]) == "momentum when optimizer == 'sgd'"

    def test_constraint(self):
        import delivery_routes

        space = delivery_routes.build_space()
        assert str(space.constraints[0]) == "encourage  sum(stops[].dwell_min) <= 90"


class TestResultRenderings:
    def test_validation_result_ok(self):
        space = _package_example_space()
        result = space.validate({"optimizer": "adam", "lr": 0.001})
        assert str(result) == "Validation: OK"

    def test_validation_result_invalid(self):
        space = _package_example_space()
        result = space.validate({"optimizer": "nope", "lr": 5.0})
        assert str(result) == (
            "Validation: INVALID (2 param error(s), 0 constraint(s) violated)\n"
            "  optimizer: out_of_bounds (value='nope')\n"
            "  lr: out_of_bounds (value=5.0)"
        )

    def test_representation_summarizes_rather_than_nesting_two_spaces(self):
        space = _package_example_space()
        rep = space.represent()
        text = str(rep)
        assert text == (
            "Representation: 3 params -> 3 params "
            "(invertible=True, measure_preserving=True)\n"
            "  encoded: lr, momentum"
        )
        # The whole point of a summary: never two full space tables.
        assert "Space: 3 params" not in text


class TestExpressionRendering:
    @pytest.mark.parametrize(
        ("expr", "expected"),
        [
            (ds.param("x").real(0.0, 1.0) < 3, "x < 3"),
            (ds.param("x").real(0.0, 1.0) == "sgd", "x == 'sgd'"),
        ],
    )
    def test_simple_comparisons(self, expr, expected):
        assert str(expr) == expected

    def test_and_inside_or_gets_clarifying_parens(self):
        a = ds.param("a").bool()
        b = ds.param("b").bool()
        c = ds.param("c").bool()
        expr = (~a) | (b & c)
        assert str(expr) == "not a or (b and c)"
