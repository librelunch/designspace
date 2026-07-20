"""Space: the resolved container returned by `ds.space()` (API_v3.md, "Space").

M1 exposes only what flat scalar spaces need; M2 adds feasibility
(`.forbid()`/`.constrain()`), Kleene-aware validation, and the reference
sampler. `.anchor()` and space-level `.meta()` stay out of scope for M2 —
IMPLEMENTATION_PLAN.md's M2 Build line names only charts/eval/validate/
sample, and no M2 gate or corpus item exercises anchors (see DECISIONS.md,
which supersedes D-3's forward guess that anchors were M2's).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

import numpy as np

from designspace.expr import BoolExpr
from designspace.ir import (
    Condition,
    Constraint,
    ConstraintEval,
    ParamDef,
    PartialEval,
    RemainingDomain,
    ValidationResult,
)

if TYPE_CHECKING:
    from designspace.identity._fingerprint import FingerprintScope, FingerprintUnserializable
    from designspace.identity._ir_codec import OnUnserializable

Seed = int | np.random.Generator | None


@dataclass(frozen=True)
class Space:
    params: MappingProxyType[str, ParamDef]
    conditions: tuple[Condition, ...]
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)

    @property
    def n_params(self) -> int:
        return len(self.params)

    @property
    def is_conditional(self) -> bool:
        return any(p.condition is not None for p in self.params.values())

    def forbid(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=True, tags=tags, meta=meta)

    def constrain(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=False, tags=tags, meta=meta)

    def validate(self, config: dict[str, Any]) -> ValidationResult:
        from designspace.validate import validate as _validate

        return _validate(self, config)

    def validate_param(
        self, path: str, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        from designspace.validate import validate_param as _validate_param

        return _validate_param(self, path, value, context)

    def is_feasible(self, config: dict[str, Any]) -> bool:
        from designspace.validate import is_feasible as _is_feasible

        return _is_feasible(self, config)

    def infeasibility_reasons(self, config: dict[str, Any]) -> list[str]:
        from designspace.validate import infeasibility_reasons as _infeasibility_reasons

        return _infeasibility_reasons(self, config)

    def evaluate_constraints(self, config: dict[str, Any]) -> list[ConstraintEval]:
        from designspace.validate import evaluate_constraints as _evaluate_constraints

        return _evaluate_constraints(self, config)

    def sample_one(self, seed: Seed = None, reject_soft: bool = False) -> dict[str, Any]:
        from designspace.sample import sample_one as _sample_one

        return _sample_one(self, seed=seed, reject_soft=reject_soft)

    def sample_dicts(
        self, n: int, seed: Seed = None, reject_soft: bool = False
    ) -> list[dict[str, Any]]:
        from designspace.sample import sample_dicts as _sample_dicts

        return _sample_dicts(self, n, seed=seed, reject_soft=reject_soft)

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        from designspace.defaults import apply_defaults as _apply_defaults

        return _apply_defaults(self, config)

    @property
    def has_complete_defaults(self) -> bool:
        from designspace.defaults import apply_defaults as _apply_defaults
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, _apply_defaults(self, {}))

    def evaluate_partial(self, config: dict[str, Any]) -> PartialEval:
        from designspace.partial import evaluate_partial as _evaluate_partial

        return _evaluate_partial(self, config)

    def remaining_domain(self, path: str, config: dict[str, Any]) -> RemainingDomain | None:
        from designspace.partial import remaining_domain as _remaining_domain

        return _remaining_domain(self, path, config)

    def param_activity(self, config: dict[str, Any]) -> dict[str, str]:
        from designspace.partial import param_activity as _param_activity

        return _param_activity(self, config)

    def is_complete(self, config: dict[str, Any]) -> bool:
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, config)

    def missing_params(self, config: dict[str, Any]) -> list[str]:
        from designspace.partial import missing_params as _missing_params

        return _missing_params(self, config)

    @property
    def topological_order(self) -> list[str]:
        from designspace.partial import topological_order as _topological_order

        return _topological_order(self)

    def next_assignable(self, config: dict[str, Any]) -> list[str]:
        from designspace.partial import next_assignable as _next_assignable

        return _next_assignable(self, config)

    def to_json(self, on_unserializable: OnUnserializable = "raise") -> dict[str, Any]:
        from designspace.serialize import to_json as _to_json

        return _to_json(self, on_unserializable=on_unserializable)

    @classmethod
    def from_json(
        cls, data: dict[str, Any], custom_types: dict[str, Any] | None = None
    ) -> Space:
        from designspace.serialize import from_json as _from_json

        return _from_json(data, custom_types=custom_types)

    def fingerprint(
        self,
        scope: FingerprintScope = "full",
        on_unserializable: FingerprintUnserializable = "raise",
    ) -> str:
        from designspace.identity import fingerprint as _fingerprint

        return _fingerprint(self, scope=scope, on_unserializable=on_unserializable)
