"""Expression transport (API.md, "The Representation Layer" > "Transport";
DECISIONS.md D-54).

Conditions and constraints are rewritten, never dropped — three mechanisms,
preferred in order: leaf substitution (`decode_expr`), node rewriting
(`rewrite`), opaque (a `ds.value` core synthesizes itself from `decode` and
the source AST, since core always knows both). Because nothing is dropped,
target activity always matches source activity, and feasibility agreement
holds by construction; what differs is *quality*, reported via
`opaque_conditions`/`opaque_constraints`.

Two implementation facts this file exists to get right (D-54). Expressions
live in **four** stores — `Space.conditions`, each `ParamDef.condition`,
`Space.constraints`, and `ListDomain.element_constraints` — not two; a
struct lift's own `.forbid(...)` puts a constraint on the *lift's* element
template, whose owning param is itself never encodable, but whose
constraint may still reference encoded descendant fields. And
`Expr.params` **cannot drive the walk**: for `boxes.field("w").sum()` it
reports `{"boxes"}`, never `"boxes[].w"`, so a `.params`-keyed walk passes
a reference straight through unrewritten — `_vector_base` (mirrored here
as `_governing_path`) resolves the projection correctly and must be used.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.errors import ResolutionError
from designspace.expr import (
    ArithExpr,
    ArithOp,
    BoolExpr,
    BoolLiteral,
    BoolOp,
    ChartApply,
    Compare,
    Contains,
    Count,
    CountOf,
    Distinct,
    Expr,
    Field,
    IfInactive,
    Implies,
    IsActive,
    IsIn,
    IsSorted,
    Length,
    Literal,
    Max,
    Min,
    Not,
    PositionOf,
    Prop,
    Size,
    Sum,
    SumOver,
    Value,
)
from designspace.expr import value as ds_value
from designspace.ir import Condition, Constraint, ListDomain, ParamDef
from designspace.ops._structural import _governing_definition_path
from designspace.ops._structural import substitute_expr as _substitute_expr
from designspace.represent._protocol import Encoding, has_decode_expr, has_rewrite
from designspace.resolve._expr_checks import iter_nodes

_VECTOR_AGGREGATES = (Sum, Min, Max, CountOf, IsSorted, Distinct)


class NeedsOpaque(Exception):  # internal control-flow signal, never a real error
    """Raised (and always caught within this module) when a reference
    inside the expression being transported has no structural path — no
    `rewrite` fired for its containing node, and its encoding supplies no
    `decode_expr`."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


# -- governing-path resolution (D-54: `.params` cannot drive this walk) -----


def _governing_path(node: Expr, space: Space) -> str | None:
    """The `space.params` key a bare reference or `.field()` projection
    reads, or `None` if `node` is not a reference site. Mirrors
    `resolve/_expr_checks.py::_vector_base` plus `_check_field_declared`'s
    own field-path construction — `.field()` is never chained (only a
    lift's own bare base takes it), so `node.operand` is always a plain
    `ParamExpr` here."""
    if isinstance(node, ParamExpr):
        return _governing_definition_path(space, node.path)
    if isinstance(node, Field) and isinstance(node.operand, ParamExpr):
        return f"{node.operand.path}[].{node.name}"
    return None


def _governing_paths_in_subtree(node: Expr, space: Space) -> frozenset[str]:
    direct = _governing_path(node, space)
    if direct is not None:
        return frozenset({direct})
    result: frozenset[str] = frozenset()
    for child in node.children:
        result = result | _governing_paths_in_subtree(child, space)
    return result


# -- structural rewriting: rewrite() first, then decode_expr() leaf subst. --


