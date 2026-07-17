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
from designspace.expr import ArithExpr, BoolExpr, Expr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    Domain,
    IntegerDomain,
    Log,
    OrdinalDomain,
    QuantizedSpec,
    RealDomain,
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
