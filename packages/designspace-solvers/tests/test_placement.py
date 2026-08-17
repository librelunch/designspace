"""The placement facts every binding shares.

`_placement` holds what a backend does not get to decide for itself. These
tests pin each of those down directly, so a binding that drifts from one
fails here by name rather than through whichever end-to-end fixture happened
to exercise the kind that drifted.
"""

from __future__ import annotations

from typing import get_args

import pytest
from designspace_solvers._placement import (
    GENERATIVE_KINDS,
    decode_random_keys,
    encode_random_keys,
    item_paths,
    native_scalar,
    require_backend,
)

import designspace as ds


def test_generative_kinds_covers_every_kind_but_the_three_that_carry_a_definition() -> None:
    """Read off `ds.TypeKind`, so a kind added to core is claimed rather than
    refused by an envelope nobody widened."""
    assert set(get_args(ds.TypeKind)) - GENERATIVE_KINDS == {"symbolic", "code", "custom"}
    assert set(get_args(ds.TypeKind)) >= GENERATIVE_KINDS


def test_every_binding_states_its_envelope_against_the_shared_vocabulary() -> None:
    """Two bindings placing every generative kind say so by sharing the set;
    the flat one narrows it rather than listing its own from scratch."""
    from designspace_solvers.cmaes import KINDS as cmaes_kinds
    from designspace_solvers.configspace import KINDS as configspace_kinds
    from designspace_solvers.optuna import KINDS as optuna_kinds

    assert optuna_kinds == GENERATIVE_KINDS
    assert configspace_kinds == GENERATIVE_KINDS
    assert cmaes_kinds < GENERATIVE_KINDS


@pytest.mark.parametrize(
    ("build", "native"),
    [
        (lambda: ds.param("x").real(0.0, 1.0), True),
        (lambda: ds.param("x").real(1e-4, 1e-1).log_scale(), True),
        (lambda: ds.param("x").integer(1, 8), True),
        (lambda: ds.param("x").real(1e-6, 1e-2).log_scale().quantized(factor=2.0), False),
        (lambda: ds.param("x").integer(16, 512).quantized(step=16), False),
    ],
    ids=["plain_real", "log_real", "plain_integer", "quantized_real", "quantized_integer"],
)
def test_native_scalar_follows_the_grid_and_the_prior(build, native: bool) -> None:
    """A solver's own distribution reproduces the chart only where there is
    no grid and no shaped prior; everything else goes through unit
    coordinates, which is what keeps a draw on the declared grid."""
    space = ds.space(build())
    assert native_scalar(space.params["x"]) is native


def test_item_paths_names_one_variable_per_item_in_declared_order() -> None:
    assert item_paths("s", 3) == ("s[0]", "s[1]", "s[2]")
    assert item_paths("workers[1].tags", 2) == ("workers[1].tags[0]", "workers[1].tags[1]")
    assert item_paths("s", 0) == ()


def test_random_keys_decode_in_ascending_order() -> None:
    assert decode_random_keys([0.9, 0.1, 0.5], ("a", "b", "c")) == ["b", "c", "a"]


def test_random_keys_round_trip_through_encode() -> None:
    items = ("a", "b", "c", "d")
    for order in (["a", "b", "c", "d"], ["d", "c", "b", "a"], ["c", "a", "d", "b"]):
        assert decode_random_keys(encode_random_keys(order, items), items) == order


@pytest.mark.parametrize("count", [0, 1])
def test_random_keys_handle_a_degenerate_item_count(count: int) -> None:
    """One item has no positions to spread over, and none has no keys."""
    items = ("only",)[:count]
    assert encode_random_keys(list(items), items) == [0.0] * count
    assert decode_random_keys([0.0] * count, items) == list(items)


def test_equal_random_keys_keep_declared_order() -> None:
    """The items are arbitrary objects, and ordering them is the question the
    permutation asks, so a tie is never broken by comparing two of them."""

    class Opaque:
        def __init__(self, name: str) -> None:
            self.name = name

    items = (Opaque("a"), Opaque("b"), Opaque("c"))
    assert decode_random_keys([0.5, 0.5, 0.5], items) == list(items)


def test_require_backend_names_the_extra_that_installs_an_absent_dependency() -> None:
    with pytest.raises(ImportError) as excinfo:
        require_backend("no_such_solver", binding="Demo", needs="NoSuchSolver", extra="demo")
    message = str(excinfo.value)
    assert "the Demo binding needs NoSuchSolver" in message
    assert "designspace-solvers[demo]" in message


def test_require_backend_returns_the_imported_module() -> None:
    assert require_backend("json", binding="Demo", needs="json", extra="demo").dumps([1]) == "[1]"
