"""Shared IR codec: `ParamDef`/`Domain`/`Prior`/`QuantizedSpec`/`Constraint`/
`Condition` <-> canonical tree (API_v3.md, "Identity and Serialization";
"IR"). One encoder, three call shapes selected by `scope`:

- `"document"` — `to_json`'s full-fidelity shape: every field, `origin` kept,
  every constraint (hard and declared) present, expression as stored
  (never bound-origin-canonicalized — that canonicalization is preimage-only).
- `"full"` — the fingerprint `full` scope: `origin` excluded, bound-origin
  constraints canonicalized to forbidden-state form (D-29(4)), default/tags/
  meta kept, both hard and declared constraints kept.
- `"sampling"` — the fingerprint `sampling` scope: as `full` but declared
  (`hard=False`) constraints and per-param default/tags/meta dropped
  (API_v3.md's scope table; DECISIONS.md D-33 additionally puts `quantized`/
  `periodic` in both fingerprint scopes despite the table's "domain, prior"
  shorthand).

`decode_*` only ever reconstructs the `"document"` shape — a fingerprint
preimage is one-way (hash only, never fed back through `from_json`).

Optional/auxiliary fields (`condition`, `default`, `tags`, `meta`) are
omitted from the tree entirely when absent/empty, never emitted as `null`/
`[]`/`{}` — so a future milestone's *additive* field (M8's anchors) costs
nothing for spaces that don't use it: an anchor-free space's `full` preimage
is byte-identical before and after anchors exist as a concept.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal

from designspace.errors import SerializationError
from designspace.expr import Compare
from designspace.identity._tags import (
    decode_arith_expr,
    decode_bool_expr,
    decode_default_value,
    encode_default_value,
    encode_expr,
    tag_value,
    untag_value,
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    Condition,
    Constraint,
    Domain,
    IntegerDomain,
    ListDomain,
    Log,
    Logit,
    OrdinalDomain,
    ParamDef,
    PermutationDomain,
    Power,
    PriorSpec,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
    Weights,
)

Scope = Literal["document", "full", "sampling"]
OnUnserializable = Literal["raise", "mark", "drop"]

_OPAQUE_MARKER = {"kind": "opaque", "$opaque": True}


@dataclass
class EncodeContext:
    """Threaded through every encoder that might hit a non-serializable
    site. In M7 the only such site is an external `Prior` (DECISIONS.md
    D-31) — the other four sites the spec enumerates (`.custom()` shorthand,
    `code`/`symbolic` validators, `symbolic` sampler, `Primitive.fn`) have no
    builder surface yet (M9/M12), so no IR they'd appear in can exist."""

    mode: OnUnserializable
    dropped: list[str] = field(default_factory=list)


# -- QuantizedSpec --------------------------------------------------------


def encode_quantized(q: QuantizedSpec | None) -> Any:
    if q is None:
        return None
    return {"step": q.step, "factor": q.factor, "include_hi": q.include_hi}


def decode_quantized(tree: Any) -> QuantizedSpec | None:
    if tree is None:
        return None
    return QuantizedSpec(step=tree["step"], factor=tree["factor"], include_hi=tree["include_hi"])


# -- Prior ------------------------------------------------------------


def encode_prior(path: str, prior: PriorSpec | None, ctx: EncodeContext) -> Any:
    if prior is None:
        return None
    if isinstance(prior, Log):
        return {"kind": "log"}
    if isinstance(prior, Logit):
        return {"kind": "logit"}
    if isinstance(prior, Power):
        return {"kind": "power", "p": float(prior.p)}
    if isinstance(prior, Weights):
        return {"kind": "weights", "values": [float(v) for v in prior.values]}
    # External `Prior` protocol object (ppf/cdf duck type): opaque (D-31).
    if ctx.mode == "raise":
        raise SerializationError(
            f"param {path!r}: external prior {prior!r} has no structural encoding "
            "(DECISIONS.md D-31) — pass on_unserializable='mark' or 'drop'"
        )
    if ctx.mode == "mark":
        return dict(_OPAQUE_MARKER)
    assert ctx.mode == "drop"
    ctx.dropped.append(f"param {path!r}: prior (external, opaque)")
    return None


def decode_prior(tree: Any) -> PriorSpec | None:
    if tree is None:
        return None
    kind = tree["kind"]
    if kind == "log":
        return Log()
    if kind == "logit":
        return Logit()
    if kind == "power":
        return Power(tree["p"])
    if kind == "weights":
        return Weights(tuple(tree["values"]))
    if kind == "opaque":
        raise SerializationError(
            "cannot reconstruct an external prior from a mark-sentinel document "
            "— from_json only round-trips fully serializable spaces"
        )
    raise SerializationError(f"unknown prior kind {kind!r}")


# -- Domain (recursive over ListDomain) -----------------------------------


def _encode_count(count: int | Any) -> Any:
    if isinstance(count, int):
        return {"kind": "static", "n": count}
    return {"kind": "dynamic", "expr": encode_expr(count)}


def _decode_count(tree: Any) -> Any:
    if tree["kind"] == "static":
        return tree["n"]
    return decode_arith_expr(tree["expr"])


