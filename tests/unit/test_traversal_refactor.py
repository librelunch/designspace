"""Two agreement checks over the shared traversal helpers.

First, `Space._direct_children`'s cached index agrees with the equivalent
per-call scan predicate, over every corpus fixture and every prefix the five
space-guided walkers construct.

Second, `definition_form`, the parsing grammar helper, agrees with
`paths/_grammar._INDEX_RE`, the cheap non-raising alternative for stripping
concrete indices, over every well-formed path the corpus produces.

`_INDEX_RE`'s usage is deliberately not swapped for `definition_form`.
`re.sub` and `re.search` never raise on a malformed path, while
`definition_form` parses through `parse_path` and raises `ResolutionError`
on one. `_lookup_param_shape` in `validate/_validate.py` backs the public
`.validate_param()` and `.remaining_domain()` surface, whose `path` argument
is user-supplied and not guaranteed grammar-clean, so swapping the exception
type and timing for malformed input would be a change to a public
misuse-error contract rather than a refactor.
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
    """The per-call scan predicate, reimplemented standalone.

    The original lived in `config/_flatten.py` and was replaced by the
    indexed method, so the index is checked against this copy.
    """
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
