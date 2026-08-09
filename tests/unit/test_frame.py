"""Unit tests for `frame/`, the DataFrame output.

See API.md, "Config Representation" > "DataFrame output". This covers what
no corpus fixture exercises: the static-count `Array` dtype rule, including
the nested `List(Array(...))` an outer-dynamic, inner-static lift produces,
and the polars-absent error path.

The per-kind dtype table and the null-for-inactive cross-fixture laws live
in `tests/conformance/test_dataframe.py`. Bespoke container-shaped column
checks live in `tests/corpus/test_delivery_routes.py` and
`tests/corpus/test_memetic_pipeline.py`.
"""

from __future__ import annotations

import sys

import pytest

import designspace as ds

# The two tests below run on a polars-free install and are the reason this
# module imports polars inside the tests that need it rather than at the top:
# a module-level import would take the missing-extra error path out of the run
# that is meant to check it. Setting the `sys.modules` entry to `None` makes
# `import polars` raise whether or not the package is installed.


def test_sample_raises_import_error_naming_the_extra_when_polars_missing(monkeypatch):
    space = ds.space(ds.param("x").real(0.0, 1.0))
    monkeypatch.setitem(sys.modules, "polars", None)
    with pytest.raises(ImportError, match=r"designspace\[polars\]"):
        space.sample(3)


def test_sample_one_and_sample_dicts_unaffected_by_missing_polars(monkeypatch):
    space = ds.space(ds.param("x").real(0.0, 1.0))
    monkeypatch.setitem(sys.modules, "polars", None)
    assert 0.0 <= space.sample_one(seed=0)["x"] <= 1.0
    assert len(space.sample_dicts(3, seed=0)) == 3


@pytest.mark.requires_polars
def test_static_repeat_uses_array_dtype():
    import polars as pl

    space = ds.space(ds.param("weights").real(0.0, 1.0).repeat(3))
    df = space.sample(5, seed=0)
    dt = df.schema["weights"]
    assert isinstance(dt, pl.Array)
    assert dt.size == 3
    assert dt.inner == pl.Float64
    for row in df["weights"].to_list():
        assert len(row) == 3


@pytest.mark.requires_polars
def test_dynamic_outer_static_inner_yields_list_of_array():
    import polars as pl

    n = ds.param("n").integer(1, 4)
    grid = ds.param("cell").integer(0, 9).repeat(2).repeat(n)
    space = ds.space(n, grid)
    df = space.sample(20, seed=1)
    dt = df.schema["cell"]
    assert isinstance(dt, pl.List)
    assert isinstance(dt.inner, pl.Array)
    assert dt.inner.size == 2
    assert dt.inner.inner == pl.Int64
    for i, row in enumerate(df["cell"].to_list()):
        assert len(row) == df["n"][i]
        for inner in row:
            assert len(inner) == 2
