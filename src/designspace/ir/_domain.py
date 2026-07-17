"""Domain: type-specific declared value space (API_v3.md, "IR").

M1 covers the scalar rows; M3 adds combinatorial (subset, permutation) and
structural (choice, struct) domains. List (lift) domains join at M4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from designspace.expr import ArithExpr


@dataclass(frozen=True)
class RealDomain:
    lo: float | ArithExpr
    hi: float | ArithExpr


@dataclass(frozen=True)
class IntegerDomain:
    lo: int | ArithExpr
    hi: int | ArithExpr


@dataclass(frozen=True)
class CategoricalDomain:
    values: tuple[Any, ...]


@dataclass(frozen=True)
class OrdinalDomain:
    values: tuple[Any, ...]


@dataclass(frozen=True)
class BoolDomain:
    pass


@dataclass(frozen=True)
class SubsetDomain:
    """`.subset(items, min_size=0, max_size=None)`. Set semantics: order
    irrelevant, no duplicates; `max_size=None` means `len(items)`."""

    items: tuple[Any, ...]
    min_size: int
    max_size: int | None


@dataclass(frozen=True)
class PermutationDomain:
    """`.permutation(items)`: all items, any order."""

    items: tuple[Any, ...]


@dataclass(frozen=True)
class ChoiceDomain:
    """`.choice(...)`. `variants` is declaration order (aligns
    `.prior(weights=...)`); `has_payload` names the subset of variants
    whose value nests a payload dict (bare variants and the explicit
    `(name, None)` tuple form nest nothing — just the variant name)."""

    variants: tuple[str, ...]
    has_payload: frozenset[str]


@dataclass(frozen=True)
class StructDomain:
    """`.space(*exprs)` (struct type method): a pure namespace, no value of
    its own — its members are separate, nested `ParamDef` entries."""


Domain = (
    RealDomain
    | IntegerDomain
    | CategoricalDomain
    | OrdinalDomain
    | BoolDomain
    | SubsetDomain
    | PermutationDomain
    | ChoiceDomain
    | StructDomain
)
