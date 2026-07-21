"""Domain: type-specific declared value space (API.md, "IR").

M1 covers the scalar rows; M3 adds combinatorial (subset, permutation) and
structural (choice, struct) domains. M4 adds the recursive list (lift)
domain — see DECISIONS.md D-18.

`QuantizedSpec` lives here (not ir/_param.py, where API.md's illustrative
ParamDef listing might suggest) because `ListDomain.element_quantized` needs
it and ir/_param.py already imports from this module — defining it in
ir/_param.py would make that a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from designspace.expr import ArithExpr

if TYPE_CHECKING:
    from designspace.ir._chart import Chart
    from designspace.ir._priors import PriorSpec


@dataclass(frozen=True)
class QuantizedSpec:
    """`.quantized(step=None, factor=None, include_hi=False)` payload."""

    step: float | None
    factor: float | None
    include_hi: bool = False


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


@dataclass(frozen=True)
class ListDomain:
    """`.repeat(count)` (the lift). Recursive — `element_domain` is another
    `ListDomain` for a chained/variadic `.repeat().repeat()`. Every fact
    about the element (chart, prior, quantization, periodicity, its own
    pre-lift default) lives here rather than on the enclosing `ParamDef`,
    which stays chartless (see DECISIONS.md D-18): a struct or choice
    element's *descendant* params are relocated into `Space.params` under
    a `"[]"`-bracketed definition-path prefix instead (`"edges[].src"`),
    exactly like M3's struct/choice relocation, just with `"[]."` in place
    of `"."` — this domain only carries the element's own leaf-level facts.
    """

    element_kind: str
    element_domain: Domain
    element_chart: Chart | None
    element_prior: PriorSpec | None
    element_periodic: bool
    element_quantized: QuantizedSpec | None
    element_default: Any
    count: int | ArithExpr
    list_default: Any = None
    # `tuple[Constraint, ...]`; typed Any to avoid a cycle (ir/_param.py,
    # where Constraint is defined, imports this module for `Domain`).
    # Constraints declared on a `.space(prebuilt)` element (DECISIONS.md
    # D-20) — a *template*, `"[]"`-prefixed like the element's descendant
    # params, expanded per active instance at evaluation time.
    element_constraints: Any = ()


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
    | ListDomain
)
