"""Expression transport (API.md, "The Representation Layer" > "Transport").

Conditions and constraints are rewritten, never dropped. Three mechanisms
apply, in order of preference: leaf substitution through `decode_expr`, node
rewriting through `rewrite`, and opaque transport, where core synthesizes a
`ds.value` from `decode` and the source AST, both of which it always knows.

Because nothing is dropped, target activity always matches source activity
and feasibility agreement holds by construction. What differs is quality,
reported through `opaque_conditions` and `opaque_constraints`.

Two implementation facts govern this file. First, expressions live in four
stores, not two: `Space.conditions`, each `ParamDef.condition`,
`Space.constraints` and `ListDomain.element_constraints`. A struct lift's
own `.forbid(...)` puts a constraint on the lift's element template, whose
owning param is never encodable but whose constraint may still reference
encoded descendant fields.

Second, `Expr.params` cannot drive the walk. For `boxes.field("w").sum()` it
reports `{"boxes"}` and never `"boxes[].w"`, so a `.params`-keyed walk would
pass a reference straight through unrewritten. `_governing_path` below,
mirroring `_vector_base`, resolves the projection correctly and must be used
instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from designspace.builder._paramexpr import ParamExpr
from designspace.builder._space import Space
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
    """Signals that a reference has no structural transport path.

    Raised and always caught within this module, when no `rewrite` fired for
    the reference's containing node and its encoding supplies no
    `decode_expr`.
    """

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


# -- governing-path resolution: `.params` cannot drive this walk ------------


def _governing_path(node: Expr, space: Space) -> str | None:
    """The `space.params` key a reference or `.field()` projection reads.

    Returns `None` when `node` is not a reference site. This mirrors
    `_vector_base` in `resolve/_expr_checks.py` together with
    `_check_field_declared`'s field-path construction. `.field()` is never
    chained, only a lift's own bare base taking it, so `node.operand` is
    always a plain `ParamExpr` here.
    """
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
    """The cached `decode_expr(param)` for one governing path.

    `decode_expr` is a pure function of `param` alone, so caching per
    governing path runs it once per param rather than once per occurrence of
    a reference to it.
    """
    if path in cache:
        return cache[path]
    template: Expr | None = None
    if has_decode_expr(encoding):
        # `decode_expr` is an optional, hasattr-checked capability, never
        # part of `Encoding`'s static Protocol shape, under the convention
        # `sample`, `cardinality` and `extract` already follow in
        # `custom/_protocol.py`. It is therefore reached through `getattr`
        # rather than the direct attribute access mypy --strict would
        # reject.
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
    """Transport one node of a source expression tree into its target form.

    Node rewriting is tried first, at every node containing a reference to a
    matched param whose encoding supplies `rewrite`. Leaf substitution
    through `decode_expr` follows, when the node itself is a reference site.
    Otherwise the walk recurses.

    Raises `NeedsOpaque` when a reference site's encoding supplies neither.
    The per-expression driver, `transport_bool` or `transport_arith`,
    catches it and falls back to opaque transport for the whole expression.
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
            return node  # an unmatched param passes through unchanged
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
    """Reconstruct `node` with each child transported through `rewrite_node`.

    This is the exhaustive per-kind dispatch `rewrite_expr` in
    `resolve/_relocate.py` and `substitute_expr` in `ops/_structural.py`
    already use, parameterized by recursive transport rather than by a
    rename or a fixed substitution.

    A source expression never contains a `ChartApply`, that node being
    transport's own output, so no branch handles it here.
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
        # The node a representation itself emits, API.md's second
        # opaque-free leaf under "Expressions". It appears here whenever the
        # source is already a representation target: `rep.target` is an
        # ordinary `Space`, so representing it again is supported by
        # construction, and that is what makes `then` usable past one
        # derived level.
        #
        # Only the operand transports. The carried chart declaration
        # describes the source param's own chart and is not the thing being
        # re-encoded, exactly as `rewrite_expr` in `_relocate.py` and
        # `substitute_expr` in `ops/_structural.py` treat it.
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
    """Every concrete instance path under `path`, for a static count only.

    The walk recurses through chained `.repeat()` levels. Opaque transport
    needs a fixed operand list at resolution time, which a dynamic count
    cannot supply. Core's own chart encoding always supplies `decode_expr`
    and so never reaches opaque transport, leaving this reachable only
    through a user-supplied rule that supplies neither `decode_expr` nor
    `rewrite` for a dynamic-count lift.

    `counts` accumulates the static length bookkeeping key at every level
    touched, giving `{"m": 2, "m[0]": 3, ...}` for a chained repeat.
    `_gather_instance_paths` needs it later to recover each level's count
    during nested aggregate evaluation.
    """
    if not isinstance(domain, ListDomain):
        return [path]
    count = domain.count
    if not isinstance(count, int) or isinstance(count, bool):
        raise ResolutionError(
            f"represent(): cannot opaquely transport an expression touching "
            f"{path!r}, whose repeat() count is dynamic; opaque transport "
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
                "Unknown, though every ds.value operand was active by the "
                "calling "
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
    """Transport one `Condition` or `Constraint` expression.

    Returns `(transported_expr, is_opaque)`. `is_opaque` says whether any
    reference inside `expr` needed the opaque fallback. It is a
    whole-expression decision, at the granularity `opaque_conditions` and
    `opaque_constraints` report.
    """
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
    """Transport store 4, `ListDomain.element_constraints`.

    Recurses through a chained or nested `.repeat()` chain. Each level's own
    template constraints transport independently of the others'.
    """
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
    """Rewrite every expression in all four stores.

    `raw_target_params` holds the structurally built, not-yet-transported
    target `ParamDef` records each `Encoding.target()` produced.

    The returned bundle is self-consistent: for a given path,
    `target_conditions` and that param's own `.condition` field carry the
    identical rewritten expression object.
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
