"""Result dataclasses for validation and constraint evaluation (API.md, "IR").

`ConstraintEval`, `ValidationResult` and `ParamError` report validation.
`PartialEval` and the `RemainingDomain` descriptor family report a partial
config. `ParamDiff` reports a config diff and `SubspaceInfo` a subspace.
`ConstraintReport` and `SamplingReport` carry sampling diagnostics, and
`RepresentationCheck` and `RepresentationCheckFailure` carry
`Representation.check()`'s findings.

There is no capability report. `rep.target` is an ordinary `Space`, so
solver negotiation is ordinary introspection and a dedicated report would
have nothing to say.
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
    """One constraint evaluated against one configuration.

    Read `violated` rather than `satisfied` unless you mean to handle
    polarity yourself: a `forbid` names a bad state, so satisfying it is
    the unhealthy outcome.

    Attributes
    ----------
    constraint : Constraint
        The constraint evaluated. For a per-element constraint inside a
        `.repeat()`, the template rather than a per-instance copy.
    instance_path : str | None
        Which element this evaluation is for, when the constraint lives
        inside a lift; `None` otherwise.
    applicable : bool
        Whether the constraint could be decided at all. `False` when a
        parameter it reads is inactive, in which case it neither holds nor
        fails, since an inapplicable constraint is never violated.
    satisfied : bool | None
        Whether the stored predicate held. `None` when the outcome is
        unknown, which is also when `applicable` is `False`.
    margin : float | None
        How far the configuration sits from the constraint boundary, signed
        so that a positive value means the stored predicate holds. `None`
        for a predicate with no numeric distance, such as a Boolean composition
        or an opaque `ds.value(..., returns=bool)`.
    """

    constraint: Constraint
    instance_path: str | None
    applicable: bool
    satisfied: bool | None
    margin: float | None

    @property
    def violated(self) -> bool:
        """Whether this evaluation counts against feasibility (for a hard
        forbid/require) or is flagged as a violation (for a soft
        encourage/discourage). It is **polarity-correct across all four kinds**.
        An inapplicable (Kleene-Unknown) eval is never violated (rule 4);
        otherwise the stored predicate is violated when ``satisfied`` differs
        from the constraint's desired polarity. This is the public,
        display-ready reading the reference sampler and ``validate`` use
        internally (``eval.is_violated``); see
        ``Constraint.feasible_when_satisfied``."""
        return self.applicable and self.satisfied is not self.constraint.feasible_when_satisfied


@dataclass(frozen=True)
class ParamError:
    """One parameter's value rejected during validation.

    About the value itself: wrong type, out of domain, present while
    inactive, absent while active. A configuration whose parameters are all
    individually fine may still be infeasible; that shows up in
    `ValidationResult.constraint_evals`, not here.

    Attributes
    ----------
    param : str
        The offending parameter's path.
    reason : str
        A short machine-readable tag, such as `"out_of_bounds"`.
    value : Any | None
        The rejected value, or `None` when the problem is its absence.
    """

    param: str
    reason: str
    value: Any | None


@dataclass(frozen=True)
class ValidationResult:
    """What `Space.validate()` found.

    Separates the two things that can be wrong with a configuration:
    whether each value is legal for its own parameter, and whether the
    constraints hold across them.

    Attributes
    ----------
    valid : bool
        Whether the configuration is both well-formed and feasible.
    param_errors : tuple[ParamError, ...]
        Per-parameter problems. Empty for a well-formed configuration,
        even one that is infeasible.
    constraint_evals : tuple[ConstraintEval, ...]
        Every constraint evaluated, soft ones included.
    """

    valid: bool
    param_errors: tuple[ParamError, ...]
    constraint_evals: tuple[ConstraintEval, ...]


@dataclass(frozen=True)
class PartialEval:
    """What `Space.evaluate_partial()` found: the state of a partial configuration.

    Attributes
    ----------
    param_status : MappingProxyType[str, str]
        Per parameter, one of `"set"`, `"active_unset"`, `"inactive"`, or
        `"unknown"` when activity cannot be decided yet. Keyed by
        definition path and, once a lift's count is known, by instance path
        as well.
    evaluable_constraints : tuple[ConstraintEval, ...]
        Constraints that could already be decided from what is set.
    pending_constraints : tuple[Constraint, ...]
        Constraints still waiting on unset values.
    n_remaining : int
        How many active parameters are still unset.
    """

    param_status: MappingProxyType[str, str]
    evaluable_constraints: tuple[ConstraintEval, ...]
    pending_constraints: tuple[Constraint, ...]
    n_remaining: int


# -- `remaining_domain`'s per-kind descriptor (API.md, "IR"), a closed
# union. It is sound rather than complete: it never excludes a still-feasible
# value, and may admit values an unreduced multi-operand coupling forbids.


@dataclass(frozen=True)
class RealRemaining:
    """What a real parameter may still take, given a partial configuration.

    Attributes
    ----------
    lo : float
        Lower bound of the remaining interval.
    hi : float
        Upper bound of the remaining interval.
    lo_inclusive : bool
        Whether `lo` itself is still allowed. A strict `<` constraint
        leaves it excluded.
    hi_inclusive : bool
        Whether `hi` itself is still allowed.
    grid : QuantizedSpec | None
        The grid, if the parameter is quantized.
    """

    lo: float
    hi: float
    lo_inclusive: bool
    hi_inclusive: bool
    grid: QuantizedSpec | None


@dataclass(frozen=True)
class IntegerRemaining:
    """What an integer parameter may still take, given a partial configuration.

    Attributes
    ----------
    lo : int
        Lowest value still allowed, inclusive.
    hi : int
        Highest value still allowed, inclusive.
    grid : QuantizedSpec | None
        The grid, if the parameter is quantized.
    """

    lo: int
    hi: int
    grid: QuantizedSpec | None


@dataclass(frozen=True)
class ValueRemaining:
    """What a bool, categorical, ordinal, or choice parameter may still take.

    Attributes
    ----------
    values : tuple[Any, ...]
        The values still allowed. For a choice, these are the variant names.
    """

    values: tuple[Any, ...]


@dataclass(frozen=True)
class SubsetRemaining:
    """What a subset parameter may still select, given a partial configuration.

    Attributes
    ----------
    forced_in : tuple[Any, ...]
        Items that must be selected.
    forced_out : tuple[Any, ...]
        Items that must not be selected.
    free : tuple[Any, ...]
        Items still undecided.
    min_size : int
        Smallest selection still allowed.
    max_size : int
        Largest selection still allowed.
    """

    forced_in: tuple[Any, ...]
    forced_out: tuple[Any, ...]
    free: tuple[Any, ...]
    min_size: int
    max_size: int


@dataclass(frozen=True)
class PermutationRemaining:
    """What a permutation parameter may still order.

    Always echoes the declared items: narrowing a permutation would need
    reasoning beyond the one-unset-operand guarantee, so none is attempted.

    Attributes
    ----------
    items : tuple[Any, ...]
        The declared items.
    """

    items: tuple[Any, ...]


RemainingDomain = (
    RealRemaining | IntegerRemaining | ValueRemaining | SubsetRemaining | PermutationRemaining
)
"""What a parameter may still take, given a partial configuration.