def _decode_expr_template(
    encoding: Encoding, param: ParamDef, path: str, cache: dict[str, Expr | None]
) -> Expr | None:
    """`decode_expr(param)` is a pure function of `param` alone — cached
    per governing path so it runs once per param, not once per occurrence
    of a reference to it."""
    if path in cache:
        return cache[path]
    template: Expr | None = None
    if has_decode_expr(encoding):
        # `decode_expr` is an optional capability (hasattr-checked, never
        # part of `Encoding`'s static Protocol shape -- the same convention
        # `custom/_protocol.py`'s `sample`/`cardinality`/`extract` already
        # use), so it is reached via `getattr` rather than a direct
        # attribute access mypy --strict would reject.
        candidate = getattr(encoding, "decode_expr")(param)  # noqa: B009
        if candidate is not None:
            if not candidate.params <= {path}:
                raise ResolutionError(
                    f"represent(): Encoding.decode_expr() for {path!r} references "
                    f"paths outside its own param (row 31): "
                    f"{sorted(candidate.params - {path})!r}"
                )
            template = candidate
    cache[path] = template
    return template


def rewrite_node(
    node: Expr,
    space: Space,
    matched: Mapping[str, Encoding],
    decode_expr_cache: dict[str, Expr | None],
) -> Expr:
    """Transport one node of a *source* expression tree into its target
    form: node rewriting first (tried at every node containing a reference
    to a matched param whose encoding supplies `rewrite`), then leaf
    substitution (`decode_expr`) when the node itself is a reference site,
    else recurse. Raises `NeedsOpaque` when a reference site's encoding
    supplies neither — caught by the per-expression driver
    (`transport_bool`/`transport_arith`), which falls back to opaque
    transport for the *whole* expression.
    """
    relevant = sorted(_governing_paths_in_subtree(node, space) & matched.keys())
    for path in relevant:
        encoding = matched[path]
        if has_rewrite(encoding):
            rewritten: Expr | None = getattr(encoding, "rewrite")(space.params[path], node)  # noqa: B009
            if rewritten is not None:
                return rewritten
    direct = _governing_path(node, space)
    if direct is not None:
        if direct not in matched:
            return node  # unmatched param -- passes through unchanged
        template = _decode_expr_template(
            matched[direct], space.params[direct], direct, decode_expr_cache
        )
        if template is None:
            raise NeedsOpaque(direct)
        return _substitute_expr(template, {direct: node})
    return _rebuild_children(node, space, matched, decode_expr_cache)


