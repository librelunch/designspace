"""Builder view types (API_v3.md, "Builder view types"; DECISIONS.md D-27,
D-29).

`ds.param(name)` returns a `FreshParamExpr` — a `ParamExpr` carrying the 9
type methods. Each type method narrows to a type-specific view that omits
the type methods, so a second one is a static type error (and, via
`ParamExpr.__getattr__`, still the path-named row-2 `ResolutionError` at
runtime — never a bare `AttributeError`). `.repeat()` — available on any
typed view, not on `FreshParamExpr` or the base — narrows to `ListParamExpr`,
which re-offers `.repeat()` for nested/variadic lifts.

Class shape, bottom to top:
    ParamExpr                      (build/_paramexpr.py — no type methods, no .repeat();
                                     type_kind: ClassVar[str | None] = None)
    +-- FreshParamExpr             9 type methods only; inherits type_kind = None
    +-- _TypedParamExpr            .repeat() only — shared by every narrowed view
        +-- _NumericParamExpr      + .log_scale()/.quantized() — Real/Integer only
        |   +-- RealParamExpr      type_kind = "real"
        |   +-- IntegerParamExpr   type_kind = "integer"
        +-- BoolParamExpr          type_kind = "bool"
        +-- CategoricalParamExpr   type_kind = "categorical"
        +-- OrdinalParamExpr       type_kind = "ordinal"
        +-- SubsetParamExpr        type_kind = "subset"
        +-- PermutationParamExpr   type_kind = "permutation"
        +-- ChoiceParamExpr        type_kind = "choice"
        +-- StructParamExpr        type_kind = "space"
        +-- ListParamExpr          type_kind = "list"

None of these subclasses add fields (API_v3.md: "they add no state beyond
ParamExpr"); each is a thin method surface (plus, on the 10 leaves, a fixed
`type_kind` override) over the same dataclass fields, constructed via
`ParamExpr._as()`. None needs `@dataclass` redecoration — `type_kind` was
declared `ClassVar` on `ParamExpr` itself, so dataclass field processing
never sees it as a field anywhere in the hierarchy; a plain class-attribute
override is enough (DECISIONS.md D-29), and no subclass's `__init__` ever
accepts `type_kind` as an argument.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import Any, ClassVar, Self

from designspace.build._paramexpr import ParamExpr, _ElementSnapshot
from designspace.errors import ResolutionError
from designspace.expr import ArithExpr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    IntegerDomain,
    Log,
    OrdinalDomain,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
)


class FreshParamExpr(ParamExpr):
    """`ds.param(name)`'s return type: a `ParamExpr` that additionally
    carries the 9 type methods, each choosing the param's type exactly
    once (API_v3.md, "Construction" / "Builder view types")."""

    def real(
        self, lo: float | ArithExpr, hi: float | ArithExpr, periodic: builtins.bool = False
    ) -> RealParamExpr:
        return self._as(RealParamExpr, domain=RealDomain(lo, hi), periodic=periodic)

    def integer(self, lo: int | ArithExpr, hi: int | ArithExpr) -> IntegerParamExpr:
        return self._as(IntegerParamExpr, domain=IntegerDomain(lo, hi))

    def categorical(self, *values: Any) -> CategoricalParamExpr:
        return self._as(CategoricalParamExpr, domain=CategoricalDomain(tuple(values)))

    def ordinal(self, *values: Any) -> OrdinalParamExpr:
        return self._as(OrdinalParamExpr, domain=OrdinalDomain(tuple(values)))

    def bool(self) -> BoolParamExpr:
        return self._as(BoolParamExpr, domain=BoolDomain())

    def subset(
        self, items: Sequence[Any], min_size: int = 0, max_size: int | None = None
    ) -> SubsetParamExpr:
        return self._as(
            SubsetParamExpr, domain=SubsetDomain(tuple(items), min_size, max_size)
        )

    def permutation(self, items: Sequence[Any]) -> PermutationParamExpr:
        return self._as(PermutationParamExpr, domain=PermutationDomain(tuple(items)))

    def choice(
        self, *variants: str | tuple[str, Any], **keyword_variants: Any
    ) -> ChoiceParamExpr:
        names: list[str] = []
        payloads: dict[str, Any] = {}
        has_payload: set[str] = set()
        for v in variants:
            if isinstance(v, str):
                names.append(v)
            else:
                name, payload = v
                names.append(name)
                if payload is not None:
                    payloads[name] = payload
                    has_payload.add(name)
        for name, payload in keyword_variants.items():
            names.append(name)
            payloads[name] = payload
            has_payload.add(name)
        return self._as(
            ChoiceParamExpr,
            domain=ChoiceDomain(tuple(names), frozenset(has_payload)),
            choice_payloads=MappingProxyType(payloads),
        )

    def space(self, *exprs: Any) -> StructParamExpr:
        from designspace.build._space import Space
        from designspace.resolve._pipeline import resolve_space

        # `.space(prebuilt: Space)` (DECISIONS.md D-20/D-15): the only route
        # to per-element constraints on a repeated struct — the inline
        # `.space(*exprs)` form has nowhere to hang a `.forbid()`. A single
        # positional `Space` argument is unambiguous: the inline form's
        # `*exprs` are always bare `ParamExpr`s, never a `Space`.
        if len(exprs) == 1 and isinstance(exprs[0], Space):
            child = exprs[0]
        else:
            child = resolve_space(exprs)
        return self._as(StructParamExpr, domain=StructDomain(), struct_space=child)


class _TypedParamExpr(ParamExpr):
    """Shared by every narrowed view (a type has been chosen, or a lift
    applied): `.repeat()` (API_v3.md, "The lift") — the one modifier valid
    across every element type, including a list itself (nested lifts)."""

    def repeat(self, *counts: int | ArithExpr) -> ListParamExpr:
        if len(counts) == 0:
            raise ResolutionError(f"param {self.path!r}: repeat() requires at least one count")
        # Variadic sugar: `.repeat(2, 3)` reads as shape (2, 3), first count
        # outermost, desugaring to chained lifts in *reverse* order —
        # `.repeat(3).repeat(2)` (API_v3.md, "The lift").
        ordered = list(reversed(counts))
        result = self._repeat_one(ordered[0])
        for c in ordered[1:]:
            result = result._repeat_one(c)
        return result

    def _repeat_one(self, count: int | ArithExpr) -> ListParamExpr:
        if isinstance(self, ListParamExpr):
            assert self.lift is not None
            inner = self.lift
        else:
            # type(self) is always a concrete leaf here (DECISIONS.md D-29):
            # .repeat() only exists on typed views, and modifiers preserve
            # the caller's class via replace(), so this is exactly the view
            # the element was declared with — e.g. RealParamExpr.
            inner = _ElementSnapshot(
                element_class=type(self),
                domain=self.domain,
                prior_spec=self.prior_spec,
                quantized_spec=self.quantized_spec,
                periodic=self.periodic,
                default_value=self.default_value,
                struct_space=self.struct_space,
                choice_payloads=self.choice_payloads,
            )
        new_lift = _ElementSnapshot(element_class=ListParamExpr, element=inner, count=count)
        return self._as(
            ListParamExpr,
            domain=None,
            prior_spec=None,
            quantized_spec=None,
            periodic=False,
            default_value=None,
            struct_space=None,
            choice_payloads=MappingProxyType({}),
            lift=new_lift,
        )


class _NumericParamExpr(_TypedParamExpr):
    """Real/Integer only: `.log_scale()`/`.quantized()` (API_v3.md,
    "Modifiers and Layering"). Absent from every other view — misuse
    (`.categorical(...).log_scale()`) is a static `attr-defined` error and,
    at runtime, `ParamExpr.__getattr__` re-raises it as row 11's
    path-named `ResolutionError` (DECISIONS.md D-28)."""

    def log_scale(self) -> Self:
        return self.prior(Log())

    def quantized(
        self,
        step: float | None = None,
        factor: float | None = None,
        include_hi: builtins.bool = False,
    ) -> Self:
        return replace(self, quantized_spec=QuantizedSpec(step, factor, include_hi))


class RealParamExpr(_NumericParamExpr):
    type_kind: ClassVar[str] = "real"


class IntegerParamExpr(_NumericParamExpr):
    type_kind: ClassVar[str] = "integer"


class BoolParamExpr(_TypedParamExpr):
    # Already a BoolExpr transitively (ParamExpr is BoolExpr-inheriting) —
    # API_v3.md: "BoolParamExpr is additionally a BoolExpr (a boolean param
    # is usable directly as a condition)".
    type_kind: ClassVar[str] = "bool"


class CategoricalParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "categorical"


class OrdinalParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "ordinal"


class SubsetParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "subset"


class PermutationParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "permutation"


class ChoiceParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "choice"


class StructParamExpr(_TypedParamExpr):
    type_kind: ClassVar[str] = "space"


class ListParamExpr(_TypedParamExpr):
    """`.repeat()`'s return type; re-offers `.repeat()` (inherited from
    `_TypedParamExpr`) for nested/variadic lifts."""

    type_kind: ClassVar[str] = "list"
