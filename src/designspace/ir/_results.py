"""Result dataclasses for validation and constraint evaluation (API_v3.md, "IR").

M2 needs (`ConstraintEval`, `ValidationResult`, `ParamError`); M6 adds
`PartialEval` and the `RemainingDomain` descriptor family; M7 adds
`ParamDiff`. `SubspaceInfo`/`Capabilities` (M8) join when their milestone does.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from designspace.ir._domain import QuantizedSpec
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


@dataclass(frozen=True)
class PartialEval:
    """`.evaluate_partial(config)` (API_v3.md, "Space — Partial Configs").

    `param_status` is keyed by definition *and* instance path (a lift's
    instances only appear once its count is determined — see
    `partial/_partial.py`).
    """

    param_status: MappingProxyType[str, str]
    evaluable_constraints: tuple[ConstraintEval, ...]
    pending_constraints: tuple[Constraint, ...]
    n_remaining: int


# -- `remaining_domain`'s per-kind descriptor (API_v3.md, "IR") — a closed
# union. Sound, not complete: never excludes a still-feasible value (may
# admit values an unreduced multi-operand coupling would forbid).


@dataclass(frozen=True)
class RealRemaining:
    lo: float
    hi: float
    lo_inclusive: bool
    hi_inclusive: bool
    grid: QuantizedSpec | None


@dataclass(frozen=True)
class IntegerRemaining:
    lo: int
    hi: int
    grid: QuantizedSpec | None


@dataclass(frozen=True)
class ValueRemaining:
    """bool, categorical, ordinal, choice — `values` are still-legal values
    (choice: still-legal variant names)."""

    values: tuple[Any, ...]


@dataclass(frozen=True)
class SubsetRemaining:
    forced_in: tuple[Any, ...]
    forced_out: tuple[Any, ...]
    free: tuple[Any, ...]
    min_size: int
    max_size: int


@dataclass(frozen=True)
class PermutationRemaining:
    """No per-item reduction under the guarantee (API_v3.md, "IR") — always
    echoes the declared items."""

    items: tuple[Any, ...]


RemainingDomain = (
    RealRemaining | IntegerRemaining | ValueRemaining | SubsetRemaining | PermutationRemaining
)


@dataclass(frozen=True)
class ParamDiff:
    """`ds.config_diff(a, b, space)` entry (API_v3.md, "Config Utilities")."""

    param: str
    old: Any | None
    new: Any | None