def _rebuild_children(
    node: Expr,
    space: Space,
    matched: Mapping[str, Encoding],
    cache: dict[str, Expr | None],
) -> Expr:
    """Reconstruct `node` with each child transported via `rewrite_node` —
    the same exhaustive per-kind dispatch `resolve/_relocate.py::rewrite_expr`
    and `ops/_structural.py::substitute_expr` already use, parameterized by
    recursive transport instead of a rename or a fixed substitution. A
    source expression never contains a `ChartApply` (that node is only ever
    transport's own *output*), so no branch handles it here.
    """

    def go(child: Expr) -> Expr:
        return rewrite_node(child, space, matched, cache)

    if isinstance(node, Compare):
        return Compare(node.op, cast(ArithExpr, go(node.left)), cast(ArithExpr, go(node.right)))
    if isinstance(node, ArithOp):
        return ArithOp(node.op, cast(ArithExpr, go(node.left)), cast(ArithExpr, go(node.right)))
    if isinstance(node, BoolOp):
        return BoolOp(node.op, cast(BoolExpr, go(node.left)), cast(BoolExpr, go(node.right)))
    if isinstance(node, Not):
        return Not(cast(BoolExpr, go(node.operand)))
    if isinstance(node, Implies):
        return Implies(cast(BoolExpr, go(node.left)), cast(BoolExpr, go(node.right)))
    if isinstance(node, IsIn):
        return IsIn(cast(ArithExpr, go(node.operand)), node.values)
    if isinstance(node, IsActive):
        return IsActive(go(node.operand))
    if isinstance(node, Count):
        return Count(tuple(cast(BoolExpr, go(o)) for o in node.operands))
    if isinstance(node, IfInactive):
        return IfInactive(cast(ArithExpr, go(node.operand)), cast(ArithExpr, go(node.fallback)))
    if isinstance(node, Contains):
        return Contains(cast(ArithExpr, go(node.operand)), node.item)
    if isinstance(node, Size):
        return Size(cast(ArithExpr, go(node.operand)))
    if isinstance(node, SumOver):
        return SumOver(cast(ArithExpr, go(node.operand)), node.mapping)
    if isinstance(node, PositionOf):
        return PositionOf(cast(ArithExpr, go(node.operand)), node.item)
    if isinstance(node, Length):
        return Length(cast(ArithExpr, go(node.operand)))
    if isinstance(node, Prop):
        return Prop(cast(ArithExpr, go(node.operand)), node.name)
    if isinstance(node, Value):
        return Value(node.fn, tuple(go(o) for o in node.operands), node.returns)
    if isinstance(node, Field):
        return Field(go(node.operand), node.name)
    if isinstance(node, Sum):
        return Sum(go(node.operand))
    if isinstance(node, Min):
        return Min(go(node.operand))
    if isinstance(node, Max):
        return Max(go(node.operand))
    if isinstance(node, CountOf):
        return CountOf(go(node.operand), node.values)
    if isinstance(node, IsSorted):
        return IsSorted(go(node.operand), node.descending)
    if isinstance(node, Distinct):
        return Distinct(go(node.operand), node.fields)
    if isinstance(node, ChartApply):
        # The node a representation itself emits (API.md, "Expressions":
        # the second opaque-free leaf). It appears here whenever the source
        # is *already* a representation target — `rep.target` is an ordinary
        # `Space`, so representing it again is supported by construction,
        # and it is what makes `then` usable past one derived level. Only
        # the operand transports: the carried chart declaration describes
        # the *source* param's own chart and is not the thing being
        # re-encoded, exactly as `_relocate.py::rewrite_expr` and
        # `ops/_structural.py::substitute_expr` treat it.
        return ChartApply(
            go(node.operand),
            node.chart,
            node.type_kind,
            node.domain,
            node.prior,
            node.quantized,
            node.periodic,
        )
    if isinstance(node, ParamExpr | Literal | BoolLiteral):
        return node  # reached only when unmatched (handled by rewrite_node above)
    raise TypeError(f"represent(): cannot transport expr kind {node.kind!r}")  # pragma: no cover


# -- opaque transport: core synthesizes a ds.value from decode + the source
# -- AST when no reference site in an expression can be handled structurally.


def _enumerate_instances(path: str, domain: Any, space: Space, counts: dict[str, int]) -> list[str]:
    """Every concrete instance path under `path` (recursively, through
    chained `.repeat()` levels), for a *static* count only — opaque
    transport needs a fixed operand list at resolution time, which a
    dynamic count cannot supply; core's own chart encoding always supplies
    `decode_expr` (never reaching opaque transport at all), so this is
    reachable only through a user-supplied rule missing both `decode_expr`
    and `rewrite` for a dynamic-count lift. `counts` accumulates the static
    length bookkeeping key at *every* level touched (`{"m": 2, "m[0]": 3,
    ...}` for a chained repeat), needed later so nested aggregate
    evaluation (`_gather_instance_paths`) can recover each level's count."""
    if not isinstance(domain, ListDomain):
        return [path]
    count = domain.count
    if not isinstance(count, int) or isinstance(count, bool):
        raise ResolutionError(
            f"represent(): cannot opaquely transport an expression touching "
            f"{path!r}, whose repeat() count is dynamic — opaque transport "
            f"needs a fixed operand list at resolution time; supply an "
            f"Encoding.decode_expr() or .rewrite() for the encoded param(s) "
            f"this expression references instead"
        )
    counts[path] = count
    result: list[str] = []
    for i in range(count):
        result.extend(_enumerate_instances(f"{path}[{i}]", domain.element_domain, space, counts))
    return result


