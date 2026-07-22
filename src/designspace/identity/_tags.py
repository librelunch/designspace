"""Type tags for `Any`-typed leaf data, and the expression-AST codec
(API_v3.md, "Identity and Serialization" > "Normalization pipeline", steps
4-6).

Every position that holds application data of otherwise-unknown type (a
categorical/ordinal declared value, a default, a literal expression operand,
...) is wrapped `{"$t": "int"|"float"|"str"|"bool"|"null", "v": ...}` so that
`categorical(1, 2) != categorical(1.0, 2.0)` and friends survive JSON's
native int/float blurring (RFC 8785 canonicalizes `1.0` to `1`). Positions
that are never `Any`-typed (a `RealDomain` bound, a `type_kind` string, an
`ArithOp.op`) are encoded as bare JSON values instead — see DECISIONS.md D-34
for the exact boundary and the tuple-preserves-order / frozenset-and-mapping-
sort rule that goes with it.

Shared by `identity/_fingerprint.py` and `serialize/_tojson.py` /
`serialize/_fromjson.py` — one codec, so the two documents can never drift
on how a leaf value or an expression node is spelled.
"""

from __future__ import annotations

import math
from typing import Any

from designspace.build._paramexpr import ParamExpr
from designspace.errors import SerializationError
from designspace.expr import (
    ArithExpr,
    ArithOp,
    BoolExpr,
    BoolLiteral,
    BoolOp,
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
)

TAG_KEY = "$t"
VAL_KEY = "v"

_TAG_NULL = "null"
_TAG_BOOL = "bool"
_TAG_INT = "int"
_TAG_FLOAT = "float"
_TAG_STR = "str"


