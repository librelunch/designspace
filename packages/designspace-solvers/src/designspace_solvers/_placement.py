"""What every binding agrees on before it places a parameter.

A backend picks its own solver and its own layout, but a few decisions are
not its own to make. Which kinds carry a coordinate at all is a fact about
the representation. Whether a solver's own real or integer distribution
reproduces a declared chart follows from the chart and the prior, not from
the solver. A subset's inclusion flags, a permutation's keys, and the order
those keys decode to are one representation, and it reads the same whichever
binding wrote it. What that representation does not carry, a subset's
declared size among it, is named here too, so a binding states the bound in
its own terms rather than discovering its absence in a sampled value. Each is
stated once here, so a change to core's kinds or charts lands in one place
rather than in every binding that happened to hold a copy of it.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from typing import Any, get_args

import designspace as ds

__all__ = [
    "GENERATIVE_KINDS",
    "decode_random_keys",
    "encode_random_keys",
    "item_paths",
    "native_scalar",
    "require_backend",
    "subset_bounds",
]

#: The kinds that carry a definition rather than a coordinate. A `symbolic`
#: or `code` parameter states a program, and a `custom` parameter's genotype
#: is its type author's to supply. Generating any of the three is a strategy
#: the library leaves to its consumer.
_NON_GENERATIVE = frozenset({"symbolic", "code", "custom"})

#: Every parameter kind a solver can be asked to generate a value for. Read
#: off `ds.TypeKind` rather than listed, so a kind added to core is claimed
#: here on the day it lands and the binding that has no placement for it
#: fails under the solvers gate, rather than being refused quietly by an
#: envelope nobody remembered to widen. A backend narrows this to what its
#: own layout holds.
GENERATIVE_KINDS = frozenset(get_args(ds.TypeKind)) - _NON_GENERATIVE


def require_backend(module: str, *, binding: str, needs: str, extra: str) -> Any:
    """Import a backend's solver, or name the extra that installs it.

    Parameters
    ----------
    module : str
        The module to import.
    binding : str
        The binding's name, as a refusal from it reads.
    needs : str
        The dependency's name, as its own documentation spells it.
    extra : str
        The extra that installs it.

    Returns
    -------
    Any
        The imported module.

    Raises
    ------
    ImportError
        When the dependency is absent, naming the extra to install.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        raise ImportError(
            f"the {binding} binding needs {needs}, which is an optional dependency. "
            f"Install it with `pip install designspace-solvers[{extra}]`."
        ) from exc


def native_scalar(defn: ds.ParamDef) -> bool:
    """Whether a solver's own distribution reproduces a scalar's chart.

    It does when the parameter carries no grid, and either no prior or a log
    scale: every solver bound here draws uniformly or log-uniformly between
    two ends. Anything else, a shaped prior or a quantization, is placed in
    unit coordinates and read back through the chart instead, which
    reproduces the declared shape and lands on the declared grid without the
    solver representing either. Reading the domain's ends and drawing
    between them would ignore both and produce values the space rejects.

    Parameters
    ----------
    defn : designspace.ParamDef
        A real or integer parameter's definition.

    Returns
    -------
    bool
        True where the solver's own distribution suffices.
    """
    return defn.quantized is None and (defn.prior is None or isinstance(defn.prior, ds.Log))


def item_paths(path: str, count: int) -> tuple[str, ...]:
    """Name the solver variables a subset or permutation places per item.

    A subset places one inclusion flag per item and a permutation one key
    per item, and a solver takes one variable for each. `flatten` keeps both
    kinds whole, `s` holding the whole included list, so these names belong
    to the solver's own namespace rather than to a flat config. They borrow
    the bracket form a lift's element uses, `s[0]` through `s[n-1]`, and
    every binding spells them the same way, so a name read off one solver's
    output means what it means in another's.

    A subset's flags carry its membership and nothing else. On their own they
    admit every combination, so a declared `min_size` or `max_size` is no
    part of what they say. A binding states the bound in its own terms,
    reading it from `subset_bounds`, or refuses the parameter by path.
    Placing the flags and leaving the bound out samples selections the space
    calls out of bounds.

    Parameters
    ----------
    path : str
        The parameter's own definition path.
    count : int
        How many items it declares.

    Returns
    -------
    tuple[str, ...]
        One name per item, in declared order.
    """
    return tuple(f"{path}[{i}]" for i in range(count))


def subset_bounds(domain: ds.SubsetDomain) -> tuple[int, int]:
    """The selection sizes a subset admits, as two numbers.

    A declaration that set no upper bound leaves `max_size` at `None`, which
    means every item. Resolving that here gives every binding one pair to
    read and one place for the reading to be wrong.

    Parameters
    ----------
    domain : designspace.SubsetDomain
        A subset parameter's domain.

    Returns
    -------
    tuple[int, int]
        The smallest and largest admitted size, both inclusive. A pair of
        `(0, len(items))` is the bound that excludes nothing.
    """
    high = len(domain.items) if domain.max_size is None else domain.max_size
    return domain.min_size, high


def decode_random_keys(keys: Sequence[float], items: Sequence[Any]) -> list[Any]:
    """Read a permutation off one continuous coordinate per item.

    The items in ascending key order. Every draw decodes to a valid
    ordering, so there is nothing to reject and nothing to repair. Two equal
    keys keep their declared order, the items themselves never being
    compared: they are arbitrary objects, and ordering them is exactly what
    the permutation is being asked for.

    Parameters
    ----------
    keys : Sequence[float]
        One coordinate per item, in declared order.
    items : Sequence[Any]
        The declared items.

    Returns
    -------
    list[Any]
        The items, ordered by their keys.
    """
    paired = sorted(zip(keys, items, strict=True), key=lambda pair: pair[0])
    return [item for _, item in paired]


def encode_random_keys(order: Sequence[Any], items: Sequence[Any]) -> list[float]:
    """The keys `decode_random_keys` reads back as `order`.

    Each item's key is its position in `order`, spread evenly across
    `[0, 1]`. A single item has no positions to spread over and takes zero.

    Parameters
    ----------
    order : Sequence[Any]
        The permutation to encode.
    items : Sequence[Any]
        The declared items, in declared order.

    Returns
    -------
    list[float]
        One coordinate per item, in declared order.
    """
    count = len(items)
    if count < 2:
        return [0.0] * count
    return [list(order).index(item) / (count - 1) for item in items]
