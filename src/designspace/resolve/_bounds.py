"""Expression bounds are sugar (API.md, "Constraints and Feasibility" >
"Expression bounds are sugar"; resolution step 6).

`ds.param("x").integer(1, ds.param("y"))` desugars to
`ds.param("x").integer(1, env_hi)` plus the implicit hard constraint
`ds.param("x") <= ds.param("y")`. `env_hi` is the interval-arithmetic hull of
the bound expression, computed over the referenced params' own already
enveloped domains along the dependency DAG. It is not the expression's value
for any one config, because charts are static and built once, independent of
any assignment (API.md, "All charts are static").

**Which side of the hull.** A hi-bound expression's envelope is the hull's
supremum, the widest value the expression could ever take, since `x` must be
able to reach that value under some legal assignment of its dependencies. The
generated `x <= expr` constraint is what narrows the domain back down per
config. A lo-bound expression's envelope is the hull's infimum,
symmetrically.

**Minimal op set.** Only `+`, `-`, and `*` by a literal constant are
interval-computable without a general symbolic engine, which the spec's
out-of-scope list rules out under "no algebraic expression normalization".
`*` requires one operand to be a `Literal` node syntactically, not merely a
sub-expression that happens to evaluate to a constant. Everything else is row
20, an uncomputable hull: division, power, modulo, two non-constant operands
multiplied, and any vector, count or field operator. The stated workaround is
to expand the bound manually.

**Scope.** Bound expressions resolve eagerly and tolerate no enclosing-scope
up-reference, unlike a `.when()` condition. A chart must be built now, in
this scope's own `resolve_space` call, and an up-reference could not be
resolved until a finalization pass that runs after charts already exist.
Bound expressions on a `.repeat()` element's own domain are unsupported, and
are rejected with a message saying so rather than left to the lift
machinery, which never reaches this pass: only a top-level
`ParamExpr.domain` is examined below.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from designspace.builder._paramexpr import ParamExpr
from designspace.errors import ResolutionError
from designspace.expr import ArithExpr, ArithOp, Compare, Literal
from designspace.ir import Constraint, IntegerDomain, RealDomain
from designspace.resolve._expr_checks import check_expr_types, check_refs_declared

if TYPE_CHECKING:
    from collections.abc import Callable

_NumericDomain = RealDomain | IntegerDomain
Interval = tuple[float, float]


def bound_exprs(d: ParamExpr) -> tuple[ArithExpr, ...]:
    """The lo/hi bound operands that are expressions, for `d`'s own
    (non-lifted) real/integer domain. Empty for every other param."""
    domain = d.domain
    if not isinstance(domain, _NumericDomain):
        return ()
    return tuple(b for b in (domain.lo, domain.hi) if isinstance(b, ArithExpr))


def bound_deps(d: ParamExpr) -> frozenset[str]:
    """Params referenced by `d`'s own bound expressions.

    These join the condition and repeat-count dependency graph, so that
    cycle detection covers them (row 7).
    """
    deps: frozenset[str] = frozenset()
    for expr in bound_exprs(d):
        deps = deps | expr.params
    return deps


def check_bound_refs(defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]) -> None:
    """Check each bound expression for row 6 and row 14 violations.

    Row 6 is an undeclared reference. Row 14 covers arithmetic on a
    categorical or ordinal, ordering on a categorical, and an
    ordinal-sequence mismatch. These are the checks a `.when()` condition
    gets, applied eagerly: a bound expression tolerates no enclosing-scope
    up-reference, as the module docstring states.
    """
    for d in defs:
        for expr in bound_exprs(d):
            context = f"param {d.path!r} bound"
            check_refs_declared(expr, defs_by_path, context=context)
            check_expr_types(expr, defs_by_path, context=context)


def _require_numeric_literal(node: Literal, path: str) -> float:
    value = node.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResolutionError(
            f"param {path!r}: bound expression literal {value!r} is not numeric, "
            "so it has no computable interval hull"
        )
    return value


def _scale(c: float, lo: float, hi: float) -> Interval:
    a, b = c * lo, c * hi
    return (a, b) if a <= b else (b, a)


def _hull_mul(
    left: ArithExpr, right: ArithExpr, envelope_of: Callable[[str], Interval], *, path: str
) -> Interval:
    if isinstance(right, Literal):
        c = _require_numeric_literal(right, path)
        lo, hi = hull(left, envelope_of, path=path)
        return _scale(c, lo, hi)
    if isinstance(left, Literal):
        c = _require_numeric_literal(left, path)
        lo, hi = hull(right, envelope_of, path=path)
        return _scale(c, lo, hi)
    raise ResolutionError(
        f"param {path!r}: bound expression multiplies two non-constant operands; "
        "interval multiplication is only computable by a literal constant"
        "; write the desugared literal bound and an explicit .forbid() "
        "constraint by hand"
    )


def hull(expr: ArithExpr, envelope_of: Callable[[str], Interval], *, path: str) -> Interval:
    if isinstance(expr, Literal):
        v = _require_numeric_literal(expr, path)
        return (v, v)
    if isinstance(expr, ParamExpr):
        return envelope_of(expr.path)
    if isinstance(expr, ArithOp):
        if expr.op == "add":
            l_lo, l_hi = hull(expr.left, envelope_of, path=path)
            r_lo, r_hi = hull(expr.right, envelope_of, path=path)
            return (l_lo + r_lo, l_hi + r_hi)
        if expr.op == "sub":
            l_lo, l_hi = hull(expr.left, envelope_of, path=path)
            r_lo, r_hi = hull(expr.right, envelope_of, path=path)
            return (l_lo - r_hi, l_hi - r_lo)
        if expr.op == "mul":
            return _hull_mul(expr.left, expr.right, envelope_of, path=path)
    raise ResolutionError(
        f"param {path!r}: bound expression has no computable interval hull "
        f"(unsupported {expr.kind!r}; only +, -, and * by a literal constant "
        "over enveloped params are supported); write the desugared literal "
        "bound and an explicit .forbid() constraint by hand"
    )


def _bound_constraint(target_path: str, op: str, other: ArithExpr) -> Constraint:
    expr = Compare(op, ParamExpr(path=target_path), other)
    return Constraint(
        expr=expr,
        hard=True,
        origin="bound",
        tags=frozenset(),
        meta=MappingProxyType({}),
        params=expr.params,
    )


def compute_bound_envelopes(
    defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]
) -> tuple[tuple[ParamExpr, ...], list[Constraint]]:
    """Resolution step 6: replace every expression bound with its envelope.

    The envelope is a plain number, the interval-arithmetic hull of the
    bound expression. This also collects the bound-origin `Constraint` that
    each expression bound sugars for.

    Must run after `check_bound_refs` (rows 6 and 14) and after cycle
    detection (row 7) has confirmed the bound-dependency graph is acyclic.
    `envelope_of` below is a memoized recursion that assumes no cycle rather
    than checking for one.
    """
    envelopes: dict[str, Interval] = {}

    def envelope_of(path: str) -> Interval:
        if path in envelopes:
            return envelopes[path]
        d = defs_by_path.get(path)
        if d is None or not isinstance(d.domain, _NumericDomain):
            raise ResolutionError(
                f"bound expression references {path!r}, which is not a real or "
                "integer param, so it has no computable interval hull; "
                "write the desugared literal bound and an explicit .forbid() "
                "constraint by hand"
            )
        lo, hi = d.domain.lo, d.domain.hi
        env_lo = hull(lo, envelope_of, path=path)[0] if isinstance(lo, ArithExpr) else lo
        env_hi = hull(hi, envelope_of, path=path)[1] if isinstance(hi, ArithExpr) else hi
        result = (env_lo, env_hi)
        envelopes[path] = result
        return result

    new_defs: list[ParamExpr] = []
    bound_constraints: list[Constraint] = []
    for d in defs:
        domain = d.domain
        if not isinstance(domain, _NumericDomain):
            new_defs.append(d)
            continue
        lo, hi = domain.lo, domain.hi
        lo_is_expr, hi_is_expr = isinstance(lo, ArithExpr), isinstance(hi, ArithExpr)
        if not lo_is_expr and not hi_is_expr:
            new_defs.append(d)
            continue
        env_lo, env_hi = envelope_of(d.path)
        new_domain: RealDomain | IntegerDomain = (
            RealDomain(env_lo, env_hi)
            if isinstance(domain, RealDomain)
            else IntegerDomain(int(env_lo), int(env_hi))
        )
        new_defs.append(replace(d, domain=new_domain))
        if lo_is_expr:
            bound_constraints.append(_bound_constraint(d.path, "ge", cast(ArithExpr, lo)))
        if hi_is_expr:
            bound_constraints.append(_bound_constraint(d.path, "le", cast(ArithExpr, hi)))
    return tuple(new_defs), bound_constraints


def bound_origin_targets(
    space: Any,  # designspace.builder._space.Space; Any avoids an import cycle
) -> dict[str, tuple[ArithExpr | None, ArithExpr | None]]:
    """Recover `path -> (lo_expr, hi_expr)` from the bound-origin constraints.

    `origin` is derived provenance (API.md, "IR"), so this reconstructs the
    dependency and tightening information from it rather than from a
    dedicated IR field. It relies on `_bound_constraint`'s invariant that
    the target param is the `Compare`'s left operand.

    Shared by `topological_order` in `eval/_kleene.py`, for dependency
    ordering, and by `sample/_sample.py`, for tighten-not-reject.

    A `represent()` target can break that invariant deliberately: transport
    rewrites a bound-origin constraint's operands like any other, wrapping a
    chart-bearing target in `ChartApply` or, more rarely, taking the whole
    comparison opaque as a `Value` node. The constraint still enforces the
    bound correctly through ordinary rejection sampling. Only the
    tighten-not-reject optimization and the dependency-ordering hint this
    function feeds are unavailable for such a target, so the entry is
    skipped rather than asserted against.
    """
    result: dict[str, tuple[ArithExpr | None, ArithExpr | None]] = {}
    for c in space.constraints:
        if c.origin != "bound":
            continue
        expr = c.expr
        if not isinstance(expr, Compare) or not isinstance(expr.left, ParamExpr):
            continue
        target = expr.left
        lo_expr, hi_expr = result.get(target.path, (None, None))
        if expr.op == "ge":
            lo_expr = expr.right
        else:
            assert expr.op == "le"
            hi_expr = expr.right
        result[target.path] = (lo_expr, hi_expr)
    return result
