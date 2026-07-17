"""ParamExpr: `ds.param(name)`, dual reference/definition (API_v3.md, "Construction").

Type methods and modifiers are pure recorders: each returns a new, immutable
ParamExpr with pending state updated. No validation happens here — that is
resolve/'s job (the pass pipeline decides what is an error, not the builder).

Internal storage fields are named with a trailing `_spec`/`_value` where the
public modifier method shares the field's natural name (`prior`, `default`,
`quantized`, `meta`) — a dataclass field and a same-named method in one class
body collide (the `def` statement overwrites the field's class-level default),
so the method needs its own name for the state it reads and writes.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

from designspace.errors import ResolutionError
from designspace.expr import (
    ArithExpr,
    BoolExpr,
    Contains,
    Expr,
    PositionOf,
    Size,
    SumOver,
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    Domain,
    IntegerDomain,
    Log,
    OrdinalDomain,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
    Weights,
)


@dataclass(frozen=True, eq=False)
class ParamExpr(ArithExpr, BoolExpr):
    """A parameter, in reference position (bare) or definition position
    (after a type method and any modifiers).
    """

    path: str
    type_kind: str | None = None
    type_calls: tuple[str, ...] = ()
    domain: Domain | None = None
    periodic: builtins.bool = False
    prior_spec: Any = None
    quantized_spec: QuantizedSpec | None = None
    default_value: Any = None
    condition: BoolExpr | None = None
    tags: frozenset[str] = frozenset()
    meta_map: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    # -- structural payloads (M3): raw builder-time state for .choice()/.space(),
    # merged into the flat IR during resolution (resolve/_relocate.py). Not part
    # of `domain` because the domain only needs variant names/has_payload, not
    # the child Spaces themselves.
    choice_payloads: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    struct_space: Any = None  # Space | None; typed Any to avoid an import cycle

    @property
    def kind(self) -> str:
        return "ref"

    @property
    def children(self) -> tuple[Expr, ...]:
        return ()

    @property
    def params(self) -> frozenset[str]:
        return frozenset({self.path})

    # -- type methods (exactly one expected; enforced at resolution) --------

    def real(
        self, lo: float | ArithExpr, hi: float | ArithExpr, periodic: builtins.bool = False
    ) -> ParamExpr:
        return replace(
            self,
            type_kind="real",
            domain=RealDomain(lo, hi),
            periodic=periodic,
            type_calls=(*self.type_calls, "real"),
        )

    def integer(self, lo: int | ArithExpr, hi: int | ArithExpr) -> ParamExpr:
        return replace(
            self,
            type_kind="integer",
            domain=IntegerDomain(lo, hi),
            type_calls=(*self.type_calls, "integer"),
        )

    def categorical(self, *values: Any) -> ParamExpr:
        return replace(
            self,
            type_kind="categorical",
            domain=CategoricalDomain(tuple(values)),
            type_calls=(*self.type_calls, "categorical"),
        )

    def ordinal(self, *values: Any) -> ParamExpr:
        return replace(
            self,
            type_kind="ordinal",
            domain=OrdinalDomain(tuple(values)),
            type_calls=(*self.type_calls, "ordinal"),
        )

    def bool(self) -> ParamExpr:
        return replace(
            self,
            type_kind="bool",
            domain=BoolDomain(),
            type_calls=(*self.type_calls, "bool"),
        )

    def subset(
        self, items: Sequence[Any], min_size: int = 0, max_size: int | None = None
    ) -> ParamExpr:
        return replace(
            self,
            type_kind="subset",
            domain=SubsetDomain(tuple(items), min_size, max_size),
            type_calls=(*self.type_calls, "subset"),
        )

    def permutation(self, items: Sequence[Any]) -> ParamExpr:
        return replace(
            self,
            type_kind="permutation",
            domain=PermutationDomain(tuple(items)),
            type_calls=(*self.type_calls, "permutation"),
        )

    def choice(
        self, *variants: str | tuple[str, Any], **keyword_variants: Any
    ) -> ParamExpr:
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
        return replace(
            self,
            type_kind="choice",
            domain=ChoiceDomain(tuple(names), frozenset(has_payload)),
            choice_payloads=MappingProxyType(payloads),
            type_calls=(*self.type_calls, "choice"),
        )

    def space(self, *exprs: ParamExpr) -> ParamExpr:
        from designspace.resolve._pipeline import resolve_space

        child = resolve_space(exprs)
        return replace(
            self,
            type_kind="space",
            domain=StructDomain(),
            struct_space=child,
            type_calls=(*self.type_calls, "space"),
        )

    # -- combinatorial expression methods (subset/permutation only; validity
    # is a resolution-time check, not a construction-time one, per M0's "no
    # evaluation, no resolution happens here") -------------------------------

    def contains(self, item: Any) -> BoolExpr:
        return Contains(self, item)

    def size(self) -> ArithExpr:
        return Size(self)

    def sum_over(self, mapping: dict[Any, float]) -> ArithExpr:
        return SumOver(self, MappingProxyType(dict(mapping)))

    def position_of(self, item: Any) -> ArithExpr:
        return PositionOf(self, item)

    # -- domain-level modifiers (last-write-wins) ----------------------------

    def prior(self, dist: Any = None, *, weights: Sequence[float] | None = None) -> ParamExpr:
        if (dist is None) == (weights is None):
            raise ResolutionError(
                f"param {self.path!r}: prior() requires exactly one of a "
                "distribution or weights=..."
            )
        if weights is not None:
            return replace(self, prior_spec=Weights(tuple(weights)))
        return replace(self, prior_spec=dist)

    def log_scale(self) -> ParamExpr:
        return self.prior(Log())

    def quantized(
        self,
        step: float | None = None,
        factor: float | None = None,
        include_hi: builtins.bool = False,
    ) -> ParamExpr:
        return replace(self, quantized_spec=QuantizedSpec(step, factor, include_hi))

    def default(self, value: Any) -> ParamExpr:
        return replace(self, default_value=value)

    # -- identity-level modifiers (accumulate, except default which is LWW) -

    def when(self, condition: BoolExpr) -> ParamExpr:
        if not isinstance(condition, BoolExpr):
            raise TypeError(".when() requires a BoolExpr condition")
        merged = condition if self.condition is None else (self.condition & condition)
        return replace(self, condition=merged)

    def tag(self, *tags: str) -> ParamExpr:
        return replace(self, tags=self.tags | frozenset(tags))

    def meta(self, mapping: dict[str, Any] | None = None, **kwargs: Any) -> ParamExpr:
        merged = dict(self.meta_map)
        if mapping:
            merged.update(mapping)
        merged.update(kwargs)
        return replace(self, meta_map=MappingProxyType(merged))
