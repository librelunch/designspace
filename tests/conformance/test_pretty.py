"""Conformance laws: `ds.pretty`.

See API.md, "Human-Readable Rendering".

Laws enforced here: `pretty_never_raises`, `pretty_accounts_for_every_coordinate`,
`pretty_states_every_value_exactly`, `pretty_marks_inactive_parameters`,
`pretty_respects_the_width_budget`, `pretty_matches_the_display_hooks`,
`pretty_filters_only_whole_rows`, `pretty_rejects_an_unknown_name`.

The corpus fixtures drive most of these, the same sixteen `display_*` laws
in `tests/conformance/test_display.py` use, so `pretty(config, space)` is
exercised against real, structurally varied spaces rather than hand-built
ones. `pretty_never_raises` additionally drives a matrix of malformed
configs per fixture, since a wrong-typed value is exactly the input a
printer is reached for.
"""

from __future__ import annotations

import contextlib
import importlib
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import designspace as ds
from designspace.config._flatten import flatten_with_errors
from designspace.display._values import render_value

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

FIXTURES = [
    "annealing_schedule",
    "compiler_pipeline",
    "delivery_routes",
    "firmware_buffers",
    "flat_hpo",
    "flow_chemistry",
    "greenhouse",
    "job_shop",
    "memetic_pipeline",
    "mixture_stickbreaking",
    "nested_survey",
    "pump_configurator",
    "sat_solver",
    "solver_portfolio",
    "vi_family",
    "wind_farm_grid",
]


def _build(name: str) -> ds.Space:
    return importlib.import_module(name).build_space()


SPACES = {name: _build(name) for name in FIXTURES}

#: Values that trip whichever built-in exception a wrong shape happens to,
#: deliberately excluding magnitudes large enough to make an out-of-domain
#: lift count expensive to expand: that is a pre-existing performance
#: property of `eval/`'s partial-activity computation, not something a
#: printer can or should paper over, and is unrelated to what this law
#: guards.
BAD_VALUES: tuple[Any, ...] = ("oops", 7, 3.14, True, None, [], {}, ["a", "b"], {"x": 1})


def _configs_for(space: ds.Space) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = [{}]
    for seed in (0, 1):
        with contextlib.suppress(Exception):  # defensive; no fixture hits this
            configs.append(space.sample_one(seed=seed))
    base = configs[-1] if len(configs) > 1 else {}
    for i, key in enumerate(base):
        mutated = dict(base)
        mutated[key] = BAD_VALUES[i % len(BAD_VALUES)]
        configs.append(mutated)
    return configs


class TestPrettyNeverRaises:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_config_in_the_matrix_renders(self, name):
        space = SPACES[name]
        for config in _configs_for(space):
            for kwargs in ({}, {"hide": "inactive"}, {"width": 40}, {"columns": ()}):
                text = ds.pretty(config, space, **kwargs)
                assert isinstance(text, str) and text


class TestPrettyAccountsForEveryCoordinate:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_status_path_is_named(self, name):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        text = ds.pretty(config, space)
        status = space.evaluate_partial(config).param_status
        # Under no filter, every coordinate the space's own partial-status
        # map carries is a row in the table: nothing is dropped silently.
        for path in status:
            last = path.rstrip("]").rsplit(".", 1)[-1].rsplit("[", 1)[0]
            assert last in text, (name, path, text)

    @pytest.mark.parametrize("name", FIXTURES)
    def test_a_filter_reports_what_it_hides(self, name):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        status = space.evaluate_partial(config).param_status
        n_inactive = sum(1 for s in status.values() if s == "inactive")
        text = ds.pretty(config, space, hide="inactive")
        if n_inactive:
            assert f"{n_inactive} inactive not shown" in text
        else:
            assert "not shown" not in text


class TestPrettyStatesEveryValueExactly:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_every_flat_value_appears_unabbreviated(self, name):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        text = ds.pretty(config, space)
        flat, _errors = flatten_with_errors(dict(config), space)
        for _path, raw in flat.items():
            if isinstance(raw, Mapping) and "source" in raw:
                assert str(raw["source"]) in text
            else:
                assert render_value(raw) in text


