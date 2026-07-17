"""The M1 resolve pass pipeline (API_v3.md, "Resolution", steps 1-5, 7-8).

Chart-building (step 6) is M2's job — `ParamDef.chart` stays `None` here, and
`.prior()`/`.log_scale()`/`.quantized()` are parsed and structurally
validated without ever consulting chart-family math (API_v3.md's own
distinction between "Support Types" and "Charts" — see DECISIONS.md D-2).

Each numbered step is a plain function over the previous step's output,
per IMPLEMENTATION_PLAN.md's "each pass a function over an explicit
intermediate."
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from types import MappingProxyType
from typing import Any

from designspace.build._names import check_name
from designspace.build._paramexpr import ParamExpr
from designspace.build._space import Space
from designspace.errors import ResolutionError
from designspace.expr import ArithExpr, ArithOp, Compare, Expr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    Condition,
    IntegerDomain,
    OrdinalDomain,
    ParamDef,
    RealDomain,
    Weights,
)


def resolve_space(exprs: tuple[ParamExpr, ...]) -> Space:
    defs = _collect(exprs)  # step 1
    _check_types_and_names(defs)  # step 2
    # step 3 (desugar): nothing to fold yet in M1. log_scale() already
    # resolves eagerly at the builder (it just calls .prior(Log())); layer
    # folding and expression-bound desugaring arrive with .repeat() (M4)
    # and expression bounds (M5).
    defs_by_path = {d.path: d for d in defs}
    _resolve_condition_refs(defs, defs_by_path)  # step 4
    _check_condition_cycles(defs, defs_by_path)  # step 5
    _validate_declarations(defs)  # step 7
    return _emit(defs)  # step 8


# -- step 1: collect ---------------------------------------------------------


def _collect(exprs: tuple[ParamExpr, ...]) -> tuple[ParamExpr, ...]:
    for e in exprs:
        if not isinstance(e, ParamExpr):
            raise ResolutionError(
                f"ds.space() requires ParamExpr definitions, got {type(e).__name__}"
            )
    return tuple(exprs)


# -- step 2: type-check -------------------------------------------------------


def _check_types_and_names(defs: tuple[ParamExpr, ...]) -> None:
    seen: set[str] = set()
    for d in defs:
        check_name(d.path, what="param name")
        if d.path in seen:
            raise ResolutionError(f"duplicate param name {d.path!r} in this scope")
        seen.add(d.path)

        if len(d.type_calls) == 0:
            raise ResolutionError(
                f"param {d.path!r} has no type: call exactly one of "
                ".real/.integer/.categorical/.ordinal/.bool"
            )
        if len(d.type_calls) > 1:
            raise ResolutionError(
                f"param {d.path!r} declares more than one type {d.type_calls!r}: "
                "exactly one type method is allowed"
            )
        _check_modifier_placement(d)


def _check_modifier_placement(d: ParamExpr) -> None:
    numeric = d.type_kind in ("real", "integer")
    weighted = d.type_kind in ("categorical", "ordinal", "bool")

    if d.prior_spec is not None:
        if isinstance(d.prior_spec, Weights) and not weighted:
            raise ResolutionError(
                f"param {d.path!r}: prior(weights=...) only applies to "
                "categorical, ordinal, or bool params"
            )
        if not isinstance(d.prior_spec, Weights) and not numeric:
            raise ResolutionError(
                f"param {d.path!r}: prior(dist) only applies to real or integer params"
            )
    if d.quantized_spec is not None and not numeric:
        raise ResolutionError(
            f"param {d.path!r}: quantized() only applies to real or integer params"
        )


# -- step 4: resolve references (+ row-14 operand type-checking) -------------


def _resolve_condition_refs(
    defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]
) -> None:
    for d in defs:
        if d.condition is None:
            continue
        for ref_path in d.condition.params:
            if ref_path not in defs_by_path:
                raise ResolutionError(
                    f"param {d.path!r}: .when() references undeclared param {ref_path!r}"
                )
        _check_expr_types(d.condition, defs_by_path, owner=d.path)


def _iter_nodes(node: Expr) -> Iterator[Expr]:
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _check_expr_types(
    condition: Expr, defs_by_path: dict[str, ParamExpr], *, owner: str
) -> None:
    for node in _iter_nodes(condition):
        if isinstance(node, ArithOp):
            for path in node.params:
                kind = defs_by_path[path].type_kind
                if kind in ("categorical", "ordinal"):
                    raise ResolutionError(
                        f"param {owner!r}: .when() performs arithmetic on {kind} "
                        f"param {path!r}, which supports comparison only"
                    )
        elif isinstance(node, Compare):
            if node.op in ("gt", "lt", "ge", "le"):
                for path in node.params:
                    kind = defs_by_path[path].type_kind
                    if kind == "categorical":
                        raise ResolutionError(
                            f"param {owner!r}: .when() orders categorical param "
                            f"{path!r} (categoricals support only ==, !=, is_in)"
                        )
            left, right = node.left, node.right
            if (
                isinstance(left, ParamExpr)
                and isinstance(right, ParamExpr)
                and defs_by_path[left.path].type_kind == "ordinal"
                and defs_by_path[right.path].type_kind == "ordinal"
            ):
                left_domain = defs_by_path[left.path].domain
                right_domain = defs_by_path[right.path].domain
                if (
                    isinstance(left_domain, OrdinalDomain)
                    and isinstance(right_domain, OrdinalDomain)
                    and left_domain.values != right_domain.values
                ):
                    raise ResolutionError(
                        f"param {owner!r}: compares ordinals {left.path!r} and "
                        f"{right.path!r}, which declare different value sequences"
                    )


# -- step 5: cycle detection ---------------------------------------------------


def _check_condition_cycles(
    defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]
) -> None:
    deps: dict[str, frozenset[str]] = {
        d.path: (d.condition.params if d.condition is not None else frozenset()) for d in defs
    }
    for path, own_deps in deps.items():
        if path in own_deps:
            raise ResolutionError(f"param {path!r}: condition references itself")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        if path in visiting:
            raise ResolutionError(f"cycle detected in condition dependencies involving {path!r}")
        visiting.add(path)
        for dep in deps[path]:
            visit(dep)
        visiting.discard(path)
        done.add(path)

    for d in defs:
        visit(d.path)


# -- step 7: validate declarations --------------------------------------------


def _validate_declarations(defs: tuple[ParamExpr, ...]) -> None:
    for d in defs:
        _validate_domain(d)
        _validate_prior(d)
        _validate_quantized(d)
        _validate_default(d)
        _validate_tags_meta(d)


def _validate_domain(d: ParamExpr) -> None:
    domain = d.domain
    if isinstance(domain, RealDomain | IntegerDomain):
        _check_bounds(d.path, domain.lo, domain.hi)
    elif isinstance(domain, CategoricalDomain):
        _check_distinct_values(d.path, domain.values, what="categorical values")
        _check_no_shared_string_image(d.path, domain.values)
    elif isinstance(domain, OrdinalDomain):
        _check_distinct_values(d.path, domain.values, what="ordinal values")
    elif isinstance(domain, BoolDomain):
        pass


def _check_bounds(path: str, lo: Any, hi: Any) -> None:
    if isinstance(lo, ArithExpr) or isinstance(hi, ArithExpr):
        raise ResolutionError(
            f"param {path!r}: expression bounds are not yet implemented (M5); "
            "write literal numeric bounds"
        )
    if isinstance(lo, bool) or isinstance(hi, bool):
        raise ResolutionError(f"param {path!r}: bounds must be numeric, not bool")
    if not math.isfinite(lo) or not math.isfinite(hi):
        raise ResolutionError(f"param {path!r}: bounds must be finite (got lo={lo!r}, hi={hi!r})")
    if lo > hi:
        raise ResolutionError(f"param {path!r}: lo={lo!r} > hi={hi!r}")


def _check_distinct_values(path: str, values: tuple[Any, ...], *, what: str) -> None:
    seen: list[Any] = []
    for v in values:
        for existing in seen:
            if type(existing) is type(v) and existing == v:
                raise ResolutionError(f"param {path!r}: duplicate {what}: {v!r}")
        seen.append(v)


def _check_no_shared_string_image(path: str, values: tuple[Any, ...]) -> None:
    seen_images: dict[str, Any] = {}
    for v in values:
        image = str(v)
        if image in seen_images and type(seen_images[image]) is not type(v):
            raise ResolutionError(
                f"param {path!r}: categorical values {seen_images[image]!r} and {v!r} "
                f"share the string image {image!r}"
            )
        seen_images.setdefault(image, v)


def _validate_prior(d: ParamExpr) -> None:
    if not isinstance(d.prior_spec, Weights):
        return
    weights = d.prior_spec.values
    domain = d.domain
    if d.type_kind == "bool":
        expected_len = 2
    elif isinstance(domain, CategoricalDomain | OrdinalDomain):
        expected_len = len(domain.values)
    else:  # pragma: no cover - unreachable given _check_modifier_placement
        expected_len = len(weights)
    if len(weights) != expected_len:
        raise ResolutionError(
            f"param {d.path!r}: prior(weights=...) has {len(weights)} entries, "
            f"expected {expected_len}"
        )
    if any(w < 0 for w in weights):
        raise ResolutionError(f"param {d.path!r}: prior(weights=...) must be non-negative")
    if all(w == 0 for w in weights):
        raise ResolutionError(f"param {d.path!r}: prior(weights=...) must not be all-zero")


def _validate_quantized(d: ParamExpr) -> None:
    q = d.quantized_spec
    if q is None:
        return
    if (q.step is None) == (q.factor is None):
        raise ResolutionError(
            f"param {d.path!r}: quantized() requires exactly one of step or factor"
        )
    if q.step is not None and (not math.isfinite(q.step) or q.step <= 0):
        raise ResolutionError(f"param {d.path!r}: quantized(step=...) must be finite and > 0")
    if q.factor is not None and (not math.isfinite(q.factor) or q.factor <= 1):
        raise ResolutionError(f"param {d.path!r}: quantized(factor=...) must be finite and > 1")


def _validate_default(d: ParamExpr) -> None:
    if d.default_value is None:
        return
    value = d.default_value
    domain = d.domain
    ok: bool
    if isinstance(domain, RealDomain):
        lo, hi = domain.lo, domain.hi
        # Bounds are already confirmed non-ArithExpr by _check_bounds, which
        # _validate_domain runs before this for the same param.
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        ok = isinstance(value, int | float) and not isinstance(value, bool) and lo <= value <= hi
    elif isinstance(domain, IntegerDomain):
        int_lo, int_hi = domain.lo, domain.hi
        assert isinstance(int_lo, int) and isinstance(int_hi, int)
        ok = isinstance(value, int) and not isinstance(value, bool) and int_lo <= value <= int_hi
    elif isinstance(domain, CategoricalDomain | OrdinalDomain):
        ok = any(type(value) is type(v) and value == v for v in domain.values)
    elif isinstance(domain, BoolDomain):
        ok = isinstance(value, bool)
    else:  # pragma: no cover - unreachable for M1 scalar kinds
        ok = True
    if not ok:
        raise ResolutionError(f"param {d.path!r}: default {value!r} is outside its domain")


def _validate_tags_meta(d: ParamExpr) -> None:
    if "" in d.tags:
        raise ResolutionError(f"param {d.path!r}: empty-string tags are not allowed")
    for key, value in d.meta_map.items():
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ResolutionError(
                f"param {d.path!r}: meta[{key!r}] is not JSON-serializable"
            ) from exc


# -- step 8: emit IR -----------------------------------------------------------


def _emit(defs: tuple[ParamExpr, ...]) -> Space:
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    for d in defs:
        assert d.type_kind is not None
        assert d.domain is not None
        params[d.path] = ParamDef(
            path=d.path,
            type_kind=d.type_kind,
            domain=d.domain,
            prior=d.prior_spec,
            periodic=d.periodic,
            default=d.default_value,
            condition=d.condition,
            tags=d.tags,
            meta=d.meta_map,
            quantized=d.quantized_spec,
        )
        if d.condition is not None:
            conditions.append(Condition(target=d.path, expr=d.condition, params=d.condition.params))
    return Space(params=MappingProxyType(params), conditions=tuple(conditions))
