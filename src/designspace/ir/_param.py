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
    # "user" | "bound" | "require" | "discourage" — derived provenance,
    # excluded from the fingerprint preimage. Storage is an implementation
    # detail; read `kind`/`feasible_when_satisfied` instead. A constraint whose
    # stored predicate is the polarity-opposite of its `origin="user"` baseline
    # (require vs forbid; discourage vs encourage) or a bound sugar stores that
    # predicate verbatim; the preimage canonicalizes it to the baseline polarity
    # so `origin` stays non-load-bearing (API.md, "IR"; "Identity").
    origin: str
    tags: frozenset[str]
    meta: MappingProxyType[str, Any]
    params: frozenset[str]

    @property
    def kind(self) -> str:
        """The builder verb that created this constraint, for display and
        dispatch: ``"forbid"`` | ``"require"`` | ``"encourage"`` |
        ``"discourage"`` | ``"bound"`` (the last is the implicit constraint an
        expression bound desugars to). Derived from ``(origin, hard)`` so
        consumers never re-derive polarity by hand (API.md, "Constraints")."""
        if self.origin == "bound":
            return "bound"
        if self.origin == "require":
            return "require"
        if self.origin == "discourage":
            return "discourage"
        return "forbid" if self.hard else "encourage"

    @property
    def feasible_when_satisfied(self) -> bool:
        """Whether the stored ``expr`` is the **desired** predicate (satisfied
        is the good outcome) rather than a **forbidden** one (satisfied is the
        bad outcome). ``False`` only for ``forbid``/``discourage`` — the two
        verbs that name a bad state. This is the single source of truth for
        "is this constraint supposed to hold?"; ``ConstraintEval.violated``
        reads it, so forbid/require/encourage/discourage all report
        consistently (API.md, "Constraints and Feasibility")."""
        return self.kind not in ("forbid", "discourage")
