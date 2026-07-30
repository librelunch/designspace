"""Unit tests for `sample/_diagnostics.py` (M10.6, PLAN.md): misuse guards
and the `instance_evals_indexed`/`instance_constraint_evals` relationship
diagnostics relies on. The conformance laws (Kleene rules, D-73/D-74) live
in `tests/conformance/test_sampling_diagnostics.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

import designspace as ds
from designspace.errors import SamplingError
from designspace.eval import instance_constraint_evals, instance_evals_indexed
from designspace.sample._sample import _draw_config


class TestMisuseGuards:
    def test_n_zero_raises_type_error(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(TypeError):
            space.sampling_report(0)

    def test_n_negative_raises_type_error(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        with pytest.raises(TypeError):
            space.sampling_report(-1)

    def test_default_n_is_1000(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        report = space.sampling_report(seed=0)
        assert report.n == 1000


class TestNonGenerativeErrorPropagates:
    """`sampling_report` adds no new error class -- a non-generative custom
    param with no `.default()` still raises the same `SamplingError` a
    plain `sample_one` would (API.md, "Sampling and Generativity")."""

    def test_non_generative_custom_without_default_raises(self):
        @dataclass(frozen=True)
        class NoSample:
            @property
            def type_key(self) -> str:
                return "no_sample"

            def validate(self, value: Any) -> bool:
                return isinstance(value, int)

            def to_json(self, value: Any) -> Any:
                return value

            def from_json(self, data: Any) -> Any:
                return data

            def describe(self) -> dict[str, Any]:
                return {}

        space = ds.space(ds.param("x").custom(NoSample()))
        with pytest.raises(SamplingError):
            space.sampling_report(10, seed=0)


class TestInstanceEvalsIndexed:
    """`instance_evals_indexed` is `instance_constraint_evals` with an
    added `(list path, template index)` tag -- dropping the tag must
    reproduce the untagged function element-for-element.

    Compared field-by-field (`instance_path`/`applicable`/`satisfied`/
    `margin`), never via a bare `==` on the `ConstraintEval`/`Constraint`
    itself: `ParamExpr.__eq__` is DSL-overloaded to *build* a `Compare`
    node (`ds.param("x") == 0`), so `==` on anything holding an expression
    tree never performs structural comparison.
    """

    def test_matches_instance_constraint_evals_element_for_element(self):
        stop = ds.space(
            ds.param("location").integer(0, 9),
            ds.param("dwell_min").integer(5, 30),
        ).forbid((ds.param("location") == 0) & (ds.param("dwell_min") > 10))
        space = ds.space(
            ds.param("n_stops").integer(1, 5),
            ds.param("stops").space(stop).repeat(ds.param("n_stops")),
        )
        rng = np.random.default_rng(0)
        for _ in range(20):
            config, activity = _draw_config(space, rng, {})
            untagged = instance_constraint_evals(space, config, activity)
            indexed = instance_evals_indexed(space, config, activity)
            tagged_evals = [ce for _path, _idx, ce in indexed]
            assert len(tagged_evals) == len(untagged)
            for tagged, plain in zip(tagged_evals, untagged, strict=True):
                assert tagged.instance_path == plain.instance_path
                assert tagged.applicable == plain.applicable
                assert tagged.satisfied == plain.satisfied
                assert tagged.margin == plain.margin

    def test_tag_names_the_owning_list_and_template_position(self):
        stop = ds.space(ds.param("v").integer(0, 9)).forbid(ds.param("v") == 0)
        space = ds.space(ds.param("stops").space(stop).repeat(3))
        rng = np.random.default_rng(0)
        config, activity = _draw_config(space, rng, {})
        indexed = instance_evals_indexed(space, config, activity)
        assert indexed  # repeat(3) is static and unconditional: always 3 instances
        for path, idx, _ce in indexed:
            assert path == "stops"
            assert idx == 0  # exactly one template on `stop`
