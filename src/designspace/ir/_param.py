"""ParamDef and the condition/constraint IR (API.md, "IR")."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from designspace.display._hooks import displayable
from designspace.expr import BoolExpr
from designspace.ir._chart import Chart
from designspace.ir._domain import Domain, QuantizedSpec, TypeKind
from designspace.ir._priors import PriorSpec

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


@displayable("designspace.display._space.render_param_def")
@dataclass(frozen=True)
class ParamDef:
    """One resolved parameter: the introspection surface.

    What `Space.params[path]` holds, and what a solver reads to decide how
    to treat a parameter. Unlike the builder objects, which carry
    half-finished state, a `ParamDef` is complete and checked.

    The IR is bidirectional: `ds.param_from_def()` turns one back into a
    builder, and `ds.space_from_ir()` rebuilds a whole space from these,
    which is what makes programmatic space construction ordinary rather
    than special.

    Attributes
    ----------
    path : str
        The parameter's full path, such as `"opt.sgd.momentum"`.
    type_kind : str
        The kind, as a string: `"real"`, `"integer"`, `"bool"`,
        `"categorical"`, `"ordinal"`, `"subset"`, `"permutation"`,
        `"choice"`, `"space"`, `"list"`, `"custom"`, `"symbolic"`,
        `"code"`.
    domain : Domain
        The declared value space.
    prior : PriorSpec | None
        The declared prior, or `None` for the default uniform measure.
    periodic : bool
        Whether the domain wraps, so its endpoints are the same point.
    default : Any
        The fill value used by `apply_defaults`, or `None` if unset.
    condition : BoolExpr | None
        When the parameter is active. `None` means unconditionally active.
    tags : frozenset[str]
        Labels attached by `.tag()`.
    meta : MappingProxyType[str, Any]
        Metadata attached by `.meta()`. Never interpreted.
    chart : Chart | None
        The map from `[0, 1]` onto the domain, for a generative scalar.
        `None` for a non-generative parameter and for a lift, since a lifted
        parameter's chart is on `ListDomain.element_chart`.
    quantized : QuantizedSpec | None
        The grid, if the parameter is quantized.

    Examples
    --------
    >>> s = ds.space(ds.param("depth").integer(1, 8))
    >>> pd = s.params["depth"]
    >>> pd.path, pd.type_kind
    ('depth', 'integer')
    >>> pd.domain
    IntegerDomain(lo=1, hi=8)
    """

    path: str
    type_kind: TypeKind
    domain: Domain
    prior: PriorSpec | None
    periodic: bool
    default: Any
    condition: BoolExpr | None
    tags: frozenset[str]
    meta: MappingProxyType[str, Any]
    chart: Chart | None = None
    quantized: QuantizedSpec | None = None


@displayable("designspace.display._space.render_condition")
@dataclass(frozen=True)
class Condition:
    """When one parameter is active, as resolved IR.

    Produced by `.when()`, and injected automatically by struct and choice
    nesting: a variant's payload parameters each get a condition on the
    discriminator. A parameter with no condition is unconditionally active.

    Attributes
    ----------
    target : str
        The parameter this condition governs.
    expr : BoolExpr
        The predicate. The target is active exactly when it holds.
    params : frozenset[str]
        Every parameter path `expr` reads. These must be assigned before
        the target's activity can be decided, which is what puts the
        condition in the dependency graph.
    """

    target: str
    expr: BoolExpr
    params: frozenset[str]


@displayable("designspace.display._space.render_constraint")
@dataclass(frozen=True)
class Constraint:
    """A restriction on which configurations are valid, as resolved IR.

    All four constraint verbs and the `bound` sugar produce one of these;
    read `kind` to tell them apart, and `feasible_when_satisfied` rather
    than reasoning about `hard` and `origin` yourself.

    Attributes
    ----------
    expr : BoolExpr
        The stored predicate. Note that this is the predicate *as written*:
        for a `forbid` it names the bad state, so satisfying it is not the
        same as being feasible. `feasible_when_satisfied` resolves it.
    hard : bool
        Whether violating it makes a configuration infeasible. `False` for
        `encourage` and `discourage`, which annotate without restricting.
    origin : str
        Provenance: `"user"`, `"bound"`, `"require"`, or `"discourage"`.
        An implementation detail of how the constraint was spelled, and
        deliberately excluded from the fingerprint, so prefer `kind`.
    tags : frozenset[str]
        Labels, used by `Space.without_constraints()`.
    meta : MappingProxyType[str, Any]
        Metadata. Never interpreted.
    params : frozenset[str]
        Every parameter path `expr` reads. This is what
        `Space.param_constraints()` matches on, and what puts the
        constraint in the dependency graph.
    """

    expr: BoolExpr
    hard: bool
    # "user" | "bound" | "require" | "discourage": derived provenance,
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
        consumers never re-derive polarity by hand."""
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
        bad outcome). ``False`` only for ``forbid``/``discourage``, the two
        verbs that name a bad state. This is the single source of truth for
        "is this constraint supposed to hold?"; ``ConstraintEval.violated``
        reads it, so forbid/require/encourage/discourage all report
        consistently."""
        return self.kind not in ("forbid", "discourage")
