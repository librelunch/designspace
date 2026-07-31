"""Expression bounds are sugar (API.md, "Constraints and Feasibility" >
"Expression bounds are sugar"; resolution step 6).

`ds.param("x").integer(1, ds.param("y"))` desugars to `ds.param("x").integer(1,
env_hi)` plus the implicit hard constraint `ds.param("x") <= ds.param("y")`.
`env_hi` is the interval-arithmetic **hull** of the bound expression, computed
over the referenced params' own (already-enveloped) domains along the
dependency DAG — not the expression's value for any one config, since charts
are static and built once, independent of any assignment (API.md, "All
charts are static").

**Which side of the hull.** A hi-bound expression's envelope is the hull's
*supremum* — the widest value the expression could ever take, since `x` must
be able to reach that value for *some* legal assignment of its dependencies,
and the generated `x <= expr` constraint is what narrows the domain back down
per-config. Symmetrically, a lo-bound expression's envelope is the hull's
*infimum*. This is a genuine spec-silent design choice — see DECISIONS.md D-29.

**Minimal op set.** Only `+`, `-`, and `*` by a literal constant are
interval-computable without a general (and out-of-scope, "no algebraic
expression normalization") symbolic engine. `*` requires one operand to be a
`Literal` node syntactically — not merely a sub-expression that happens to
evaluate to a constant. Anything else (division, power, modulo, two
non-constant operands multiplied, any vector/count/field operator) is row 20:
an uncomputable hull, with the stated workaround being the manual expansion.

**Scope.** Bound expressions are resolved *eagerly*, tolerating no
enclosing-scope up-reference (unlike `.when()` conditions) — a chart must be
built now, in this scope's own `resolve_space` call, and an up-reference
couldn't be resolved until a later finalization pass that runs after charts
already exist. See DECISIONS.md D-29. Bound expressions on a `.repeat()`
element's own domain are not yet supported (D-29) — rejected with a clear
message rather than silently mishandled by the lift machinery, which never
sees this pass at all (only top-level `ParamExpr.domain` is examined below).
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

from designspace.build._paramexpr import ParamExpr
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
    """Params referenced by `d`'s own bound expression(s) — joins the
    condition/repeat-count dependency graph for cycle detection (row 7)."""
    deps: frozenset[str] = frozenset()
    for expr in bound_exprs(d):
        deps = deps | expr.params
    return deps


def check_bound_refs(defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]) -> None:
    """Row 6 (undeclared ref) / row 14 (arithmetic on categorical/ordinal,
    ordering on categorical, ordinal-sequence mismatch) over each bound
    expression — the same checks `.when()` conditions get, but eager: a
    bound expression does not tolerate an enclosing-scope up-reference (see
    module docstring / DECISIONS.md D-29)."""
    for d in defs:
        for expr in bound_exprs(d):
            context = f"param {d.path!r} bound"
            check_refs_declared(expr, defs_by_path, context=context)
            check_expr_types(expr, defs_by_path, context=context)


def _require_numeric_literal(node: Literal, path: str) -> float:
    value = node.value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ResolutionError(
            f"param {path!r}: bound expression literal {value!r} is not numeric "
            "— no computable interval hull (row 20)"
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
        f"param {path!r}: bound expression multiplies two non-constant operands "
        "— interval multiplication is only computable by a literal constant "
        "(row 20); write the desugared literal bound and an explicit .forbid() "
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
        f"(unsupported {expr.kind!r} — only +, -, and * by a literal constant "
        "over enveloped params are supported); write the desugared literal "
        "bound and an explicit .forbid() constraint by hand (row 20)"
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
    """Resolution step 6: replace every expression bound with its
    interval-arithmetic envelope (a plain number), collecting the
    bound-origin `Constraint` each expression bound sugars for. Must run
    after `check_bound_refs` (row 6/14) and after cycle detection (row 7)
    has confirmed the bound-dependency graph is acyclic — `envelope_of`
    below is a memoized recursion that assumes no cycle, not a fresh check.
    """
    envelopes: dict[str, Interval] = {}

    def envelope_of(path: str) -> Interval:
        if path in envelopes:
            return envelopes[path]
        d = defs_by_path.get(path)
        if d is None or not isinstance(d.domain, _NumericDomain):
            raise ResolutionError(
                f"bound expression references {path!r}, which is not a real or "
                "integer param — no computable interval hull (row 20); write "
                "the desugared literal bound and an explicit .forbid() "
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
    space: Any,  # designspace.build._space.Space; Any avoids an import cycle
) -> dict[str, tuple[ArithExpr | None, ArithExpr | None]]:
    """path -> (lo_expr, hi_expr) recovered from `space.constraints`'
    bound-origin entries. `origin` is derived provenance (API.md, "IR") —
    this reconstructs the dependency/tightening information from it rather
    than a dedicated IR field, relying on `_bound_constraint`'s invariant
    that the target param is always the `Compare`'s *left* operand.

    Shared by `eval/_kleene.py::topological_order` (dependency ordering) and
    `sample/_sample.py` (tighten-not-reject).

    A `represent()` target can break that invariant on purpose: transport
    (M11) rewrites a bound-origin constraint's operands like any other
    (leaf substitution wraps a chart-bearing target in `ChartApply`, or —
    rarer — the whole comparison goes opaque, a `Value` node). Either way
    the constraint still enforces the bound correctly through ordinary
    rejection sampling; only the tighten-not-reject *optimization* and the
    dependency-ordering hint this function feeds are unavailable for that
    target, so such an entry is skipped rather than asserted against.
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
