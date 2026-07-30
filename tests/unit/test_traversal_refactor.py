"""M10.7 refactor-safety checks: the two things that make the traversal
extraction auditable rather than merely green.

1. `Space._direct_children`'s cached index agrees with the pre-M10.7
   per-call scan predicate, over every corpus fixture and every prefix
   the five space-guided walkers actually construct.
2. `definition_form` (the canonical, parsing grammar helper) agrees with
   `paths/_grammar._INDEX_RE` -- a cheap, non-raising alternative for
   stripping concrete indices, on every well-formed path the corpus
   produces -- confirming the *construction* sweep (which did replace
   every `f"...[]."` / `f"...[{i}]."` / `rindex("[")` idiom with
   `paths/_grammar.py` helpers) lost nothing. `_INDEX_RE` itself was
   independently compiled in `validate/_validate.py` and
   `ops/_structural.py` before M10.7 consolidated it into one shared
   definition (`import re` had no other purpose in either file); this test
   predates that consolidation and was updated to import the shared
   constant rather than keep a third private copy of its own.

   `_INDEX_RE`'s *usage* was deliberately **not** swapped for
   `definition_form`: `re.sub`/`re.search` never raise on a malformed
   path, while `definition_form` parses via `parse_path` and raises
   `ResolutionError` on one. `validate/_validate.py::_lookup_param_shape`
   backs the public `.validate_param()`/`.remaining_domain()` surface,
   whose `path` argument is user-supplied and not guaranteed grammar-clean
   -- swapping the exception type/timing for malformed input is a public
   misuse-error contract change, not a pure refactor, so it stays out of
   this milestone's scope (PLAN.md's own contingency: "if any call site
   can receive a non-grammar path, leave the regex and say so").
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from designspace.config import flatten
from designspace.paths import definition_form
from designspace.paths._grammar import _INDEX_RE

CORPUS_DIR = Path(__file__).resolve().parents[1] / "corpus"
if str(CORPUS_DIR) not in sys.path:
    sys.path.insert(0, str(CORPUS_DIR))

FIXTURES = [
    "flat_hpo",
    "greenhouse",
    "flow_chemistry",
    "job_shop",
    "sat_solver",
    "wind_farm_grid",
    "delivery_routes",
    "solver_portfolio",
    "memetic_pipeline",
    "firmware_buffers",
    "pump_configurator",
    "compiler_pipeline",
    "vi_family",
]


def _build(name: str):
    return importlib.import_module(name).build_space()


def _old_direct_children(space, prefix: str) -> list[str]:
    """The pre-M10.7 `config/_flatten.py::_direct_children` predicate,
    reimplemented standalone (the original was removed in favor of the
    indexed method) so the index can be checked against it."""
    result = []
    for path in space.params:
        if not path.startswith(prefix):
            continue
        remainder = path[len(prefix) :]
        if remainder and "." not in remainder:
            result.append(path)
    return result


def _all_prefixes(space) -> set[str]:
    """Every prefix a space-guided walker could construct against this
    space: "" (root) plus, for every path, the prefix up to and including
    each of its dots (covers struct/choice-variant nesting) and up to a
    trailing "[]." for every list-typed param (covers lift descent)."""
    prefixes = {""}
    for path, pd in space.params.items():
        parts = path.split(".")
        for i in range(1, len(parts)):
            prefixes.add(".".join(parts[:i]) + ".")
        if pd.type_kind == "list":
            prefixes.add(f"{path}[].")
    return prefixes


class TestDirectChildrenIndexEquivalence:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_index_matches_the_old_scan_over_every_constructed_prefix(self, name):
        space = _build(name)
        for prefix in _all_prefixes(space):
            assert list(space._direct_children(prefix)) == _old_direct_children(space, prefix)


class TestDefinitionFormVsIndexRegex:
    @pytest.mark.parametrize("name", FIXTURES)
    def test_agree_on_every_sampled_instance_path(self, name):
        space = _build(name)
        for seed in range(10):
            config = space.sample_one(seed=seed)
            for path in flatten(config, space):
                if "[" not in path:
                    continue
                assert definition_form(path) == _INDEX_RE.sub("[]", path), path
