"""Domain: type-specific declared value space (API_v3.md, "IR").

M1 covers the scalar rows only; structural/combinatorial/list domains join
in later milestones.
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


Domain = RealDomain | IntegerDomain | CategoricalDomain | OrdinalDomain | BoolDomain
