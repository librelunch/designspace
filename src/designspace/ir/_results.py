"""Result dataclasses for validation and constraint evaluation (API.md, "IR").

M2 needs (`ConstraintEval`, `ValidationResult`, `ParamError`); M6 adds
`PartialEval` and the `RemainingDomain` descriptor family; M7 adds
`ParamDiff`; M8 adds `SubspaceInfo`; M10.6 adds `ConstraintReport`/
`SamplingReport` (API.md, "Sampling diagnostics"); M11 adds
`RepresentationCheck`/`RepresentationCheckFailure` (`Representation.check()`
— API.md, "The Representation Layer"). `capability_report()`/`Capabilities`,
once slated for this layer, were removed outright before M11 opened
(DECISIONS.md D-57, folded into API.md's "Staging" section): `rep.target`
is an ordinary `Space`, so solver negotiation is ordinary introspection —
there is nothing left for a dedicated report to say.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from designspace.expr import BoolExpr
from designspace.ir._domain import QuantizedSpec
from designspace.ir._param import Constraint


@dataclass(frozen=True)
class ConstraintEval:
    constraint: Constraint
    instance_path: str | None
    applicable: bool
    satisfied: bool | None
    margin: float | None

    @property
    def violated(self) -> bool:
        """Whether this evaluation counts against feasibility (for a hard
        forbid/require) or is flagged as a violation (for a soft
        encourage/discourage) — **polarity-correct across all four kinds**.
        An inapplicable (Kleene-Unknown) eval is never violated (rule 4);
        otherwise the stored predicate is violated when ``satisfied`` differs
        from the constraint's desired polarity. This is the public,
        display-ready reading the reference sampler and ``validate`` use
        internally (``eval.is_violated``); see
        ``Constraint.feasible_when_satisfied``."""
        return self.applicable and self.satisfied is not self.constraint.feasible_when_satisfied


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
    """`.evaluate_partial(config)` (API.md, "Space — Partial Configs").

    `param_status` is keyed by definition *and* instance path (a lift's
    instances only appear once its count is determined — see
    `partial/_partial.py`).
    """

    param_status: MappingProxyType[str, str]
    evaluable_constraints: tuple[ConstraintEval, ...]
    pending_constraints: tuple[Constraint, ...]
    n_remaining: int


# -- `remaining_domain`'s per-kind descriptor (API.md, "IR") — a closed
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
    """No per-item reduction under the guarantee (API.md, "IR") — always
    echoes the declared items."""

    items: tuple[Any, ...]


RemainingDomain = (
    RealRemaining | IntegerRemaining | ValueRemaining | SubsetRemaining | PermutationRemaining
)


@dataclass(frozen=True)
class ParamDiff:
    """`ds.config_diff(a, b, space)` entry (API.md, "Config Utilities")."""

    param: str
    old: Any | None
    new: Any | None


@dataclass(frozen=True)
class SubspaceInfo:
    """One entry of `Space.subspaces` (API.md, "Space — Introspection":
    "struct and variant subspaces by prefix"; DECISIONS.md D-43 — the shape
    is not otherwise specified). A struct param (`.space(...)`) or a
    choice's payload-bearing variant, each relocates its descendants under
    a definition-path prefix (`ops/_introspect.py::subspaces` builds one
    entry per relocation site, keyed by that same `prefix`).

    `condition` is the *folded* activation condition gating every member —
    for a struct, its own `.when()` (if any); for a variant, that ANDed
    with the discriminator equality (`choice_path == variant`) — the same
    expression `resolve/_relocate.py::relocate_child` folds into each
    descendant's own condition, reconstructed here as a single value
    describing the subspace as a whole rather than repeated per member.
    """

    prefix: str
    kind: str  # "struct" | "variant"
    member_paths: tuple[str, ...]
    condition: BoolExpr | None
    variant_name: str | None = None  # set only for kind == "variant"


@dataclass(frozen=True)
class ConstraintReport:
    """One `SamplingReport.constraints` row (API.md, "Sampling diagnostics").

    `constraint` is the declared `Constraint` — for a per-element template
    (`ListDomain.element_constraints`), the template itself, never an
    instantiated per-instance copy. `applicable`/`satisfied` are fractions
    of all `n` draws (D-73): a per-element constraint folds its k
    per-draw instance evals into one applicable/satisfied decision per
    draw before dividing by `n`, so every row shares one denominator and
    stays comparable to `acceptance_rate`. `satisfied` is conditioned on
    `applicable` (fraction of *applicable* draws satisfied), and is `0.0`
    by convention — never `NaN` — when `applicable == 0.0`.
    """

    constraint: Constraint
    applicable: float
    satisfied: float

    @property
    def violation_rate(self) -> float:
        """The polarity-resolved fraction of applicable draws in the *bad*
        state — the aggregate analog of `ConstraintEval.violated`. `satisfied`
        alone is raw: a forbid/discourage names a bad state (`satisfied` *is*
        the violation fraction), a require/encourage/bound a good one
        (violation is the complement, `1 - satisfied`) — reading a mixed
        table of rows by `satisfied` alone means re-deriving this flip by
        hand per verb, exactly the confusion `ConstraintEval.violated`
        already exists to avoid for a single evaluation.

        `0.0` when `applicable == 0.0`, for both polarities — mirroring
        `ConstraintEval.violated`'s "inapplicable is never violated" (Kleene
        rule 4) and `satisfied`'s own "`0.0` by convention, never `NaN`"
        default, rather than computed mechanically as `1 - satisfied`, which
        would report a never-evaluated require/encourage row as "always
        violated" instead of "carries no information."
        """
        if self.applicable == 0.0:
            return 0.0
        if self.constraint.feasible_when_satisfied:
            return 1.0 - self.satisfied
        return self.satisfied


@dataclass(frozen=True)
class SamplingReport:
    """`.sampling_report(n, seed, tighten_bounds)` (API.md, "Sampling
    diagnostics"). Aggregation only, over the **unconditioned** measure —
    drawn before rejection, so both Unknown-swallowing and funnel bias are
    visible. `activity` keys are exactly `set(space.params)`, including
    `"[]"`-templated definition paths from inside a lifted struct/choice,
    folded per draw the same way as `constraints` (D-73)."""

    n: int
    acceptance_rate: float
    constraints: tuple[ConstraintReport, ...]
    activity: MappingProxyType[str, float]


@dataclass(frozen=True)
class RepresentationCheckFailure:
    """One law violation `Representation.check()` recorded, deduped by
    `(law, detail)` across the `n` sampled draws — a count of how many
    draws exhibited it, not one row per draw. `check()` is a diagnostic
    tool for a supplied morphism's author (API.md, "The Representation
    Layer": "the suite as a tool, since a supplied morphism has no other
    way to be shown sound"), not a per-draw audit trail."""

    law: str  # short law name, e.g. "decode_totality" | "feasibility_agreement"
    detail: str  # a representative message naming the offending path/value
    count: int  # how many of the n draws exhibited this failure


@dataclass(frozen=True)
class RepresentationCheck:
    """`rep.check(n=200, seed=None)` (API.md, "The Representation Layer";
    DECISIONS.md — `check()`'s report shape is an implementation choice the
    spec leaves open). Never raises on a law violation: mirrors
    `ValidationResult`/`SamplingReport`/`PartialEval` — a report, not an
    exception, matching every other diagnostic surface this library
    returns. `ok` is `True` iff `failures` is empty."""

    n: int
    ok: bool
    failures: tuple[RepresentationCheckFailure, ...]
