"""Shared expression checks for rows 6 and 14 of API.md's error table.

Row 6 is an undeclared reference; row 14 covers arithmetic and ordering type
errors.

Both `.when()` conditions (`resolve/_pipeline.py`) and `.forbid()` and
`.encourage()` expressions (`resolve/_constraints.py`) use these checks.
Each walks an `Expr` tree against a `path -> definition` mapping. That
mapping holds builder-time `ParamExpr` objects for a fresh `ds.space()` and
resolved `ParamDef` records for a constraint added to an already-resolved
`Space`. Both expose `.type_kind` and `.domain`, so the checks are identical
either way.

`context` is a pre-formatted, already-quoted description of where the
expression came from, prefixed onto each message: `"param 'x'"` for a
condition, `"forbid()"` for a feasibility constraint.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, cast

from designspace.builder._paramexpr import ParamExpr
from designspace.errors import ResolutionError
from designspace.expr import (
    SCALAR_TYPES,
    ArithOp,
    BoolOp,
    ChartApply,
    Compare,
    Contains,
    CountOf,
    Distinct,
    Expr,
    Field,
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
from designspace.ir import CustomDomain, ListDomain, OrdinalDomain, PermutationDomain, SubsetDomain
from designspace.paths._grammar import split_instance_path

_SCALAR_PROP_TYPES = SCALAR_TYPES


def iter_nodes(node: Expr) -> Iterator[Expr]:
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def _is_declared(path: str, defs_by_path: Mapping[str, Any]) -> bool:
    """Whether `path` names something declared.

    `path` may be an ordinary definition path; an instance path into a
    struct or choice lift element, such as `"stops[0].dwell"`, whose
    `"[]"`-bracketed template is a declared definition; a direct scalar or
    choice lift element such as `"dropout[3]"`, which has no template of its
    own but whose owning list param is declared; or any deeper or mixed
    nesting the grammar admits, such as `g[0][1]` or `layers[2].act[1]`. See
    `paths._grammar.split_instance_path`.

    API.md, "Expressions" says "Instance paths are legal in expressions...
    An out-of-range index makes the leaf inactive". The out-of-range half is
    an evaluation-time concern that `_leaf_value` handles. This is the
    resolution-time half (row 6): the lift itself must be a declared param.
    """
    if path in defs_by_path:
        return True
    if "[" not in path:
        return False
    split = split_instance_path(path)
    if split is None:
        return False
    base_key, _brackets = split
    return base_key in defs_by_path


def _resolve_entry(path: str, defs_by_path: Mapping[str, Any]) -> Any:
    """The declared shape backing `path`, in the sense `_is_declared` uses.

    A direct scalar or choice lift element resolves to a synthetic element
    view, `element_paramdef` in `resolve/_relocate.py`, consumed one bracket
    at a time so that a chained or nested scalar lift such as `g[0][1]`
    resolves all the way to its leaf. Type checks then see the element's
    `type_kind` and domain rather than the enclosing list's.

    This is possible only once the `ListDomain` is built, which is the
    constraint-on-resolved-Space path. A `.when()` condition's instance
    reference to a not-yet-lifted element falls back to the outer entry
    unchanged, and the finalization pass `check_fully_resolved` re-checks it
    once every lift is built.

    Callers that tolerate an enclosing-scope up-reference skip a non-local
    path before resolving it, so this only ever sees a path already known to
    be declared somewhere in `defs_by_path`.
    """
    if path in defs_by_path:
        return defs_by_path[path]
    split = split_instance_path(path)
    assert split is not None  # only ever called on an already-declared path
    base_key, brackets = split
    entry = defs_by_path[base_key]
    for _ in brackets:
        domain = getattr(entry, "domain", None)
        if not isinstance(domain, ListDomain):
            return entry  # not yet built, per-scope timing; best effort
        from designspace.resolve._relocate import element_paramdef

        entry = element_paramdef(path, domain)
    return entry


def _check_static_index_range(path: str, defs_by_path: Mapping[str, Any], *, context: str) -> None:
    """Row 29: an out-of-range bracket index against a static count.

    API.md, "Expressions" says "against a static count the length is known
    at resolution, so an out-of-range index... is a resolution error." A
    dynamic count keeps the runtime Unknown rule, so this no-ops for it and
    defers to the evaluation-time handling in `eval/_kleene.py`. So does a
    not-yet-built `ListDomain`; the finalization pass `check_fully_resolved`
    re-runs this once every lift is built.
    """
    if "[" not in path:
        return
    split = split_instance_path(path)
    if split is None:
        return
    base_key, brackets = split
    entry = defs_by_path.get(base_key)
    if entry is None:
        return
    for idx in brackets:
        domain = getattr(entry, "domain", None)
        if not isinstance(domain, ListDomain):
            return
        count = domain.count
        if (
            idx is not None  # a bare "[]" virtual template marker: nothing to range-check
            and isinstance(count, int)
            and not isinstance(count, bool)
            and not (-count <= idx < count)
        ):
            raise ResolutionError(
                f"{context}: instance index {idx} on {path!r} is out of range for "
                f"a static repeat() count of {count}"
            )
        from designspace.resolve._relocate import element_paramdef

        entry = element_paramdef(path, domain)


def _reject_lift_valued_bool_operand(
    operand: Expr, defs_by_path: Mapping[str, Any], *, context: str
) -> None:
    """Row 29: a boolean operator applied to a still-list-typed operand.

    The operators are `~`, `&`, `|`, and a bare condition or constraint. An
    example is `~ds.param("g[0]")` on a `repeat(4, 4)` bool lift, where
    `g[0]` is the inner list rather than a scalar bool. Without this check
    the operand is silently coerced by truthiness, taking `bool()` of the
    inner list's own count.
    """
    if not isinstance(operand, ParamExpr):
        return
    if not _is_declared(operand.path, defs_by_path):
        return  # an up-reference or genuinely undeclared; other checks own this
    if _resolve_entry(operand.path, defs_by_path).type_kind == "list":
        raise ResolutionError(
            f"{context}: boolean operator applied to {operand.path!r}, which is "
            "still a lift (repeat()), not a scalar bool"
        )


def _referenced_domain(node: Any, defs_by_path: Mapping[str, Any], *, context: str) -> Any:
    if not isinstance(node, ParamExpr):
        raise ResolutionError(f"{context}: expects a bare param reference, got {node.kind!r}")
    return _resolve_entry(node.path, defs_by_path).domain


def _require_subset_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str, what: str
) -> SubsetDomain:
    domain = _referenced_domain(node, defs_by_path, context=context)
    if not isinstance(domain, SubsetDomain):
        raise ResolutionError(f"{context}: {what} on {node.path!r}, which is not a subset param")
    return domain


def _require_permutation_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str
) -> PermutationDomain:
    domain = _referenced_domain(node, defs_by_path, context=context)
    if not isinstance(domain, PermutationDomain):
        raise ResolutionError(
            f"{context}: position_of() on {node.path!r}, which is not a permutation param"
        )
    return domain


def _lift_depth(domain: ListDomain) -> int:
    depth = 0
    d: Any = domain
    while isinstance(d, ListDomain):
        depth += 1
        d = d.element_domain
    return depth


def _vector_base(node: Any) -> Any:
    """Unwrap to the lift-referencing `ParamExpr` under a vector expression.

    This strips a `.field()` chain and a representation's `ChartApply`
    wrapper, which a transported expression may have inserted around either
    a bare lift reference or a `.field()` projection. A scalar lift is
    itself a vector expression, and `.field()` projects a struct lift into
    one; the base reference is what carries the `ListDomain`.

    Unwrapping `ChartApply` is required rather than cosmetic. Without it a
    transported aggregate such as `Sum(ChartApply(Field(...)))` fails
    `_referenced_domain`'s bare-param-reference check on its own decode.
    """
    while isinstance(node, Field | ChartApply):
        node = node.operand
    return node


def _require_lift_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str, what: str
) -> ListDomain:
    base = _vector_base(node)
    domain = _referenced_domain(base, defs_by_path, context=context)
    if not isinstance(domain, ListDomain):
        raise ResolutionError(
            f"{context}: {what} on {base.path!r}, which is not a lift (repeat()) param"
        )
    return domain


def prop_type(node: Prop, defs_by_path: Mapping[str, Any], *, context: str) -> type:
    """Row 16: `.prop()` on an undeclared property or a non-scalar type.

    The property set is queried live off the referenced param's `ParamType`
    instance, since core "derive[s] all domain facts from it (describe,
    validate, extract) rather than re-declaring" (API.md, "Solver
    Integration"). `properties()` is an optional capability, absent exactly
    for a shorthand custom and for a full-protocol type that declares none.
    """
    domain = _referenced_domain(node.operand, defs_by_path, context=context)
    if not isinstance(domain, CustomDomain):
        operand_path = cast(ParamExpr, node.operand).path
        raise ResolutionError(
            f"{context}: prop({node.name!r}) on {operand_path!r}, which is not a custom param"
        )
    props: dict[str, type] = {}
    if domain.param_type is not None and hasattr(domain.param_type, "properties"):
        props = domain.param_type.properties()
    if node.name not in props:
        operand_path = cast(ParamExpr, node.operand).path
        raise ResolutionError(
            f"{context}: prop({node.name!r}) on {operand_path!r} is not a declared property"
        )
    declared_type = props[node.name]
    if declared_type not in _SCALAR_PROP_TYPES:
        operand_path = cast(ParamExpr, node.operand).path
        raise ResolutionError(
            f"{context}: prop({node.name!r}) on {operand_path!r} declares "
            f"non-scalar type {declared_type!r}; only int/float/bool/str "
            "properties are expression-visible"
        )
    return declared_type


def _opaque_scalar_type(node: Any, defs_by_path: Mapping[str, Any], *, context: str) -> type | None:
    """The scalar type an opaque leaf declares or returns, else `None`.

    The opaque leaves are `Prop` and `Value`, the two dual-typed leaves
    API.md checks alike: row 16's scalar restriction "applies identically"
    to `ds.value`.
    """
    if isinstance(node, Prop):
        return prop_type(node, defs_by_path, context=context)
    if isinstance(node, Value):
        return node.returns
    return None


def _describe_opaque(node: Prop | Value) -> str:
    if isinstance(node, Prop):
        return f"prop({node.name!r})"
    fn_name = getattr(node.fn, "__name__", repr(node.fn))
    return f"ds.value({fn_name}, ...)"


def _check_opaque_compare_types(
    node: Compare, defs_by_path: Mapping[str, Any], *, context: str
) -> None:
    """A comparison type mismatch on an opaque leaf.

    This is row 16's third clause for `.prop()` and row 30's comparison
    clause for `ds.value`. It fires when an opaque leaf is compared against
    a literal of a different Python type, or against a second opaque leaf of
    a different declared or returned type.

    The match is strict, with no int/float leniency, following the
    type-tagged equality used throughout the library. The message names the
    side being checked first, so a mismatch between a `.prop()` and a
    `ds.value()` reads from whichever side the walk reached first.
    """
    for this_side, other_side in ((node.left, node.right), (node.right, node.left)):
        if not isinstance(this_side, Prop | Value):
            continue
        declared_type = _opaque_scalar_type(this_side, defs_by_path, context=context)
        assert declared_type is not None
        if isinstance(other_side, Literal):
            if type(other_side.value) is not declared_type:
                raise ResolutionError(
                    f"{context}: {_describe_opaque(this_side)} is "
                    f"{declared_type.__name__!r}-typed, compared against "
                    f"{other_side.value!r} ({type(other_side.value).__name__!r})"
                )
        elif isinstance(other_side, Prop | Value):
            other_type = _opaque_scalar_type(other_side, defs_by_path, context=context)
            if other_type is not None and other_type is not declared_type:
                raise ResolutionError(
                    f"{context}: {_describe_opaque(this_side)} ({declared_type.__name__!r}) "
                    f"compared against {_describe_opaque(other_side)} "
                    f"({other_type.__name__!r})"
                )


def _check_field_declared(node: Field, defs_by_path: Mapping[str, Any], *, context: str) -> None:
    """Row 6: `.field(name)` requires a struct lift whose element declares `name`.

    `node.operand` is checked only when it is itself a direct lift
    reference. A chained `.field().field()` would have to trace through an
    intermediate, non-lift struct field, and `_validate_lift` in
    `resolve/_pipeline.py` already rejects that nesting depth, so no valid
    space reaches the case.
    """
    base = node.operand
    if not isinstance(base, ParamExpr):
        return
    domain = _referenced_domain(base, defs_by_path, context=context)
    if not isinstance(domain, ListDomain) or domain.element_kind != "space":
        raise ResolutionError(
            f"{context}: field({node.name!r}) on {base.path!r}, which is not a "
            "struct lift (a repeat() of a .space() element)"
        )
    field_path = f"{base.path}[].{node.name}"
    if field_path not in defs_by_path:
        raise ResolutionError(
            f"{context}: field({node.name!r}) on {base.path!r} is not a declared element field"
        )


def check_refs_declared(
    expr: Expr,
    defs_by_path: Mapping[str, Any],
    *,
    context: str,
    tolerate_undeclared: bool = False,
) -> None:
    for path in expr.params:
        if not _is_declared(path, defs_by_path):
            if tolerate_undeclared:
                # An up-reference to a param bound in an enclosing scope
                # (API.md's sole scoping rule): unresolvable while this
                # payload resolves standalone, re-checked at finalization once
                # every enclosing scope has contributed its params.
                continue
            raise ResolutionError(f"{context}: references undeclared param {path!r}")


def check_expr_types(
    expr: Expr,
    defs_by_path: Mapping[str, Any],
    *,
    context: str,
    tolerate_undeclared: bool = False,
) -> None:
    if isinstance(expr, ParamExpr):
        # Row 29 (item 6): a bare bool leaf used directly as the whole
        # condition or constraint, with no wrapping `Not` or `BoolOp`. This
        # is the third named boolean position, checked once here because
        # `iter_nodes` yielding it as an ordinary node would conflate it
        # with a bare ParamExpr in a vector-aggregate operand position,
        # which is legitimately list-typed and must not raise.
        _reject_lift_valued_bool_operand(expr, defs_by_path, context=context)
    for node in iter_nodes(expr):
        if tolerate_undeclared and any(not _is_declared(p, defs_by_path) for p in node.params):
            # A node touching an enclosing-scope up-reference cannot be typed
            # standalone (its referenced def is not in this scope); deferred to
            # finalization over the merged space.
            continue
        if isinstance(node, ArithOp):
            for path in node.params:
                kind = _resolve_entry(path, defs_by_path).type_kind
                if kind in ("categorical", "ordinal"):
                    raise ResolutionError(
                        f"{context}: performs arithmetic on {kind} "
                        f"param {path!r}, which supports comparison only"
                    )
        elif isinstance(node, Prop):
            prop_type(node, defs_by_path, context=context)
        elif isinstance(node, Compare):
            if node.op in ("gt", "lt", "ge", "le"):
                for path in node.params:
                    kind = _resolve_entry(path, defs_by_path).type_kind
                    if kind == "categorical":
                        raise ResolutionError(
                            f"{context}: orders categorical param "
                            f"{path!r} (categoricals support only ==, !=, is_in)"
                        )
            _check_opaque_compare_types(node, defs_by_path, context=context)
            left, right = node.left, node.right
            if (
                isinstance(left, ParamExpr)
                and isinstance(right, ParamExpr)
                and _resolve_entry(left.path, defs_by_path).type_kind == "ordinal"
                and _resolve_entry(right.path, defs_by_path).type_kind == "ordinal"
            ):
                left_domain = _resolve_entry(left.path, defs_by_path).domain
                right_domain = _resolve_entry(right.path, defs_by_path).domain
                if (
                    isinstance(left_domain, OrdinalDomain)
                    and isinstance(right_domain, OrdinalDomain)
                    and left_domain.values != right_domain.values
                ):
                    raise ResolutionError(
                        f"{context}: compares ordinals {left.path!r} and "
                        f"{right.path!r}, which declare different value sequences"
                    )
            for param_side, literal_side in ((left, right), (right, left)):
                if not (isinstance(param_side, ParamExpr) and isinstance(literal_side, Literal)):
                    continue
                entry = _resolve_entry(param_side.path, defs_by_path)
                if entry.type_kind != "ordinal" or not isinstance(entry.domain, OrdinalDomain):
                    continue
                if not any(
                    type(v) is type(literal_side.value) and v == literal_side.value
                    for v in entry.domain.values
                ):
                    raise ResolutionError(
                        f"{context}: compares ordinal {param_side.path!r} against "
                        f"{literal_side.value!r}, which is not a declared value"
                    )
        elif isinstance(node, Field):
            _check_field_declared(node, defs_by_path, context=context)
        elif isinstance(node, Contains):
            _require_subset_domain(node.operand, defs_by_path, context=context, what="contains()")
        elif isinstance(node, Size):
            _require_subset_domain(node.operand, defs_by_path, context=context, what="size()")
        elif isinstance(node, SumOver):
            subset_domain = _require_subset_domain(
                node.operand, defs_by_path, context=context, what="sum_over()"
            )
            universe = set(subset_domain.items)
            bad_keys = sorted(set(node.mapping.keys()) - universe, key=repr)
            if bad_keys:
                operand_path = cast(ParamExpr, node.operand).path
                raise ResolutionError(
                    f"{context}: sum_over() mapping has keys {bad_keys!r} outside "
                    f"the item universe of {operand_path!r}"
                )
        elif isinstance(node, PositionOf):
            perm_domain = _require_permutation_domain(node.operand, defs_by_path, context=context)
            if node.item not in perm_domain.items:
                operand_path = cast(ParamExpr, node.operand).path
                raise ResolutionError(
                    f"{context}: position_of({node.item!r}) on {operand_path!r} "
                    "is not a declared member"
                )
        elif isinstance(node, Length):
            _require_lift_domain(node.operand, defs_by_path, context=context, what="length()")
        elif isinstance(node, IsSorted):
            domain = _require_lift_domain(
                node.operand, defs_by_path, context=context, what="is_sorted()"
            )
            if _lift_depth(domain) > 1:
                operand_path = _vector_base(node.operand).path
                raise ResolutionError(
                    f"{context}: is_sorted() on {operand_path!r} is restricted to a "
                    "single repeat() level; a nested lift has no canonical order"
                )
        elif isinstance(node, Sum | Min | Max | CountOf | Distinct):
            _require_lift_domain(node.operand, defs_by_path, context=context, what=f"{node.kind}()")
        elif isinstance(node, ParamExpr):
            # Row 29: a static out-of-range instance index (item 2). Runs
            # for every bare ParamExpr regardless of its surrounding node,
            # since an out-of-range index is wrong wherever it appears. The
            # lift-valued-bool check below applies only at specific
            # boolean-operator positions.
            _check_static_index_range(node.path, defs_by_path, context=context)
        elif isinstance(node, Not):
            # Row 29: `~` applied to a still-list-typed operand (item 6).
            _reject_lift_valued_bool_operand(node.operand, defs_by_path, context=context)
        elif isinstance(node, BoolOp):
            # Row 29: `&`/`|` applied to a still-list-typed operand (item 6).
            _reject_lift_valued_bool_operand(node.left, defs_by_path, context=context)
            _reject_lift_valued_bool_operand(node.right, defs_by_path, context=context)
