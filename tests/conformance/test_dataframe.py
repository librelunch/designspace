"""Conformance laws: DataFrame output (PLAN.md M10 gate: "dtype table
asserted per corpus fixture; null-for-inactive; column names == path
grammar").

Container-shaped top-level columns (struct/list/choice) are exercised by
bespoke, fixture-specific assertions in `tests/corpus/test_delivery_routes.py`
and `tests/corpus/test_memetic_pipeline.py` — the general laws here stay
scoped to what holds for every corpus fixture without per-kind knowledge:
row count, the top-level column-name set, and scalar-column null placement
cross-checked against the already-conformance-tested `sample_dicts` path
(same seed, same n -> the same underlying draws, since both go through the
same per-draw sampling primitive).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("name", FIXTURES)
def test_top_level_columns_match_path_grammar(name):
    space = _build(name)
    df = space.sample(5, seed=0)
    expected: set[str] = set()
    for child in space._direct_children(""):
        pd = space.params[child]
        expected.add(child)
        if pd.type_kind == "choice":
            expected.update(f"{child}.{variant}" for variant in pd.domain.has_payload)
    assert set(df.columns) == expected


@pytest.mark.parametrize("name", FIXTURES)
def test_row_count_matches_n(name):
    space = _build(name)
    assert space.sample(37, seed=1).height == 37


@pytest.mark.parametrize("name", FIXTURES)
def test_scalar_column_null_matches_dict_absence(name):
    space = _build(name)
    n = 60
    df = space.sample(n, seed=2)
    dicts = space.sample_dicts(n, seed=2)
    for child in space._direct_children(""):
        pd = space.params[child]
        if pd.type_kind in ("space", "list", "choice"):
            continue  # container-shaped; covered by per-fixture tests
        column = df[child].to_list()
        for i in range(n):
            present = child in dicts[i]
            assert (column[i] is None) != present, (name, child, i)
            if present and pd.type_kind not in ("symbolic", "code", "custom"):
                assert column[i] == dicts[i][child], (name, child, i)
