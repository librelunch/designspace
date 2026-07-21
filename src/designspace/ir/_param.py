"""ParamDef and the condition/constraint IR (API.md, "IR")."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from designspace.expr import BoolExpr
from designspace.ir._chart import Chart
from designspace.ir._domain import Domain, QuantizedSpec
from designspace.ir._priors import PriorSpec


@dataclass(frozen=True)
class ParamDef:
    path: str
    type_kind: str
    domain: Domain
    prior: PriorSpec | None
    periodic: bool
    default: Any
    condition: BoolExpr | None
    tags: frozenset[str]
    meta: MappingProxyType[str, Any]
    chart: Chart | None = None
    quantized: QuantizedSpec | None = None


@dataclass(frozen=True)
class Condition:
    target: str
    expr: BoolExpr
    params: frozenset[str]


@dataclass(frozen=True)
class Constraint:
    expr: BoolExpr
    hard: bool
    # "user" | "bound" | "require" — derived provenance, excluded from the
    # fingerprint preimage. A "bound" or "require" hard constraint stores the
    # DESIRED (feasible) predicate and is feasible-iff-satisfied (opposite of a
    # user forbid); the preimage canonicalizes it to forbidden-state form so
    # feasibility polarity survives without `origin` (API.md, "IR"; "Identity").
    origin: str
    tags: frozenset[str]
    meta: MappingProxyType[str, Any]
    params: frozenset[str]
