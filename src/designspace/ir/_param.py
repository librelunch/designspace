"""ParamDef and the condition/constraint IR (API_v3.md, "IR").

`Constraint` is defined here (module map: ir/ owns it from M1) but nothing
populates it yet — `.forbid()`/`.constrain()` are M2's validate/.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from designspace.expr import BoolExpr
from designspace.ir._domain import Domain
from designspace.ir._priors import PriorSpec


@dataclass(frozen=True)
class QuantizedSpec:
    """`.quantized(step=None, factor=None, include_hi=False)` payload.

    Not part of API_v3.md's illustrative ParamDef listing (nor is a
    `prior`-sibling field for weights) — see DECISIONS.md D-2.
    """

    step: float | None
    factor: float | None
    include_hi: bool = False


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
    chart: None = None
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
    origin: str
    tags: frozenset[str]
    meta: MappingProxyType[str, Any]
    params: frozenset[str]