def encode_domain(kind: str, domain: Domain, scope: Scope, ctx: EncodeContext, path: str) -> Any:
    if kind == "real":
        assert isinstance(domain, RealDomain)
        assert isinstance(domain.lo, int | float) and isinstance(domain.hi, int | float)
        return {"kind": "real", "lo": float(domain.lo), "hi": float(domain.hi)}
    if kind == "integer":
        assert isinstance(domain, IntegerDomain)
        assert isinstance(domain.lo, int) and isinstance(domain.hi, int)
        return {"kind": "integer", "lo": domain.lo, "hi": domain.hi}
    if kind == "categorical":
        assert isinstance(domain, CategoricalDomain)
        return {"kind": "categorical", "values": [tag_value(v) for v in domain.values]}
    if kind == "ordinal":
        assert isinstance(domain, OrdinalDomain)
        return {"kind": "ordinal", "values": [tag_value(v) for v in domain.values]}
    if kind == "bool":
        assert isinstance(domain, BoolDomain)
        return {"kind": "bool"}
    if kind == "subset":
        assert isinstance(domain, SubsetDomain)
        return {
            "kind": "subset",
            "items": [tag_value(v) for v in domain.items],
            "min_size": domain.min_size,
            "max_size": domain.max_size,
        }
    if kind == "permutation":
        assert isinstance(domain, PermutationDomain)
        return {"kind": "permutation", "items": [tag_value(v) for v in domain.items]}
    if kind == "choice":
        assert isinstance(domain, ChoiceDomain)
        return {
            "kind": "choice",
            "variants": list(domain.variants),
            "has_payload": sorted(domain.has_payload),
        }
    if kind == "space":
        assert isinstance(domain, StructDomain)
        return {"kind": "space"}
    if kind == "list":
        assert isinstance(domain, ListDomain)
        return _encode_list_domain(domain, scope, ctx, path)
    raise SerializationError(f"param {path!r}: unknown domain kind {kind!r}")


def _encode_list_domain(domain: ListDomain, scope: Scope, ctx: EncodeContext, path: str) -> Any:
    tree: dict[str, Any] = {
        "kind": "list",
        "element_kind": domain.element_kind,
        "element_domain": encode_domain(
            domain.element_kind, domain.element_domain, scope, ctx, path
        ),
        "element_periodic": domain.element_periodic,
        "count": _encode_count(domain.count),
    }
    prior_tree = encode_prior(path, domain.element_prior, ctx)
    if prior_tree is not None:
        tree["element_prior"] = prior_tree
    quantized_tree = encode_quantized(domain.element_quantized)
    if quantized_tree is not None:
        tree["element_quantized"] = quantized_tree
    if domain.element_default is not None:
        tree["element_default"] = encode_default_value(domain.element_default)
    if domain.list_default is not None:
        tree["list_default"] = encode_default_value(domain.list_default)
    encoded_constraints = [
        encoded
        for c in domain.element_constraints
        if (encoded := encode_constraint(c, scope)) is not None
    ]
    if encoded_constraints:
        tree["element_constraints"] = encoded_constraints
    return tree


def decode_domain(kind: str, tree: Any, path: str) -> Domain:
    if kind == "real":
        return RealDomain(float(tree["lo"]), float(tree["hi"]))
    if kind == "integer":
        return IntegerDomain(int(tree["lo"]), int(tree["hi"]))
    if kind == "categorical":
        return CategoricalDomain(tuple(untag_value(v) for v in tree["values"]))
    if kind == "ordinal":
        return OrdinalDomain(tuple(untag_value(v) for v in tree["values"]))
    if kind == "bool":
        return BoolDomain()
    if kind == "subset":
        return SubsetDomain(
            items=tuple(untag_value(v) for v in tree["items"]),
            min_size=tree["min_size"],
            max_size=tree["max_size"],
        )
    if kind == "permutation":
        return PermutationDomain(tuple(untag_value(v) for v in tree["items"]))
    if kind == "choice":
        return ChoiceDomain(
            variants=tuple(tree["variants"]), has_payload=frozenset(tree["has_payload"])
        )
    if kind == "space":
        return StructDomain()
    if kind == "list":
        return _decode_list_domain(tree, path)
    raise SerializationError(f"param {path!r}: unknown domain kind {kind!r}")


def _decode_list_domain(tree: Any, path: str) -> ListDomain:
    element_kind = tree["element_kind"]
    element_default = (
        decode_default_value(tree["element_default"]) if "element_default" in tree else None
    )
    list_default = (
        decode_default_value(tree["list_default"]) if "list_default" in tree else None
    )
    return ListDomain(
        element_kind=element_kind,
        element_domain=decode_domain(element_kind, tree["element_domain"], path),
        element_chart=None,  # rebuilt by the caller (needs the enclosing param's path)
        element_prior=decode_prior(tree.get("element_prior")),
        element_periodic=tree["element_periodic"],
        element_quantized=decode_quantized(tree.get("element_quantized")),
        element_default=element_default,
        count=_decode_count(tree["count"]),
        list_default=list_default,
        element_constraints=tuple(
            decode_constraint(c) for c in tree.get("element_constraints", ())
        ),
    )


