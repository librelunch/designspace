"""Result dataclasses for validation and constraint evaluation (API_v3.md, "IR").

Only what M2 needs (`ConstraintEval`, `ValidationResult`, `ParamError`) —
`PartialEval` (M6), `ParamDiff` (M7), `SubspaceInfo`/`Capabilities` (M8) join
when their milestones do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from designspace.ir._param import Constraint


@dataclass(frozen=True)
class ConstraintEval:
    constraint: Constraint
    instance_path: str | None
    applicable: bool
    satisfied: bool | None
    margin: float | None


@dataclass(frozen=True)
class ParamError:
    param: str
    reason: str
    value: Any | None


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    param_errors: tuple[ParamError, ...]
    constraint_evals: tuple[ConstraintEval, ...]