def _leaf_paths_for(
    node: Expr, space: Space, seen: set[str], out: list[str], counts: dict[str, int]
) -> None:
    def add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            out.append(path)

    if isinstance(node, Distinct) and node.fields:
        assert isinstance(node.operand, ParamExpr)
        base_domain = space.params[node.operand.path].domain
        for inst in _enumerate_instances(node.operand.path, base_domain, space, counts):
            for field_name in node.fields:
                add(f"{inst}.{field_name}")
        return
    if isinstance(node, _VECTOR_AGGREGATES):
        base = node.operand
        if isinstance(base, Field) and isinstance(base.operand, ParamExpr):
            base_domain = space.params[base.operand.path].domain
            for inst in _enumerate_instances(base.operand.path, base_domain, space, counts):
                add(f"{inst}.{base.name}")
            return
        assert isinstance(base, ParamExpr)
        for inst in _enumerate_instances(base.path, space.params[base.path].domain, space, counts):
            add(inst)
        return
    if isinstance(node, ParamExpr):
        add(node.path)
        return
    if isinstance(node, Field) and isinstance(node.operand, ParamExpr):
        base_domain = space.params[node.operand.path].domain
        for inst in _enumerate_instances(node.operand.path, base_domain, space, counts):
            add(f"{inst}.{node.name}")
        return
    for child in node.children:
        _leaf_paths_for(child, space, seen, out, counts)


def _opaque_fn(
    source_expr: BoolExpr,
    leaf_paths: list[str],
    count_keys: dict[str, int],
    space: Space,
    matched: Mapping[str, Encoding],
) -> Any:
    from designspace.eval import Unknown, compute_activity, evaluate_bool

    def fn(*values: Any) -> bool:
        config: dict[str, Any] = dict(count_keys)
        for path, raw in zip(leaf_paths, values, strict=True):
            governing = _governing_definition_path(space, path)
            config[path] = (
                matched[governing].decode(space.params[governing], raw)
                if governing in matched
                else raw
            )
        activity = compute_activity(space, config)
        result = evaluate_bool(source_expr, config, activity, space)
        if isinstance(result, Unknown):
            raise ValueError(
                "represent(): opaque transport's reconstructed evaluation was "
                "Unknown — every ds.value operand was active by the calling "
                "convention, so this indicates a source expression this "
                "opaque path does not yet support"
            )
        return bool(result)

    return fn


def _opaque_wrap(expr: BoolExpr, space: Space, matched: Mapping[str, Encoding]) -> BoolExpr:
    leaf_paths: list[str] = []
    count_keys: dict[str, int] = {}
    _leaf_paths_for(expr, space, set(), leaf_paths, count_keys)
    fn = _opaque_fn(expr, leaf_paths, count_keys, space, matched)
    operands = tuple(ParamExpr(path=p) for p in leaf_paths)
    wrapped = ds_value(fn, *operands, returns=bool)
    assert isinstance(wrapped, BoolExpr)
    return wrapped


def transport_bool(
    expr: BoolExpr,
    space: Space,
    matched: Mapping[str, Encoding],
    decode_expr_cache: dict[str, Expr | None],
) -> tuple[BoolExpr, bool]:
    """Transport one `Condition`/`Constraint` expression. Returns
    `(transported_expr, is_opaque)` — `is_opaque` names whether *any*
    reference inside `expr` needed the opaque fallback (a whole-expression
    decision, matching how `opaque_conditions`/`opaque_constraints` report
    at that granularity)."""
    try:
        return cast(BoolExpr, rewrite_node(expr, space, matched, decode_expr_cache)), False
    except NeedsOpaque:
        return _opaque_wrap(expr, space, matched), True


@dataclass(frozen=True)
class TransportResult:
    target_params: dict[str, ParamDef]
    target_conditions: tuple[Condition, ...]
    target_constraints: tuple[Constraint, ...]
    opaque_conditions: tuple[str, ...]
    opaque_constraints: tuple[Constraint, ...]


def _transport_constraint_tuple(
    constraints: tuple[Constraint, ...],
    space: Space,
    matched: Mapping[str, Encoding],
    cache: dict[str, Expr | None],
) -> tuple[tuple[Constraint, ...], list[Constraint]]:
    out: list[Constraint] = []
    opaque: list[Constraint] = []
    for c in constraints:
        rewritten, is_opaque = transport_bool(c.expr, space, matched, cache)
        new_c = replace(c, expr=rewritten, params=rewritten.params)
        out.append(new_c)
        if is_opaque:
            opaque.append(new_c)
    return tuple(out), opaque