class TestPrettyMarksInactiveParameters:
    def test_inactive_and_unset_are_distinct_and_never_omitted(self):
        space = ds.space(
            ds.param("switch").bool(),
            ds.param("always").real(0.0, 1.0),
            ds.param("dependent").real(0.0, 1.0).when(ds.param("switch") == True),  # noqa: E712
        )
        text = ds.pretty({"switch": False}, space)
        assert "dependent" in text
        assert "always" in text
        assert "inactive" in text
        assert "unset" in text
        # The two statuses read differently: an inactive param's row never
        # claims to be merely unset, and vice versa.
        dependent_line = next(line for line in text.splitlines() if "dependent" in line)
        always_line = next(line for line in text.splitlines() if "always" in line)
        assert "inactive" in dependent_line
        assert "unset" in always_line
        assert "inactive" not in always_line


class TestPrettyRespectsTheWidthBudget:
    """Swept at 88, the real default, and 120, a generous override: both
    hold for the whole corpus with zero exceptions. A width narrow enough
    to force the documented exception, a value or a `when` clause too wide
    to share a line with anything else, is exercised directly below
    instead of by sweeping the corpus down to it: at that point the
    exception is the common case rather than the rare one, and a blanket
    `len(line) <= width` stops distinguishing a real regression from the
    exception the law itself carves out.
    """

    @pytest.mark.parametrize("name", FIXTURES)
    @pytest.mark.parametrize("width", [88, 120])
    def test_no_line_exceeds_the_requested_width(self, name, width):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        text = ds.pretty(config, space, width=width)
        for line in text.splitlines():
            assert len(line) <= width, (name, width, len(line), line)

    def test_an_overlong_value_is_never_abbreviated_to_fit(self):
        space = ds.space(ds.param("x").real(0.0, 1.0))
        value = 0.123456789012345
        text = ds.pretty({"x": value}, space, width=10)
        assert render_value(value) in text

    def test_an_overlong_when_clause_is_never_abbreviated_to_fit(self):
        space = ds.space(
            ds.param("switch").categorical("a_very_long_variant_name", "other"),
            ds.param("dependent")
            .real(0.0, 1.0)
            .when(ds.param("switch") == "a_very_long_variant_name"),
        )
        text = ds.pretty({"switch": "a_very_long_variant_name", "dependent": 0.5}, space, width=10)
        assert "switch == 'a_very_long_variant_name'" in text
        assert max(len(line) for line in text.splitlines()) > 10


class TestPrettyMatchesTheDisplayHooks:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_pretty_at_defaults_equals_str(self, name):
        space = SPACES[name]
        assert ds.pretty(space) == str(space)
        for pd in space.params.values():
            assert ds.pretty(pd) == str(pd)
        for c in space.constraints:
            assert ds.pretty(c) == str(c)
        for pd in space.params.values():
            assert ds.pretty(pd.domain) == str(pd.domain)


class TestPrettyFiltersOnlyWholeRows:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_kept_rows_are_byte_identical_to_unfiltered(self, name):
        space = SPACES[name]
        config = space.sample_one(seed=0)
        unfiltered = ds.pretty(config, space).splitlines()
        filtered = ds.pretty(config, space, hide="inactive").splitlines()
        kept = [line for line in filtered if not re.match(r"^\s*\.\.\. \d+ \w+ not shown$", line)]
        for line in kept:
            assert line in unfiltered, (name, line)


class TestPrettyRejectsAnUnknownName:
    def test_unknown_column_name_raises(self):
        space = SPACES["flat_hpo"]
        config = space.sample_one(seed=0)
        with pytest.raises(TypeError, match="nope"):
            ds.pretty(config, space, columns="nope")
        with pytest.raises(TypeError, match="nope"):
            ds.pretty(space, columns="nope")

    def test_unknown_status_name_raises(self):
        space = SPACES["flat_hpo"]
        config = space.sample_one(seed=0)
        with pytest.raises(TypeError, match="nope"):
            ds.pretty(config, space, show="nope")
        with pytest.raises(TypeError, match="nope"):
            ds.pretty(config, space, hide="nope")

    def test_show_and_hide_together_raises(self):
        space = SPACES["flat_hpo"]
        config = space.sample_one(seed=0)
        with pytest.raises(TypeError):
            ds.pretty(config, space, show="set", hide="inactive")

    def test_show_or_hide_without_a_space_raises(self):
        space = SPACES["flat_hpo"]
        with pytest.raises(TypeError):
            ds.pretty(space, show="set")
        with pytest.raises(TypeError):
            ds.pretty(space, hide="inactive")
