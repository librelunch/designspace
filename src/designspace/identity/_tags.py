"""Type tags for `Any`-typed leaf data, and the expression-AST codec.

See API.md, "Identity and Serialization" > "Normalization pipeline", steps 4
through 6.

Every position holding application data of otherwise-unknown type, such as a
categorical or ordinal declared value, a default or a literal expression
operand, is wrapped as `{"$t": "int"|"float"|"str"|"bool"|"null", "v": ...}`.
That is what makes `categorical(1, 2)` differ from `categorical(1.0, 2.0)`
across JSON's native int/float blurring, RFC 8785 canonicalizing `1.0` to
`1`. Positions that are never `Any`-typed, such as a `RealDomain` bound, a
`type_kind` string or an `ArithOp.op`, are encoded as bare JSON values.
Tuples preserve order; frozensets and mappings sort.

Shared by `identity/_fingerprint.py`, `serialize/_tojson.py` and
`serialize/_fromjson.py`. One codec means the two documents can never drift
on how a leaf value or an expression node is spelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any
from typing import Literal as TypingLiteral

from designspace.builder._paramexpr import ParamExpr
from designspace.errors import SerializationError
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

TAG_KEY = "$t"
VAL_KEY = "v"

_TAG_NULL = "null"
_TAG_BOOL = "bool"
_TAG_INT = "int"
_TAG_FLOAT = "float"
_TAG_STR = "str"

# -- Non-serializable-site handling --------------------------------------
#
# `ds.value`'s `fn` is a non-serializable site inside an expression tree,
# where an external Prior and the `.custom` shorthand are whole-domain sites.
# `encode_expr` therefore needs this context, and `_ir_codec` imports from
# `_tags` rather than the reverse, so the shared type lives on this side of
# that edge. It is re-exported from `_ir_codec`, so an import of
# `EncodeContext` or `OnUnserializable` from that module keeps working.

OnUnserializable = TypingLiteral["raise", "mark", "drop"]
"""What `to_json` does when the space holds something it cannot serialize.

`"raise"` is the default and fails loudly, naming every offending site by
definition path, since silence here loses meaning. `"mark"` substitutes the
`{"$opaque": true}` sentinel *in place*, so the site's presence still
counts toward identity. `"drop"` writes the document without those sites
plus a manifest of what was omitted; the space it reconstructs is a
different space by design.

