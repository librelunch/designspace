"""Shared IR codec: `ParamDef`/`Domain`/`Prior`/`QuantizedSpec`/`Constraint`/
`Condition` <-> canonical tree (API.md, "Identity and Serialization";
"IR"). One encoder, three call shapes selected by `scope`:

- `"document"` — `to_json`'s full-fidelity shape: every field, `origin` kept,
  every constraint (hard and declared) present, expression as stored
  (never polarity-canonicalized — that canonicalization is preimage-only).
- `"full"` — the fingerprint `full` scope: `origin` excluded, polarity-opposite
  constraints (`origin` `"bound"`, `"require"`, or `"discourage"`) canonicalized
  to their baseline-polarity form (D-29(4)/D-38/D-39), default/tags/meta kept,
  both hard and declared constraints kept.
- `"sampling"` — the fingerprint `sampling` scope: as `full` but declared
  (`hard=False`) constraints and per-param default/tags/meta dropped
  (API.md's scope table; DECISIONS.md D-33 additionally puts `quantized`/
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

from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any, Literal

from designspace.errors import SerializationError
from designspace.expr import Compare, Not
from designspace.identity._tags import _OPAQUE_MARKER as _OPAQUE_MARKER
from designspace.identity._tags import EncodeContext as EncodeContext
from designspace.identity._tags import OnUnserializable as OnUnserializable
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
    CodeDomain,
    Condition,
    Constraint,
    CustomDomain,
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
    SymbolicDomain,
    Weights,
)
from designspace.program import FloatLiteral, IntLiteral, Primitive, Signature

CustomTypeRegistry = Mapping[str, Any]  # type_key -> factory(describe_dict) -> ParamType

Scope = Literal["document", "full", "sampling"]

# `EncodeContext`/`OnUnserializable`/`_OPAQUE_MARKER` now live in
# identity/_tags.py (M10.8: `encode_expr` needs them too, and `_tags` is
# imported *by* this module, never the reverse) — re-imported here (not just
# re-exported) so every pre-existing `from designspace.identity._ir_codec
# import EncodeContext, ...` site keeps working verbatim.


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


def _encode_count(count: int | Any, ctx: EncodeContext, path: str) -> Any:
    if isinstance(count, int):
        return {"kind": "static", "n": count}
    site = f"param {path!r} repeat() count"
    return {"kind": "dynamic", "expr": encode_expr(count, ctx, site=site)}


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
    if kind == "custom":
        assert isinstance(domain, CustomDomain)
        return _encode_custom_domain(domain, ctx, path)
    if kind == "symbolic":
        assert isinstance(domain, SymbolicDomain)
        return _encode_symbolic_domain(domain, ctx, path)
    if kind == "code":
        assert isinstance(domain, CodeDomain)
        return _encode_code_domain(domain, ctx, path)
    if kind == "list":
        assert isinstance(domain, ListDomain)
        return _encode_list_domain(domain, scope, ctx, path)
    raise SerializationError(f"param {path!r}: unknown domain kind {kind!r}")


def _encode_custom_domain(domain: CustomDomain, ctx: EncodeContext, path: str) -> Any:
    """Custom params serialize as `type_key` + the `describe()` output
    (API.md, "to_json / from_json"). The `.custom(sampler, validator)`
    shorthand is in the enumerated non-serializable set (API.md:606) — it
    rides the same raise / mark (`{"$opaque": true}`) / drop-plus-manifest
    path as an external prior (`encode_prior`, above), since a whole custom
    param has no serializable substance without its type (DECISIONS.md
    D-47: "drop" degrades to the same opaque marker as "mark" here, rather
    than removing the whole param — a document produced this way is not
    meant to round-trip through `from_json`, "a different space by
    design")."""
    if domain.param_type is not None:
        pt = domain.param_type
        try:
            described = encode_default_value(pt.describe())
        except SerializationError as e:
            raise SerializationError(
                f"param {path!r}: custom type describe() output is not "
                f"JSON-serializable ({e}) (row 23)"
            ) from e
        return {"kind": "custom", "type_key": pt.type_key, "describe": described}
    if ctx.mode == "raise":
        raise SerializationError(
            f"param {path!r}: .custom(sampler, validator) shorthand has no "
            "structural encoding — pass on_unserializable='mark' or 'drop'"
        )
    if ctx.mode == "mark":
        return dict(_OPAQUE_MARKER)
    assert ctx.mode == "drop"
    ctx.dropped.append(f"param {path!r}: custom type (shorthand, opaque)")
    return dict(_OPAQUE_MARKER)


# -- SymbolicDomain / CodeDomain (M12) -------------------------------------
#
# Unlike a whole opaque custom, these two kinds are *mostly* structural —
# `signature`/`primitives`/`max_depth`/`description`/`constraints`/`examples`
# all serialize plainly. Only three fields are genuinely opaque
# (DECISIONS.md D-88, the enumerated non-serializable set: "`code`/
# `symbolic` validators, `symbolic` sampler, `Primitive.fn`"), and each
# rides raise/mark/drop *in place* rather than poisoning the whole domain —
# the same in-place-degradation precedent D-77 set for a `ds.value` site,
# generalized from "one opaque leaf inside an expression tree" to "one
# opaque field inside an otherwise-structural domain."


def _encode_opaque_field(ctx: EncodeContext, site: str) -> Any:
    if ctx.mode == "raise":
        raise SerializationError(
            f"{site} has no structural encoding — pass on_unserializable='mark' or 'drop'"
        )
    if ctx.mode == "mark":
        return dict(_OPAQUE_MARKER)
    assert ctx.mode == "drop"
    ctx.dropped.append(f"{site} (opaque)")
    return dict(_OPAQUE_MARKER)


def _decode_opaque_field(tree: Any, key: str, site: str) -> None:
    if key in tree:
        raise SerializationError(
            f"{site}: cannot reconstruct from a mark-sentinel document — "
            "from_json only round-trips fully serializable spaces"
        )


def _encode_signature(signature: Signature) -> Any:
    return {"args": [[name, t] for name, t in signature.args.items()], "returns": signature.returns}


def _decode_signature(tree: Any) -> Signature:
    return Signature(dict(tree["args"]), tree["returns"])


def _encode_program_primitive(
    prim: str | Primitive | FloatLiteral | IntLiteral, ctx: EncodeContext, path: str
) -> Any:
    if isinstance(prim, str):
        return {"kind": "name", "name": prim}
    if isinstance(prim, Primitive):
        lo, hi = prim.arity_range
        tree: dict[str, Any] = {
            "kind": "primitive",
            "name": prim.name,
            "arity": {"lo": lo, "hi": hi},
        }
        if prim.fn is not None:
            tree["fn"] = _encode_opaque_field(
                ctx, f"param {path!r}: symbolic() primitive {prim.name!r} fn"
            )
        return tree
    if isinstance(prim, FloatLiteral):
        return {"kind": "float_literal", "lo": prim.lo, "hi": prim.hi}
    assert isinstance(prim, IntLiteral)
    return {"kind": "int_literal", "lo": prim.lo, "hi": prim.hi}


def _decode_program_primitive(tree: Any, path: str) -> str | Primitive | FloatLiteral | IntLiteral:
    kind = tree["kind"]
    if kind == "name":
        return str(tree["name"])
    if kind == "primitive":
        _decode_opaque_field(tree, "fn", f"param {path!r}: symbolic() primitive fn")
        arity = tree["arity"]
        return Primitive(name=tree["name"], arity=(arity["lo"], arity["hi"]))
    if kind == "float_literal":
        return FloatLiteral(float(tree["lo"]), float(tree["hi"]))
    if kind == "int_literal":
        return IntLiteral(int(tree["lo"]), int(tree["hi"]))
    raise SerializationError(f"param {path!r}: unknown symbolic() primitive kind {kind!r}")


def _encode_symbolic_domain(domain: SymbolicDomain, ctx: EncodeContext, path: str) -> Any:
    tree: dict[str, Any] = {
        "kind": "symbolic",
        "signature": _encode_signature(domain.signature),
        "primitives": [_encode_program_primitive(p, ctx, path) for p in domain.primitives],
        "max_depth": domain.max_depth,
    }
    if domain.validators is not None:
        tree["validators"] = _encode_opaque_field(ctx, f"param {path!r}: symbolic() validators")
    if domain.sampler is not None:
        tree["sampler"] = _encode_opaque_field(ctx, f"param {path!r}: symbolic() sampler")
    return tree


def _decode_symbolic_domain(tree: Any, path: str) -> SymbolicDomain:
    _decode_opaque_field(tree, "validators", f"param {path!r}: symbolic() validators")
    _decode_opaque_field(tree, "sampler", f"param {path!r}: symbolic() sampler")
    return SymbolicDomain(
        signature=_decode_signature(tree["signature"]),
        primitives=tuple(_decode_program_primitive(p, path) for p in tree["primitives"]),
        max_depth=tree["max_depth"],
    )


def _encode_code_domain(domain: CodeDomain, ctx: EncodeContext, path: str) -> Any:
    tree: dict[str, Any] = {
        "kind": "code",
        "signature": _encode_signature(domain.signature),
        "description": domain.description,
    }
    if domain.constraints is not None:
        tree["constraints"] = list(domain.constraints)
    if domain.examples is not None:
        tree["examples"] = [encode_default_value(e) for e in domain.examples]
    if domain.validators is not None:
        tree["validators"] = _encode_opaque_field(ctx, f"param {path!r}: code() validators")
    return tree


def _decode_code_domain(tree: Any, path: str) -> CodeDomain:
    _decode_opaque_field(tree, "validators", f"param {path!r}: code() validators")
    constraints = tuple(tree["constraints"]) if "constraints" in tree else None
    examples = (
        tuple(decode_default_value(e) for e in tree["examples"]) if "examples" in tree else None
    )
    return CodeDomain(
        signature=_decode_signature(tree["signature"]),
        description=tree["description"],
        constraints=constraints,
        examples=examples,
    )


def _encode_list_domain(domain: ListDomain, scope: Scope, ctx: EncodeContext, path: str) -> Any:
    tree: dict[str, Any] = {
        "kind": "list",
        "element_kind": domain.element_kind,
        "element_domain": encode_domain(
            domain.element_kind, domain.element_domain, scope, ctx, path
        ),
        "element_periodic": domain.element_periodic,
        "count": _encode_count(domain.count, ctx, path),
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
        for i, c in enumerate(domain.element_constraints)
        if (
            encoded := encode_constraint(
                c, scope, ctx, site=f"param {path!r} element constraint {i}"
            )
        )
        is not None
    ]
    if encoded_constraints:
        tree["element_constraints"] = encoded_constraints
    return tree


def decode_domain(
    kind: str, tree: Any, path: str, custom_types: CustomTypeRegistry | None = None
) -> Domain:
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
    if kind == "custom":
        return _decode_custom_domain(tree, path, custom_types)
    if kind == "symbolic":
        return _decode_symbolic_domain(tree, path)
    if kind == "code":
        return _decode_code_domain(tree, path)
    if kind == "list":
        return _decode_list_domain(tree, path, custom_types)
    raise SerializationError(f"param {path!r}: unknown domain kind {kind!r}")


def _decode_custom_domain(
    tree: Any, path: str, custom_types: CustomTypeRegistry | None
) -> CustomDomain:
    if tree.get("kind") == "opaque":
        raise SerializationError(
            f"param {path!r}: cannot reconstruct a custom param from a "
            "mark-sentinel document (the .custom(sampler, validator) "
            "shorthand is not serializable) — from_json only round-trips "
            "fully serializable spaces"
        )
    type_key = tree["type_key"]
    if custom_types is None or type_key not in custom_types:
        raise SerializationError(
            f"from_json: param {path!r} has type_key {type_key!r}, which has "
            "no entry in custom_types (row 27)"
        )
    factory = custom_types[type_key]
    described = decode_default_value(tree["describe"])
    return CustomDomain(param_type=factory(described))


def _decode_list_domain(
    tree: Any, path: str, custom_types: CustomTypeRegistry | None = None
) -> ListDomain:
    element_kind = tree["element_kind"]
    element_default = (
        decode_default_value(tree["element_default"]) if "element_default" in tree else None
    )
    list_default = decode_default_value(tree["list_default"]) if "list_default" in tree else None
    return ListDomain(
        element_kind=element_kind,
        element_domain=decode_domain(element_kind, tree["element_domain"], path, custom_types),
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


def _canonicalize_polarity(c: Constraint) -> Constraint:
    """D-29(4)/D-38/D-39: normalize a constraint's stored predicate to its
    baseline polarity before hashing, so `origin` (excluded from the preimage)
    is never semantics-load-bearing. A verb that stores the polarity-opposite
    predicate from its `origin="user"` sibling — `require` vs `forbid`,
    `discourage` vs `encourage` — or a `bound` sugar is negated back:

    - `origin="bound"` (M5) is always a single top-level
      `Compare(op, ParamExpr(target), other)` (resolve/_bounds.py
      `_bound_constraint`), so its negation is an **operator flip**
      (`x <= y` → `x > y`) — byte-identical to a user `.forbid(x > y)`.
      Element-level constraints are never bound-origin (repeat-element bound
      expressions aren't supported yet, D-29).
    - `origin="require"` (M7.5) and `origin="discourage"` (M7.6) store an
      arbitrary `BoolExpr`, so the negation is a **whole-expression** `Not(...)`.
      `require(e)` is thus fingerprint-equal to `.forbid(~e)`, and
      `discourage(e)` to `.encourage(~e)`. (D-38: `require(x<=y)` is *not*
      fingerprint-equal to the operator-flipped `.forbid(x>y)`, even though both
      name the same feasible set — a semantic equivalence, not a syntactic one.
      "Equal fingerprints ⇒ equal feasible sets" is one-way, so distinct
      fingerprints for identical feasibility are allowed.)

    Without this, `discourage(e)` and `encourage(e)` — same `(expr, hard)`, only
    `origin` differing, opposite polarity — would share a preimage, making the
    excluded `origin` load-bearing.
    """
    if c.origin == "bound":
        expr = c.expr
        assert isinstance(expr, Compare)
        flip = {"le": "gt", "ge": "lt"}
        assert expr.op in flip, f"unexpected bound-origin comparison op {expr.op!r}"
        return replace(c, expr=Compare(flip[expr.op], expr.left, expr.right))
    if c.origin in ("require", "discourage"):
        return replace(c, expr=Not(c.expr))
    return c


def encode_constraint(c: Constraint, scope: Scope, ctx: EncodeContext, *, site: str) -> Any:
    """Returns `None` when `c` is excluded at this scope (a declared/soft
    constraint at `sampling`). `site` (M10.8) names this constraint for a
    `ds.value` opacity error/manifest entry — caller-supplied since a
    `Constraint` carries no name/path of its own, only a position in
    `space.constraints`/`ListDomain.element_constraints`."""
    if scope == "sampling" and not c.hard:
        return None
    expr = c.expr if scope == "document" else _canonicalize_polarity(c).expr
    tree: dict[str, Any] = {"expr": encode_expr(expr, ctx, site=site), "hard": c.hard}
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


def encode_condition(cond: Condition, ctx: EncodeContext) -> Any:
    site = f"param {cond.target!r} condition"
    return {"target": cond.target, "expr": encode_expr(cond.expr, ctx, site=site)}


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
        tree["condition"] = encode_expr(pd.condition, ctx, site=f"param {pd.path!r} condition")
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


# -- Space-level anchors / meta (M8) --------------------------------------
#
# Both are `Mapping[str, Any]` keyed by an untagged string (an anchor name;
# a meta key) whose *value* is `Any`-typed application data — tagged
# recursively via the same generic codec `default`/`ParamDef.meta`/
# `Constraint.meta` use (normalization step 5). Keys sort (step 3). Omitted
# entirely when empty, never emitted as `{}` (identity/_ir_codec.py's
# module docstring: an anchor/meta-free space's preimage must be
# byte-identical to a pre-M8 one).


def encode_anchors(anchors: Any) -> Any:
    if not anchors:
        return None
    return {name: encode_default_value(config) for name, config in sorted(anchors.items())}


def decode_anchors(tree: Any) -> MappingProxyType[str, Any]:
    if tree is None:
        return MappingProxyType({})
    return MappingProxyType({name: decode_default_value(cfg) for name, cfg in tree.items()})


def encode_space_meta(meta: Any) -> Any:
    if not meta:
        return None
    return {k: encode_default_value(v) for k, v in sorted(meta.items())}


def decode_space_meta(tree: Any) -> MappingProxyType[str, Any]:
    if tree is None:
        return MappingProxyType({})
    return MappingProxyType({k: decode_default_value(v) for k, v in tree.items()})


def decode_param(tree: Any, custom_types: CustomTypeRegistry | None = None) -> ParamDef:
    path = tree["path"]
    kind = tree["kind"]
    default = decode_default_value(tree["default"]) if "default" in tree else None
    tags = frozenset(tree.get("tags", ()))
    meta = MappingProxyType({k: decode_default_value(v) for k, v in tree.get("meta", {}).items()})
    condition = decode_bool_expr(tree["condition"]) if "condition" in tree else None
    return ParamDef(
        path=path,
        type_kind=kind,
        domain=decode_domain(kind, tree["domain"], path, custom_types),
        prior=decode_prior(tree.get("prior")),
        periodic=tree["periodic"],
        default=default,
        condition=condition,
        tags=tags,
        meta=meta,
        chart=None,  # rebuilt by the caller (serialize/_fromjson.py)
        quantized=decode_quantized(tree.get("quantized")),
    )
