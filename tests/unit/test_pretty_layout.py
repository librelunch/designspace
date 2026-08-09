"""Unit tests for `ds.pretty`: exact golden layouts.

The conformance suite (`tests/conformance/test_pretty.py`) checks the
properties every rendering must have, across the whole corpus. This file
pins the exact text a handful of fixed cases produce: column alignment,
container rows, the lifted-choice tree, a filter's trailer line, the
constraint block, and the degraded rendering of a config `validate` itself
rejects. Brittleness is deliberately concentrated here, matching
`tests/unit/test_display_layout.py`'s own rationale.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import designspace as ds

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))


def _memetic_pipeline_space() -> ds.Space:
    return importlib.import_module("memetic_pipeline").build_space()


def _small_space() -> ds.Space:
    return ds.space(
        ds.param("optimizer").categorical("adam", "sgd"),
        ds.param("lr").real(1e-4, 1e-1).log_scale(),
        ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
    ).forbid(ds.param("lr") > 0.5)


class TestConfigLayout:
    def test_column_alignment_and_the_constraint_block(self):
        space = _small_space()
        config = {"optimizer": "sgd", "lr": 0.01, "momentum": 0.9}
        assert ds.pretty(config, space) == (
            "Config: 3 params, 3 set, 0 inactive, valid\n"
            "  optimizer  = 'sgd'  in {'adam', 'sgd'}\n"
            "  lr         = 0.01  in [0.0001, 0.1]\n"
            "  momentum   = 0.9  in [0.0, 0.99]  when optimizer == 'sgd'\n"
            "\n"
            "  forbid  lr > 0.5  ok  margin -0.490"
        )

    def test_an_inactive_param_shows_its_condition_not_a_value(self):
        space = _small_space()
        config = {"optimizer": "adam", "lr": 0.01}
        assert ds.pretty(config, space) == (
            "Config: 3 params, 2 set, 1 inactive, valid\n"
            "  optimizer  = 'adam'  in {'adam', 'sgd'}\n"
            "  lr         = 0.01  in [0.0001, 0.1]\n"
            "  momentum   inactive  when optimizer == 'sgd'\n"
            "\n"
            "  forbid  lr > 0.5  ok  margin -0.490"
        )

    def test_hide_reports_what_it_drops(self):
        space = _small_space()
        config = {"optimizer": "adam", "lr": 0.01}
        assert ds.pretty(config, space, hide="inactive") == (
            "Config: 3 params, 2 set, 1 inactive, valid\n"
            "  optimizer  = 'adam'  in {'adam', 'sgd'}\n"
            "  lr         = 0.01  in [0.0001, 0.1]\n"
            "  ... 1 inactive not shown\n"
            "\n"
            "  forbid  lr > 0.5  ok  margin -0.490"
        )

    def test_a_config_validate_itself_rejects_degrades_rather_than_raising(self):
        space = _small_space()
        config = {"optimizer": "adam", "lr": "oops"}
        assert ds.pretty(config, space) == (
            "Config: 3 params, 2 set, not validated\n"
            "  optimizer  = 'adam'\n"
            "  lr         = 'oops'\n"
            "  momentum   unknown  when optimizer == 'sgd'"
        )


class TestConfigLayoutAgainstTheCorpus:
    def test_a_lifted_choice_shows_the_real_index_and_suppresses_the_redundant_when(self):
        space = _memetic_pipeline_space()
        config = {
            "n_ops": 4,
            "pipeline": [
                {"local_search": {"iters": 15}},
                {"local_search": {"iters": 32}},
                "crossover",
                {"local_search": {"iters": 41}},
            ],
        }
        assert ds.pretty(config, space) == (
            "Config: 14 params, 9 set, 5 inactive, valid\n"
            "  n_ops                     = 4  in [2, 6]\n"
            "  pipeline                  count 4\n"
            "    [0]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [0].mutation.rate       inactive  when pipeline[] == 'mutation'\n"
            "    [0].local_search.iters  = 15  in [1, 100]  when pipeline[] == 'local_search'\n"
            "    [1]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [1].mutation.rate       inactive  when pipeline[] == 'mutation'\n"
            "    [1].local_search.iters  = 32  in [1, 100]  when pipeline[] == 'local_search'\n"
            "    [2]                     = 'crossover'  in one of shuffle, crossover, +2 more\n"
            "    [2].mutation.rate       inactive  when pipeline[] == 'mutation'\n"
            "    [2].local_search.iters  inactive  when pipeline[] == 'local_search'\n"
            "    [3]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [3].mutation.rate       inactive  when pipeline[] == 'mutation'\n"
            "    [3].local_search.iters  = 41  in [1, 100]  when pipeline[] == 'local_search'\n"
            "\n"
            "  forbid  count_of(pipeline, {'local_search'}) < 1  ok  margin -2.000"
        )

    def test_hide_inactive_keeps_kept_rows_byte_identical(self):
        space = _memetic_pipeline_space()
        config = {
            "n_ops": 4,
            "pipeline": [
                {"local_search": {"iters": 15}},
                {"local_search": {"iters": 32}},
                "crossover",
                {"local_search": {"iters": 41}},
            ],
        }
        assert ds.pretty(config, space, hide="inactive") == (
            "Config: 14 params, 9 set, 5 inactive, valid\n"
            "  n_ops                     = 4  in [2, 6]\n"
            "  pipeline                  count 4\n"
            "    [0]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [0].local_search.iters  = 15  in [1, 100]  when pipeline[] == 'local_search'\n"
            "    [1]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [1].local_search.iters  = 32  in [1, 100]  when pipeline[] == 'local_search'\n"
            "    [2]                     = 'crossover'  in one of shuffle, crossover, +2 more\n"
            "    [3]                     = 'local_search'  in one of shuffle, crossover, +2 more\n"
            "    [3].local_search.iters  = 41  in [1, 100]  when pipeline[] == 'local_search'\n"
            "  ... 5 inactive not shown\n"
            "\n"
            "  forbid  count_of(pipeline, {'local_search'}) < 1  ok  margin -2.000"
        )


def _wide_constraint_space() -> ds.Space:
    return ds.space(
        ds.param("a").bool(), ds.param("b").bool(), ds.param("c").bool(), ds.param("d").bool()
    ).require(
        (ds.param("a") == True)  # noqa: E712
        | ((ds.param("b") == True) & (ds.param("c") == True) & (ds.param("d") == True))  # noqa: E712
    )


class TestPrettyDispatch:
    def test_a_bare_constraint_matches_its_own_str_at_the_default_width(self):
        space = _small_space()
        assert ds.pretty(space.constraints[0]) == str(space.constraints[0]) == "forbid  lr > 0.5"

    def test_a_bare_constraint_wraps_once_a_caller_asks_for_a_narrower_width(self):
        constraint = _wide_constraint_space().constraints[0]
        assert str(constraint) == "require  a == True or (b == True and c == True and d == True)"
        assert ds.pretty(constraint) == str(constraint)
        assert ds.pretty(constraint, width=40) == (
            "require  a == True or (b == True and c\n         == True and d == True)"
        )