`Space.fingerprint` accepts only the first two; see
`FingerprintUnserializable`.
"""

_OPAQUE_MARKER = {"kind": "opaque", "$opaque": True}


@dataclass
class EncodeContext:
    """The context threaded through every encoder that may hit an opaque site.

    The spec enumerates six non-serializable sites. An external `Prior` and
    the `.custom(sampler, validator)` shorthand are whole-domain sites, met
    by `encode_domain` and `encode_prior`. `ds.value`'s `fn` is met by
    `encode_expr`. The `code` and `symbolic` `validators`, the `symbolic`
    `sampler` and `Primitive.fn` are each opaque per field rather than
    poisoning the whole domain, and are met by `_encode_symbolic_domain` and
    `_encode_code_domain` in `identity/_ir_codec.py`.
    """

    mode: OnUnserializable
    dropped: list[str] = field(default_factory=list)


def _tag_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        raise SerializationError(
            f"cannot serialize non-finite float {value!r} "
            "(NaN and Inf are resolution errors wherever floats occur in the "
            "IR, so this value should never have reached serialization)"
        )
    return 0.0 if value == 0.0 else value  # step 4: -0.0 -> 0.0


def tag_value(value: Any) -> dict[str, Any]:
    """Wrap a scalar `Any`-typed value with its type tag (step 5)."""
    if value is None:
        return {TAG_KEY: _TAG_NULL, VAL_KEY: None}
    if isinstance(value, bool):  # must precede the int check (bool <: int)
        return {TAG_KEY: _TAG_BOOL, VAL_KEY: value}
    if isinstance(value, int):
        return {TAG_KEY: _TAG_INT, VAL_KEY: value}
    if isinstance(value, float):
        return {TAG_KEY: _TAG_FLOAT, VAL_KEY: _tag_float(value)}
    if isinstance(value, str):
        return {TAG_KEY: _TAG_STR, VAL_KEY: value}
    raise SerializationError(
        f"cannot type-tag value {value!r} of unsupported type {type(value).__name__}"
    )


def untag_value(tree: dict[str, Any]) -> Any:
    tag = tree[TAG_KEY]
    value = tree[VAL_KEY]
    if tag == _TAG_NULL:
        return None
    if tag in (_TAG_BOOL, _TAG_INT, _TAG_STR):
        return value
    if tag == _TAG_FLOAT:
        return float(value)
    raise SerializationError(f"unknown type tag {tag!r}")


def sort_key(tagged: dict[str, Any]) -> tuple[str, str]:
    """A deterministic total order over tagged values.

    Used to canonicalize otherwise-unordered collections, such as a
    `SumOver` mapping's keys or a config's subset value. The order is stable
    and total rather than natural.
    """
    return (tagged[TAG_KEY], repr(tagged[VAL_KEY]))


def encode_default_value(value: Any) -> Any:
    """Encode a default value generically, tagging every scalar leaf.

    This covers `ParamDef.default`, `ListDomain.element_default` and
    `list_default`. A domain's own declared values have their leaf type
    fixed by the param's `type_kind`, so real, integer and bool stay
    untagged there. A default's shape is known only by walking it: a lift's
    `list_default` is "a literal phenotype value per index", of any element
    shape, whether scalar, struct, choice or nested list, as `_fill_list` in
    `defaults/_defaults.py` treats it. A struct-element default is therefore
    a plain dict and a choice-element default a bare string or single-key
    dict, exactly like an ordinary config value.

    Rather than thread the enclosing `Space` through the domain codec to
    resolve struct-field types, as `identity/_config_encode.py` does for
    actual configs, this walks the value generically and tags every scalar
    leaf, real, integer and bool included, which the domain and config
    codecs leave bare. The simplification costs nothing: dict key order is
    JCS's job, object keys being canonicalized on serialization whatever
    this tree's own key order, so no `Space`-driven declaration-order lookup
    is needed.

    A dict key of exactly `"$t"` would be misread as a tagged-scalar marker
    on decode. For a struct- or choice-shaped `default` this is an accepted
    gap: the path grammar does not reserve `$`, no corpus fixture or spec
    example uses it as a struct field name, and the tagged-value
    micro-format already reserves `$`-prefixed keys elsewhere, as with
    `$opaque`. For `meta`, which shares this codec, the same collision is
    rejected outright: `check_meta_json_serializable` in
    `builder/_names.py` refuses any `"$"`-prefixed meta key at construction.
    Meta keys are unconstrained user input, unlike a default's struct field
    names, which are limited to declared struct fields, so a collision there
    is a real `KeyError` on `from_json` rather than a hypothetical one.
    """
    if isinstance(value, dict):
        return {k: encode_default_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode_default_value(v) for v in value]
    return tag_value(value)


def decode_default_value(tree: Any) -> Any:
    if isinstance(tree, dict):
        if TAG_KEY in tree:
            return untag_value(tree)
        return {k: decode_default_value(v) for k, v in tree.items()}
    if isinstance(tree, list):
        return [decode_default_value(v) for v in tree]
    raise SerializationError(f"malformed default-value tree: {tree!r}")


# -- Expression AST codec -----------------------------------------------
#
# One node per `expr/_ast.py` class, plus `ParamExpr`, the "ref" leaf that
# appears inside resolved `Condition` and `Constraint` expression trees.
# Encoding always emits `{"kind": node.kind, ...}`, the spec's stated
# preimage shape of "node kind, children in operand order". Decoding
# dispatches on "kind" alone, a single node kind never appearing in two
# structurally different shapes, through one universal `decode_expr`.
# Several operand slots are typed as the generic `Expr`, namely
# `IsActive.operand` and every `VectorExpr` aggregate's `operand`, and so
# cannot be decoded through a narrower, statically typed entry point.
#
# `Literal` and `BoolLiteral` collide, both reporting
# `.kind == "literal"`. They are disambiguated by which key carries the
# payload rather than by kind: `"value"`, tagged, for `Literal`, and
# `"bool"`, bare because `BoolLiteral.value` is always exactly `bool` and
# never `Any`-typed, for `BoolLiteral`.


def _enc_children(children: tuple[Expr, ...], ctx: EncodeContext | None, site: str) -> list[Any]:
    return [encode_expr(c, ctx, site=site) for c in children]


def encode_expr(
    node: Expr, ctx: EncodeContext | None = None, *, site: str = "expression"
) -> dict[str, Any]:
    """Encode an expression tree to its canonical form.

    `ctx` and `site` serve the one opaque leaf, `Value` below. Every other
    node is fully structural and ignores them, so a caller passing neither,
    such as `builder/_space.py`'s structural-equality check, is unaffected.

    `ctx=None` behaves as `"raise"`, the safe default `on_unserializable`
    has everywhere else, so a caller that threads no context still fails
    loudly on an opaque node rather than silently.

    `site` is a pre-formatted description of where the expression tree came
    from, such as `"constraint 3"` or `"param 'x' condition"`, prefixed onto
    the opaque leaf's message. It does not vary with tree depth: the message
    needs to name a site an author would recognize, not the exact node.
    """
    if isinstance(node, ParamExpr):  # ref leaf; check before Literal/BoolLiteral
        # (ParamExpr is not one of those, but check first defensively since
        # it is also an ArithExpr/BoolExpr and could shadow a future subclass)
        return {"kind": "ref", "path": node.path}
    if isinstance(node, BoolLiteral):
        return {"kind": "literal", "bool": node.value}
    if isinstance(node, Literal):
        # `encode_default_value` rather than the scalar-only `tag_value`.
        # Every prior literal is scalar, so the two agree byte for byte on
        # those, but this also supports a custom param's phenotype value, a
        # JSON-shaped nested dict or list such as a `.freeze()` pin's
        # embedded literal, without a dedicated codec.
        return {"kind": "literal", "value": encode_default_value(node.value)}
    if isinstance(node, ArithOp | Compare | BoolOp):
        return {"kind": node.kind, "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, Not):
        return {"kind": "not", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, Implies):
        return {"kind": "implies", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, IsIn):
        return {
            "kind": "is_in",
            "children": _enc_children(node.children, ctx, site),
            "values": [tag_value(v) for v in node.values],
        }
    if isinstance(node, IsActive):
        return {"kind": "is_active", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, Count):
        return {"kind": "count", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, IfInactive):
        return {"kind": "if_inactive", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, Contains):
        return {
            "kind": "contains",
            "children": _enc_children(node.children, ctx, site),
            "item": tag_value(node.item),
        }
    if isinstance(node, Size):
        return {"kind": "size", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, SumOver):
        pairs = [(tag_value(k), tag_value(v)) for k, v in node.mapping.items()]
        pairs.sort(key=lambda kv: sort_key(kv[0]))  # step 3: unordered (Mapping) sorts
        return {
            "kind": "sum_over",
            "children": _enc_children(node.children, ctx, site),
            "mapping": [[k, v] for k, v in pairs],
        }
    if isinstance(node, PositionOf):
        return {
            "kind": "position_of",
            "children": _enc_children(node.children, ctx, site),
            "item": tag_value(node.item),
        }
    if isinstance(node, Length):
        return {"kind": "length", "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, Prop):
        return {
            "kind": "prop",
            "children": _enc_children(node.children, ctx, site),
            "name": node.name,
        }
    if isinstance(node, Value):
        # The one opaque expression leaf (API.md, "Identity and
        # Serialization": `ds.value`'s `fn` joins the non-serializable set).
        # A leaf marker only; operands are never encoded, matching how
        # `_encode_custom_domain` erases a whole opaque domain rather than
        # partially encoding it.
        mode = "raise" if ctx is None else ctx.mode
        if mode == "raise":
            raise SerializationError(
                f"{site}: ds.value()'s fn has no structural encoding, being "
                "opaque under API.md's non-serializable set; pass "
                "on_unserializable='mark' or 'drop'"
            )
        if mode == "mark":
            return dict(_OPAQUE_MARKER)
        assert mode == "drop" and ctx is not None
        ctx.dropped.append(f"{site}: ds.value fn (opaque)")
        return dict(_OPAQUE_MARKER)
    if isinstance(node, ChartApply):
        # Opaque-free, unlike `Value` above. `chart_apply`'s `fn` is always
        # `chart.from_unit`, a pure function of `type_kind`, `domain`,
        # `prior`, `quantized` and `periodic`, the declaration facts
        # `encode_param` already encodes for an ordinary `ParamDef`. Those
        # are reused here through a function-local import of
        # `identity/_ir_codec.py`; a module-level one would cycle, since
        # `_ir_codec` imports `_tags` for `encode_expr` itself.
        #
        # `scope="document"` is fixed rather than threaded through. Real and
        # integer domain encoding, the only two kinds a chart-bearing param
        # ever has, never branches on scope; only `list` and `custom`
        # domains do. Any literal scope is therefore equivalent here. An
        # external `Prior` still rides the raise, mark and drop path in
        # `encode_prior`, keyed off the same `ctx`.
        from designspace.identity._ir_codec import (
            encode_domain,
            encode_prior,
            encode_quantized,
        )

        effective_ctx = ctx if ctx is not None else EncodeContext(mode="raise")
        tree: dict[str, Any] = {
            "kind": "chart_apply",
            "children": _enc_children(node.children, ctx, site),
            "type_kind": node.type_kind,
            "domain": encode_domain(node.type_kind, node.domain, "document", effective_ctx, site),
            "periodic": node.periodic,
        }
        prior_tree = encode_prior(site, node.prior, effective_ctx)
        if prior_tree is not None:
            tree["prior"] = prior_tree
        quantized_tree = encode_quantized(node.quantized)
        if quantized_tree is not None:
            tree["quantized"] = quantized_tree
        return tree
    if isinstance(node, Field):
        return {
            "kind": "field",
            "children": _enc_children(node.children, ctx, site),
            "name": node.name,
        }
    if isinstance(node, Sum | Min | Max):
        return {"kind": node.kind, "children": _enc_children(node.children, ctx, site)}
    if isinstance(node, CountOf):
        return {
            "kind": "count_of",
            "children": _enc_children(node.children, ctx, site),
            "values": [tag_value(v) for v in node.values],
        }
    if isinstance(node, IsSorted):
        return {
            "kind": "is_sorted",
            "children": _enc_children(node.children, ctx, site),
            "descending": node.descending,
        }
    if isinstance(node, Distinct):
        return {
            "kind": "distinct",
            "children": _enc_children(node.children, ctx, site),
            "fields": list(node.fields),
        }
    raise SerializationError(f"no expression codec for node type {type(node).__name__}")


_ARITH_OPS = frozenset({"add", "sub", "mul", "div", "pow", "mod"})
_COMPARE_OPS = frozenset({"eq", "ne", "gt", "lt", "ge", "le"})
_BOOL_OPS = frozenset({"and", "or"})


def decode_expr(tree: dict[str, Any]) -> Expr:
    kind = tree["kind"]
    if kind == "ref":
        return ParamExpr(path=tree["path"])
    if kind == "literal":
        if "bool" in tree:
            return BoolLiteral(tree["bool"])
        return Literal(decode_default_value(tree["value"]))
    if kind == "opaque":
        raise SerializationError(
            "cannot reconstruct a ds.value() node from a mark-sentinel "
            "document (its fn is opaque); from_json only round-trips "
            "fully serializable spaces"
        )
    children = [decode_expr(c) for c in tree.get("children", ())]
    if kind in _ARITH_OPS:
        left, right = children
        assert isinstance(left, ArithExpr) and isinstance(right, ArithExpr)
        return ArithOp(kind, left, right)
    if kind in _COMPARE_OPS:
        left, right = children
        assert isinstance(left, ArithExpr) and isinstance(right, ArithExpr)
        return Compare(kind, left, right)
    if kind in _BOOL_OPS:
        left, right = children
        assert isinstance(left, BoolExpr) and isinstance(right, BoolExpr)
        return BoolOp(kind, left, right)
    if kind == "not":
        (operand,) = children
        assert isinstance(operand, BoolExpr)
        return Not(operand)
    if kind == "implies":
        left, right = children
        assert isinstance(left, BoolExpr) and isinstance(right, BoolExpr)
        return Implies(left, right)
    if kind == "is_in":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return IsIn(operand, tuple(untag_value(v) for v in tree["values"]))
    if kind == "is_active":
        (operand,) = children
        return IsActive(operand)
    if kind == "count":
        assert all(isinstance(c, BoolExpr) for c in children)
        return Count(tuple(children))  # type: ignore[arg-type]
    if kind == "if_inactive":
        operand, fallback = children
        assert isinstance(operand, ArithExpr) and isinstance(fallback, ArithExpr)
        return IfInactive(operand, fallback)
    if kind == "contains":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return Contains(operand, untag_value(tree["item"]))
    if kind == "size":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return Size(operand)
    if kind == "sum_over":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        mapping = {untag_value(k): untag_value(v) for k, v in tree["mapping"]}
        return SumOver(operand, mapping)
    if kind == "position_of":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return PositionOf(operand, untag_value(tree["item"]))
    if kind == "length":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return Length(operand)
    if kind == "prop":
        (operand,) = children
        assert isinstance(operand, ArithExpr)
        return Prop(operand, tree["name"])
    if kind == "field":
        (operand,) = children
        return Field(operand, tree["name"])
    if kind == "sum":
        (operand,) = children
        return Sum(operand)
    if kind == "min":
        (operand,) = children
        return Min(operand)
    if kind == "max":
        (operand,) = children
        return Max(operand)
    if kind == "count_of":
        (operand,) = children
        return CountOf(operand, tuple(untag_value(v) for v in tree["values"]))
    if kind == "is_sorted":
        (operand,) = children
        return IsSorted(operand, tree["descending"])
    if kind == "distinct":
        (operand,) = children
        return Distinct(operand, tuple(tree["fields"]))
    if kind == "chart_apply":
        (operand,) = children
        from designspace.charts import build_chart
        from designspace.identity._ir_codec import decode_domain, decode_prior, decode_quantized

        type_kind = tree["type_kind"]
        domain = decode_domain(type_kind, tree["domain"], "<chart_apply>")
        prior = decode_prior(tree.get("prior"))
        quantized = decode_quantized(tree.get("quantized"))
        # Rebuilt fresh and never trusted from input, under the same
        # "charts are always derived" rule `resolve.rebuild_charts` applies
        # to `ParamDef.chart`. The source facts just decoded were valid once
        # already, the original param having resolved successfully, so this
        # cannot raise.
        chart = build_chart("<chart_apply>", type_kind, domain, prior, quantized)
        assert chart is not None  # type_kind is always "real"/"integer" here
        return ChartApply(
            operand=operand,
            chart=chart,
            type_kind=type_kind,
            domain=domain,
            prior=prior,
            quantized=quantized,
            periodic=tree["periodic"],
        )
    raise SerializationError(f"unknown expression node kind {kind!r}")


def decode_bool_expr(tree: dict[str, Any]) -> BoolExpr:
    node = decode_expr(tree)
    assert isinstance(node, BoolExpr)
    return node


def decode_arith_expr(tree: dict[str, Any]) -> ArithExpr:
    node = decode_expr(tree)
    assert isinstance(node, ArithExpr)
    return node
