"""Shared expression checks: row 6 (undeclared refs) and row 14 (arithmetic /
ordering type errors) — API.md's error table.

Used both for `.when()` conditions (resolve/_pipeline.py, M1) and for
`.forbid()`/`.encourage()` expressions (resolve/_constraints.py, M2): both
walk a `BoolExpr`/`Expr` tree against a `path -> definition` mapping, where
the mapping may hold either builder-time `ParamExpr`s (fresh `ds.space()`)
or resolved `ParamDef`s (a constraint added to an already-resolved `Space`)
— both expose `.type_kind`/`.domain`, so the checks are identical either way.

`context` is a pre-formatted, already-quoted description of where the
expression came from — `"param 'x'"` for a condition, `"forbid()"` for a
feasibility constraint — prefixed onto each message.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from typing import Any, cast

from designspace.build._paramexpr import ParamExpr
from designspace.errors import ResolutionError
from designspace.expr import (
    ArithOp,
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
    PositionOf,
    Prop,
    Size,
    Sum,
    SumOver,
)
from designspace.ir import CustomDomain, ListDomain, OrdinalDomain, PermutationDomain, SubsetDomain

_SCALAR_PROP_TYPES = (int, float, bool, str)

_INDEX_RE = re.compile(r"\[\d+\]")


def iter_nodes(node: Expr) -> Iterator[Expr]:
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def _is_declared(path: str, defs_by_path: Mapping[str, Any]) -> bool:
    """`path` may be an ordinary definition path, an instance path into a
    struct/choice lift element (`"stops[0].dwell"` — its `"[]"`-bracketed
    *template* is a declared def) or a direct scalar/choice lift element
    (`"dropout[3]"` — no template of its own, but its owning list param
    is declared). API.md, "Expressions": "Instance paths are legal in
    expressions... An out-of-range index makes the leaf inactive" — the
    out-of-range half is an evaluation-time concern (`_leaf_value`
    already handles it for free); this is the resolution-time half (row 6):
    the *lift itself* still has to be a declared param.
    """
    if path in defs_by_path:
        return True
    if "[" not in path:
        return False
    template = _INDEX_RE.sub("[]", path)
    if template in defs_by_path:
        return True
    base = path[: path.rindex("[")]
    return base in defs_by_path


def _resolve_entry(path: str, defs_by_path: Mapping[str, Any]) -> Any:
    """The declared shape backing `path` (see `_is_declared`) — a direct
    scalar/choice lift element resolves to a synthetic element view
    (`resolve/_relocate.py`'s `element_paramdef`) so type checks see the
    *element's* type_kind/domain, not the enclosing list's; only possible
    once `ListDomain` is actually built (the constraint-on-resolved-Space
    path), so a `.when()` condition's instance reference to a not-yet-
    lifted element falls back to the outer entry unchanged (best effort).
    Callers that tolerate up-references (D-26) never reach here for a
    non-local path — they skip it before resolving — so this only ever
    sees a path already known to be declared somewhere in `defs_by_path`.
    """
    if path in defs_by_path:
        return defs_by_path[path]
    template = _INDEX_RE.sub("[]", path)
    if template in defs_by_path:
        return defs_by_path[template]
    base = path[: path.rindex("[")]
    entry = defs_by_path[base]
    domain = getattr(entry, "domain", None)
    if isinstance(domain, ListDomain):
        from designspace.resolve._relocate import element_paramdef

        return element_paramdef(path, domain)
    return entry


def _referenced_domain(node: Any, defs_by_path: Mapping[str, Any], *, context: str) -> Any:
    if not isinstance(node, ParamExpr):
        raise ResolutionError(
            f"{context}: expects a bare param reference, got {node.kind!r}"
        )
    return _resolve_entry(node.path, defs_by_path).domain


def _require_subset_domain(
    node: Any, defs_by_path: Mapping[str, Any], *, context: str, what: str
) -> SubsetDomain:
    domain = _referenced_domain(node, defs_by_path, context=context)
    if not isinstance(domain, SubsetDomain):
        raise ResolutionError(
            f"{context}: {what} on {node.path!r}, which is not a subset param"
        )
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
    """Unwraps a `.field()` chain down to the underlying lift-referencing
    `ParamExpr` (a scalar lift *is* a vector expression; `.field()`
    projects a struct lift into one — the base reference is what actually
    carries the `ListDomain`)."""
    while isinstance(node, Field):
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
    """Row 16: `.prop()` on undeclared property; non-scalar property type.
    Queried live off the referenced param's `ParamType` instance (`core...
    derive[s] all domain facts from it (describe, validate, extract) rather
    than re-declaring", API.md "Solver Integration") — `properties()` is
    itself an optional capability (DECISIONS.md D-45), absent iff a
    shorthand custom or a full-protocol type that declares none."""
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
            f"{context}: prop({node.name!r}) on {operand_path!r} is not a "
            "declared property (row 16)"
        )
    declared_type = props[node.name]
    if declared_type not in _SCALAR_PROP_TYPES:
        operand_path = cast(ParamExpr, node.operand).path
        raise ResolutionError(
            f"{context}: prop({node.name!r}) on {operand_path!r} declares "
            f"non-scalar type {declared_type!r} — only int/float/bool/str "
            "properties are expression-visible (row 16)"
        )
    return declared_type


def _check_prop_compare_types(
    node: Compare, defs_by_path: Mapping[str, Any], *, context: str
) -> None:
    """Row 16's third clause: type mismatch in comparison — a `.prop()`
    compared against a literal of a different Python type, or against a
    second `.prop()` of a different declared type. Strict type match, no
    int/float leniency (DECISIONS.md D-34 precedent: type-tagged equality
    throughout)."""
    for prop_side, other_side in ((node.left, node.right), (node.right, node.left)):
        if not isinstance(prop_side, Prop):
            continue
        declared_type = prop_type(prop_side, defs_by_path, context=context)
        if isinstance(other_side, Literal):
            if type(other_side.value) is not declared_type:
                raise ResolutionError(
                    f"{context}: prop({prop_side.name!r}) is "
                    f"{declared_type.__name__!r}-typed, compared against "
                    f"{other_side.value!r} ({type(other_side.value).__name__!r}) (row 16)"
                )
        elif isinstance(other_side, Prop):
            other_type = prop_type(other_side, defs_by_path, context=context)
            if other_type is not declared_type:
                raise ResolutionError(
                    f"{context}: prop({prop_side.name!r}) ({declared_type.__name__!r}) "
                    f"compared against prop({other_side.name!r}) "
                    f"({other_type.__name__!r}) (row 16)"
                )


def _check_field_declared(
    node: Field, defs_by_path: Mapping[str, Any], *, context: str
) -> None:
    """Row 6: `.field(name)` requires a struct lift whose element declares
    `name`. `node.operand` is checked only when it is itself a direct lift
    reference — a chained `.field().field()` would need to trace through an
    intermediate (non-lift) struct field, which nested-lift depth already
    rejects elsewhere (resolve/_pipeline.py's `_validate_lift`), so no valid
    space can reach that case today.
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
            f"{context}: field({node.name!r}) on {base.path!r} is not a declared "
            "element field"
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
                # every enclosing scope has contributed its params (D-26).
                continue
            raise ResolutionError(f"{context}: references undeclared param {path!r}")


def check_expr_types(
    expr: Expr,
    defs_by_path: Mapping[str, Any],
    *,
    context: str,
    tolerate_undeclared: bool = False,
) -> None:
    for node in iter_nodes(expr):
        if tolerate_undeclared and any(
            not _is_declared(p, defs_by_path) for p in node.params
        ):
            # A node touching an enclosing-scope up-reference cannot be typed
            # standalone (its referenced def is not in this scope); deferred to
            # finalization over the merged space (D-26).
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
            _check_prop_compare_types(node, defs_by_path, context=context)
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
                    "single repeat() level (row 24) — a nested lift has no canonical order"
                )
        elif isinstance(node, Sum | Min | Max | CountOf | Distinct):
            _require_lift_domain(
                node.operand, defs_by_path, context=context, what=f"{node.kind}()"
            )