# -- Constraint / Condition -----------------------------------------------


def _canonicalize_bound_origin(c: Constraint) -> Constraint:
    """D-29(4): a bound-origin constraint stores the DESIRED predicate
    (`x <= y`); the preimage canonicalizes it to its forbidden-state
    negation (`x > y`) — byte-identical to a user `.forbid(x > y)` — so
    fingerprint equality tracks feasibility despite `origin` being excluded
    from the preimage. Bound constraints are always a single top-level
    `Compare(op, ParamExpr(target), other)` (resolve/_bounds.py
    `_bound_constraint`); element-level constraints are never bound-origin
    (repeat-element bound expressions aren't supported yet, D-29)."""
    if c.origin != "bound":
        return c
    expr = c.expr
    assert isinstance(expr, Compare)
    flip = {"le": "gt", "ge": "lt"}
    assert expr.op in flip, f"unexpected bound-origin comparison op {expr.op!r}"
    return replace(c, expr=Compare(flip[expr.op], expr.left, expr.right))


def encode_constraint(c: Constraint, scope: Scope) -> Any:
    """Returns `None` when `c` is excluded at this scope (a declared/soft
    constraint at `sampling`)."""
    if scope == "sampling" and not c.hard:
        return None
    expr = c.expr if scope == "document" else _canonicalize_bound_origin(c).expr
    tree: dict[str, Any] = {"expr": encode_expr(expr), "hard": c.hard}
    if scope == "document":
        tree["origin"] = c.origin
    if scope != "sampling":
        if c.tags:
            tree["tags"] = sorted(c.tags)
        if c.meta:
            # Meta values are JSON-serializable, not necessarily scalar (row
            # 23 gates "JSON-serializable"; a list/dict value passes) — the
            # same generic recursive codec `default`/`list_default` use.
            tree["meta"] = {k: encode_default_value(v) for k, v in sorted(c.meta.items())}
    return tree


def decode_constraint(tree: Any) -> Constraint:
    expr = decode_bool_expr(tree["expr"])
    tags = frozenset(tree.get("tags", ()))
    meta = MappingProxyType({k: decode_default_value(v) for k, v in tree.get("meta", {}).items()})
    return Constraint(
        expr=expr,
        hard=tree["hard"],
        origin=tree.get("origin", "user"),
        tags=tags,
        meta=meta,
        params=expr.params,
    )


def encode_condition(cond: Condition) -> Any:
    return {"target": cond.target, "expr": encode_expr(cond.expr)}


def decode_condition(tree: Any) -> Condition:
    expr = decode_bool_expr(tree["expr"])
    return Condition(target=tree["target"], expr=expr, params=expr.params)


# -- ParamDef ---------------------------------------------------------


def encode_param(pd: ParamDef, scope: Scope, ctx: EncodeContext) -> dict[str, Any]:
    tree: dict[str, Any] = {
        "path": pd.path,
        "kind": pd.type_kind,
        "domain": encode_domain(pd.type_kind, pd.domain, scope, ctx, pd.path),
        "periodic": pd.periodic,
    }
    prior_tree = encode_prior(pd.path, pd.prior, ctx)
    if prior_tree is not None:
        tree["prior"] = prior_tree
    quantized_tree = encode_quantized(pd.quantized)
    if quantized_tree is not None:
        tree["quantized"] = quantized_tree
    if pd.condition is not None:
        tree["condition"] = encode_expr(pd.condition)
    if scope != "sampling":
        if pd.default is not None:
            # A default can be subset/permutation-shaped (a list of items),
            # not only scalar — `encode_default_value` (not the scalar-only
            # `tag_value`) handles that generically.
            tree["default"] = encode_default_value(pd.default)
        if pd.tags:
            tree["tags"] = sorted(pd.tags)
        if pd.meta:
            # Meta values are JSON-serializable, not necessarily scalar (row
            # 23 gates "JSON-serializable"; a list/dict value passes) — the
            # same generic recursive codec `default`/`list_default` use.
            tree["meta"] = {k: encode_default_value(v) for k, v in sorted(pd.meta.items())}
    return tree


def decode_param(tree: Any) -> ParamDef:
    path = tree["path"]
    kind = tree["kind"]
    default = decode_default_value(tree["default"]) if "default" in tree else None
    tags = frozenset(tree.get("tags", ()))
    meta = MappingProxyType({k: decode_default_value(v) for k, v in tree.get("meta", {}).items()})
    condition = decode_bool_expr(tree["condition"]) if "condition" in tree else None
    return ParamDef(
        path=path,
        type_kind=kind,
        domain=decode_domain(kind, tree["domain"], path),
        prior=decode_prior(tree.get("prior")),
        periodic=tree["periodic"],
        default=default,
        condition=condition,
        tags=tags,
        meta=meta,
        chart=None,  # rebuilt by the caller (serialize/_fromjson.py)
        quantized=decode_quantized(tree.get("quantized")),
    )