def _transport_list_domain(
    domain: ListDomain, space: Space, matched: Mapping[str, Encoding], cache: dict[str, Expr | None]
) -> tuple[ListDomain, list[Constraint]]:
    """Store 4 (`ListDomain.element_constraints`), recursing through a
    chained/nested `.repeat()` chain — each level's own template
    constraints are transported independently of the others'."""
    opaque: list[Constraint] = []
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        inner, inner_opaque = _transport_list_domain(domain.element_domain, space, matched, cache)
        opaque.extend(inner_opaque)
        domain = replace(domain, element_domain=inner)
    new_constraints, level_opaque = _transport_constraint_tuple(
        domain.element_constraints, space, matched, cache
    )
    opaque.extend(level_opaque)
    return replace(domain, element_constraints=new_constraints), opaque


def transport_space(
    source: Space, matched: Mapping[str, Encoding], raw_target_params: Mapping[str, ParamDef]
) -> TransportResult:
    """Rewrites every expression in all four stores (D-54) a source space's
    conditions/constraints inhabit, given `raw_target_params` (the
    structurally-built, not-yet-transported target `ParamDef`s each
    `Encoding.target()` produced). Returns a fully self-consistent bundle:
    `target_conditions` and each rewritten param's own `.condition` field
    carry the identical rewritten expression object for a given path.
    """
    decode_expr_cache: dict[str, Expr | None] = {}
    target_params = dict(raw_target_params)

    # Stores 1+2: Space.conditions and each ParamDef.condition.
    target_conditions: list[Condition] = []
    opaque_condition_names: list[str] = []
    for cond in source.conditions:
        rewritten, is_opaque = transport_bool(cond.expr, source, matched, decode_expr_cache)
        target_conditions.append(
            Condition(target=cond.target, expr=rewritten, params=rewritten.params)
        )
        target_params[cond.target] = replace(target_params[cond.target], condition=rewritten)
        if is_opaque:
            opaque_condition_names.append(cond.target)

    # Store 3: Space.constraints.
    target_constraints, opaque_constraints = _transport_constraint_tuple(
        source.constraints, source, matched, decode_expr_cache
    )

    # Store 4: ListDomain.element_constraints, for every list-kind param.
    for path, pd in list(target_params.items()):
        if pd.type_kind != "list":
            continue
        assert isinstance(pd.domain, ListDomain)
        new_domain, elem_opaque = _transport_list_domain(
            pd.domain, source, matched, decode_expr_cache
        )
        opaque_constraints.extend(elem_opaque)
        target_params[path] = replace(pd, domain=new_domain)

    return TransportResult(
        target_params=target_params,
        target_conditions=tuple(target_conditions),
        target_constraints=target_constraints,
        opaque_conditions=tuple(sorted(set(opaque_condition_names))),
        opaque_constraints=tuple(opaque_constraints),
    )


# -- row 32 eligibility scans: which paths a .repeat() count or .prop() reads


def count_read_paths(space: Space) -> frozenset[str]:
    from designspace.eval._kleene import _lift_count_deps

    paths: set[str] = set()
    for pd in space.params.values():
        paths |= _lift_count_deps(pd.domain)
    return frozenset(paths)


def prop_read_paths(space: Space) -> frozenset[str]:
    paths: set[str] = set()
    for expr in _iter_all_exprs(space):
        for node in iter_nodes(expr):
            if isinstance(node, Prop):
                assert isinstance(node.operand, ParamExpr)
                paths.add(node.operand.path)
    return frozenset(paths)


def _iter_all_exprs(space: Space) -> list[BoolExpr]:
    exprs: list[BoolExpr] = list(c.expr for c in space.conditions)
    exprs.extend(c.expr for c in space.constraints)
    for pd in space.params.values():
        domain = pd.domain
        while isinstance(domain, ListDomain):
            exprs.extend(c.expr for c in domain.element_constraints)
            domain = domain.element_domain
    return exprs