The return type of `Space.remaining_domain()`: one descriptor per kind of
parameter. Narrowing is **sound but not complete**: a value it admits may
still turn out infeasible, but a value it excludes is genuinely impossible.
"""


@dataclass(frozen=True)
class ParamDiff:
    """One difference between two configurations, from `ds.config_diff()`.

    Attributes
    ----------
    param : str
        The path that differs.
    old : Any | None
        Its value in the first configuration, or `None` if absent there.
    new : Any | None
        Its value in the second, or `None` if absent there.
    """

    param: str
    old: Any | None
    new: Any | None


@dataclass(frozen=True)
class SubspaceInfo:
    """One nested region of a space, from `Space.subspaces`.

    A struct, or a choice variant that carries parameters. Either way its
    members live under a shared path prefix and share one activation
    condition.

    Attributes
    ----------
    prefix : str
        The path prefix its members share, such as `"opt.sgd."`.
    kind : str
        `"struct"` or `"variant"`.
    member_paths : tuple[str, ...]
        The parameters inside it.
    condition : BoolExpr | None
        When the whole subspace is active, as one expression. For a
        variant this includes the discriminator equality; `None` means
        unconditionally active.
    variant_name : str | None
        The variant's name, for `kind == "variant"`; otherwise `None`.
    """

    prefix: str
    kind: str  # "struct" | "variant"
    member_paths: tuple[str, ...]
    condition: BoolExpr | None
    variant_name: str | None = None  # set only for kind == "variant"


@dataclass(frozen=True)
class ConstraintReport:
    """One `SamplingReport.constraints` row.

    `constraint` is the declared `Constraint`. For a per-element template
    (`ListDomain.element_constraints`), the template itself, never an
    instantiated per-instance copy.

    `applicable` and `satisfied` are fractions of all `n` draws. A
    per-element constraint folds its per-draw instance evaluations into one
    applicable and satisfied decision per draw before dividing by `n`, so
    every row shares one denominator and stays comparable to
    `acceptance_rate`. `satisfied` is conditioned on
    `applicable` (fraction of *applicable* draws satisfied), and is `0.0`
    by convention, never `NaN`, when `applicable == 0.0`.

    Attributes
    ----------
    constraint : Constraint
        The declared constraint this row reports on.
    applicable : float
        Fraction of draws in which the constraint could be decided at all.
        A low value is the "rarely relevant" pathology: the constraint is
        governing almost nothing.
    satisfied : float
        Fraction of *applicable* draws in which the stored predicate held.
        Raw, so its healthy direction depends on the verb; read
        `violation_rate` instead.
    """

    constraint: Constraint
    applicable: float
    satisfied: float

    @property
    def violation_rate(self) -> float:
        """The polarity-resolved fraction of applicable draws in the *bad*
        state, the aggregate analog of `ConstraintEval.violated`. `satisfied`
        alone is raw: a forbid/discourage names a bad state (`satisfied` *is*
        the violation fraction), a require/encourage/bound a good one
        (violation is the complement, `1 - satisfied`). Reading a mixed
        table of rows by `satisfied` alone means re-deriving this flip by
        hand per verb, exactly the confusion `ConstraintEval.violated`
        already exists to avoid for a single evaluation.

        `0.0` when `applicable == 0.0`, for both polarities, mirroring
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
    """What `Space.sampling_report(n, seed, tighten_bounds)` returns.

    Aggregation only, over the **unconditioned** measure,
    drawn before rejection, so both Unknown-swallowing and funnel bias are
    visible. `activity` keys are exactly `set(space.params)`, including
    `"[]"`-templated definition paths from inside a lifted struct or
    choice, folded per draw as `constraints` is.

    Attributes
    ----------
    n : int
        How many draws the report is based on.
    acceptance_rate : float
        Fraction of draws that would survive rejection. A low value means
        sampling is working hard and the accepted configurations are a
        heavily distorted slice of the measure you declared.
    constraints : tuple[ConstraintReport, ...]
        One row per declared constraint.
    activity : MappingProxyType[str, float]
        Per parameter, the fraction of draws in which it was active.
    """

    n: int
    acceptance_rate: float
    constraints: tuple[ConstraintReport, ...]
    activity: MappingProxyType[str, float]


@dataclass(frozen=True)
class RepresentationCheckFailure:
    """One law `Representation.check()` found violated.

    Deduplicated by law and detail across the sampled draws, so this is a count of
    how many draws exhibited the problem, not one row per draw.

    Attributes
    ----------
    law : str
        Short name of the violated law, such as `"decode_totality"` or
        `"feasibility_agreement"`.
    detail : str
        A representative message naming the offending path or value.
    count : int
        How many of the sampled draws exhibited it.
    """

    law: str  # short law name, e.g. "decode_totality" | "feasibility_agreement"
    detail: str  # a representative message naming the offending path/value
    count: int  # how many of the n draws exhibited this failure


@dataclass(frozen=True)
class RepresentationCheck:
    """What `Representation.check()` found: a report, never an exception.

    Attributes
    ----------
    n : int
        How many draws the check was based on.
    ok : bool
        Whether every law held. `True` exactly when `failures` is empty.
    failures : tuple[RepresentationCheckFailure, ...]
        The violations found, one entry per distinct law and detail.
    """

    n: int
    ok: bool
    failures: tuple[RepresentationCheckFailure, ...]