def _tag_float(value: float) -> float:
    if math.isnan(value) or math.isinf(value):
        raise SerializationError(
            f"cannot serialize non-finite float {value!r} "
            "(NaN/Inf are resolution errors wherever floats occur in the IR — "
            "this indicates a value that should never have reached serialization)"
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
    """A deterministic total order over tagged values, for canonicalizing
    otherwise-unordered collections (a `SumOver` mapping's keys; a config's
    subset value). Not a "natural" order — just stable and total."""
    return (tagged[TAG_KEY], repr(tagged[VAL_KEY]))


def encode_default_value(value: Any) -> Any:
    """A `ParamDef.default` / `ListDomain.element_default` / `list_default`
    value, generically. Unlike a domain's own declared values (where the
    param's `type_kind` already fixes the leaf type, so real/integer/bool
    stay untagged — DECISIONS.md D-34), a default's shape is only known by
    walking it: a lift's `list_default` is "a literal phenotype value per
    index — any element shape: scalar, struct, choice, nested list"
    (`defaults/_defaults.py::_fill_list`), so a struct-element default is a
    plain dict and a choice-element default is a bare string or a
    single-key dict, exactly like an ordinary config value. Rather than
    thread the enclosing `Space` through the domain codec to resolve
    struct-field types the way `identity/_config_encode.py` does for actual
    configs, this walks the value generically and tags every scalar leaf
    uniformly (including real/integer/bool, which the domain/config codecs
    otherwise leave bare) — a deliberate, documented simplification: dict
    key order is JCS's job (object keys are canonicalized on serialization
    regardless of this tree's own key order), so no `Space`-driven
    declaration-order lookup is needed either.

    A dict key of exactly `"$t"` would be misread as a tagged-scalar marker
    on decode. For a struct/choice-shaped `default`, this is an accepted,
    undocumented gap: the path grammar doesn't reserve `$`, but no corpus
    fixture or spec example uses it as a struct field name, and the
    tagged-value micro-format already reserves `$`-prefixed keys elsewhere
    (`$opaque`). For `meta` (which shares this codec, DECISIONS.md D-36),
    the same collision is *not* merely accepted — `build/_names.py
    ::check_meta_json_serializable` rejects any `"$"`-prefixed meta key at
    construction, because meta keys are unconstrained user input (unlike a
    default's struct field names, which are already limited to declared
    struct fields) and a collision there is a real `KeyError` on `from_json`,
    not a hypothetical one.
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
# One node per `expr/_ast.py` class (+ `ParamExpr`, the "ref" leaf that
# appears inside resolved `Condition`/`Constraint` expression trees). Encode
# always emits `{"kind": node.kind, ...}` per the spec's stated preimage
# shape ("node kind, children in operand order..."); decode dispatches
# purely on "kind" (a single node kind never appears in two structurally
# different shapes) via one universal `decode_expr`, since several operand
# slots are typed as the generic `Expr` (`IsActive.operand`, and every
# `VectorExpr` aggregate's `operand`) and so cannot be decoded through a
# narrower, statically-typed entry point.
#
# One genuine collision: `Literal` and `BoolLiteral` both report
# `.kind == "literal"`. They are disambiguated by which key carries the
# payload — `"value"` (tagged) for `Literal`, `"bool"` (bare, since
# `BoolLiteral.value` is always exactly `bool`, never `Any`-typed) for
# `BoolLiteral` — rather than by kind alone.


def _enc_children(children: tuple[Expr, ...]) -> list[Any]:
    return [encode_expr(c) for c in children]


def encode_expr(node: Expr) -> dict[str, Any]:
    if isinstance(node, ParamExpr):  # ref leaf; check before Literal/BoolLiteral
        # (ParamExpr is not one of those, but check first defensively since
        # it is also an ArithExpr/BoolExpr and could shadow a future subclass)
        return {"kind": "ref", "path": node.path}
    if isinstance(node, BoolLiteral):
        return {"kind": "literal", "bool": node.value}
    if isinstance(node, Literal):
        # `encode_default_value`, not the scalar-only `tag_value`: every
        # prior literal is scalar, so this is byte-identical for them, but
        # it also supports a custom param's phenotype value (a JSON-shaped
        # nested dict/list, e.g. a `.freeze()` pin's embedded literal —
        # DECISIONS.md D-47) without a dedicated codec.
        return {"kind": "literal", "value": encode_default_value(node.value)}
    if isinstance(node, ArithOp | Compare | BoolOp):
        return {"kind": node.kind, "children": _enc_children(node.children)}
    if isinstance(node, Not):
        return {"kind": "not", "children": _enc_children(node.children)}
    if isinstance(node, Implies):
        return {"kind": "implies", "children": _enc_children(node.children)}
    if isinstance(node, IsIn):
        return {
            "kind": "is_in",
            "children": _enc_children(node.children),
            "values": [tag_value(v) for v in node.values],
        }
    if isinstance(node, IsActive):
        return {"kind": "is_active", "children": _enc_children(node.children)}
    if isinstance(node, Count):
        return {"kind": "count", "children": _enc_children(node.children)}
    if isinstance(node, IfInactive):
        return {"kind": "if_inactive", "children": _enc_children(node.children)}
    if isinstance(node, Contains):
        return {
            "kind": "contains",
            "children": _enc_children(node.children),
            "item": tag_value(node.item),
        }
    if isinstance(node, Size):
        return {"kind": "size", "children": _enc_children(node.children)}
    if isinstance(node, SumOver):
        pairs = [(tag_value(k), tag_value(v)) for k, v in node.mapping.items()]
        pairs.sort(key=lambda kv: sort_key(kv[0]))  # step 3: unordered (Mapping) sorts
        return {
            "kind": "sum_over",
            "children": _enc_children(node.children),
            "mapping": [[k, v] for k, v in pairs],
        }
    if isinstance(node, PositionOf):
        return {
            "kind": "position_of",
            "children": _enc_children(node.children),
            "item": tag_value(node.item),
        }
    if isinstance(node, Length):
        return {"kind": "length", "children": _enc_children(node.children)}
    if isinstance(node, Prop):
        return {"kind": "prop", "children": _enc_children(node.children), "name": node.name}
    if isinstance(node, Field):
        return {"kind": "field", "children": _enc_children(node.children), "name": node.name}
    if isinstance(node, Sum | Min | Max):
        return {"kind": node.kind, "children": _enc_children(node.children)}
    if isinstance(node, CountOf):
        return {
            "kind": "count_of",
            "children": _enc_children(node.children),
            "values": [tag_value(v) for v in node.values],
        }
    if isinstance(node, IsSorted):
        return {
            "kind": "is_sorted",
            "children": _enc_children(node.children),
            "descending": node.descending,
        }
    if isinstance(node, Distinct):
        return {
            "kind": "distinct",
            "children": _enc_children(node.children),
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
    raise SerializationError(f"unknown expression node kind {kind!r}")


def decode_bool_expr(tree: dict[str, Any]) -> BoolExpr:
    node = decode_expr(tree)
    assert isinstance(node, BoolExpr)
    return node


def decode_arith_expr(tree: dict[str, Any]) -> ArithExpr:
    node = decode_expr(tree)
    assert isinstance(node, ArithExpr)
    return node
