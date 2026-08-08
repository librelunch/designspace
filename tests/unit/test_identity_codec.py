"""Round-trip tests for the identity and serialization codec.

The codec is `identity/_tags.py` with `identity/_ir_codec.py`, and every
expression AST node kind and every `Domain` kind is covered.

These are lower-level than `tests/conformance/test_identity.py`'s laws: they
pin the codec itself, independent of any particular corpus space. A subtle
encode-or-decode bug in one node or domain kind is otherwise easy to miss
when it is exercised only through a handful of hand-built law-test spaces.

Expression nodes use `eq=False`, so equality is identity. A round trip is
therefore verified by re-encoding the decoded node and comparing the trees:
the tree, rather than the Python object, is the thing whose stability
matters.
"""

from __future__ import annotations

import pytest

from designspace import ParamExpr
from designspace.errors import SerializationError
from designspace.expr import (
    ArithOp,
    BoolLiteral,
    BoolOp,
    Compare,
    Contains,
    Count,
    CountOf,
    Distinct,
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
    Size,
    Sum,
    SumOver,
    Value,
)
from designspace.identity._ir_codec import EncodeContext, decode_domain, encode_domain
from designspace.identity._tags import (
    decode_default_value,
    decode_expr,
    encode_default_value,
    encode_expr,
    tag_value,
    untag_value,
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
)

_x = ParamExpr(path="x")
_y = ParamExpr(path="y")

EXPR_CASES = {
    "literal_int": Literal(5),
    "literal_float": Literal(5.5),
    "literal_str": Literal("s"),
    "literal_bool": Literal(True),
    "literal_none": Literal(None),
    "bool_literal_true": BoolLiteral(True),
    "bool_literal_false": BoolLiteral(False),
    "ref": _x,
    "add": ArithOp("add", _x, Literal(1)),
    "sub": ArithOp("sub", _x, Literal(1)),
    "mul": ArithOp("mul", _x, Literal(2)),
    "div": ArithOp("div", _x, Literal(2)),
    "pow": ArithOp("pow", _x, Literal(2)),
    "mod": ArithOp("mod", _x, Literal(2)),
    "eq": Compare("eq", _x, _y),
    "ne": Compare("ne", _x, _y),
    "gt": Compare("gt", _x, _y),
    "lt": Compare("lt", _x, _y),
    "ge": Compare("ge", _x, _y),
    "le": Compare("le", _x, _y),
    "and": BoolOp("and", Compare("gt", _x, Literal(0)), Compare("lt", _y, Literal(1))),
    "or": BoolOp("or", Compare("gt", _x, Literal(0)), Compare("lt", _y, Literal(1))),
    "not": Not(Compare("gt", _x, Literal(0))),
    "implies": Implies(Compare("gt", _x, Literal(0)), Compare("lt", _y, Literal(1))),
    "is_in": IsIn(_x, (1, 2, "three")),
    "is_active": IsActive(_x),
    "count_empty": Count(()),
    "count_one": Count((Compare("gt", _x, Literal(0)),)),
    "count_many": Count(
        (Compare("gt", _x, Literal(0)), Compare("lt", _y, Literal(1)), BoolLiteral(True))
    ),
    "if_inactive": IfInactive(_x, Literal(-1)),
    "contains": Contains(_x, "item"),
    "size": Size(_x),
    "sum_over": SumOver(_x, {"a": 1.0, "b": 2.5}),
    "position_of": PositionOf(_x, "item"),
    "length": Length(_x),
    "field": Field(_x, "member"),
    "sum": Sum(_x),
    "min": Min(_x),
    "max": Max(_x),
    "count_of": CountOf(_x, (1, "two", 3.0)),
    "is_sorted_asc": IsSorted(_x, False),
    "is_sorted_desc": IsSorted(_x, True),
    "distinct_no_fields": Distinct(_x),
    "distinct_fields": Distinct(_x, ("a", "b")),
}


@pytest.mark.parametrize("node", EXPR_CASES.values(), ids=EXPR_CASES.keys())
def test_expr_round_trip(node):
    tree = encode_expr(node)
    decoded = decode_expr(tree)
    assert encode_expr(decoded) == tree


class TestExprCodecDisambiguation:
    def test_literal_and_bool_literal_do_not_collide(self):
        lit_tree = encode_expr(Literal(True))
        bool_tree = encode_expr(BoolLiteral(True))
        assert lit_tree != bool_tree
        assert isinstance(decode_expr(lit_tree), Literal)
        assert isinstance(decode_expr(bool_tree), BoolLiteral)

    def test_sum_over_mapping_is_order_independent(self):
        a = SumOver(_x, {"a": 1.0, "b": 2.0})
        b = SumOver(_x, {"b": 2.0, "a": 1.0})
        assert encode_expr(a) == encode_expr(b)


class TestValueOpacityCodec:
    """`Value` is the one node `decode_expr` deliberately cannot reconstruct.

    It raises on the mark-sentinel `"opaque"` kind rather than round-
    tripping, so it is not a generic `EXPR_CASES` entry above and its codec
    behaviour gets its own class.
    """

    def _node(self) -> Value:
        return Value(lambda x: x, (_x,), float)

    def test_ctx_none_defaults_to_raise(self):
        with pytest.raises(SerializationError):
            encode_expr(self._node())

    def test_raise_mode_names_the_site(self):
        ctx = EncodeContext(mode="raise")
        with pytest.raises(SerializationError, match="my_site"):
            encode_expr(self._node(), ctx, site="my_site")

    def test_mark_mode_yields_the_opaque_marker(self):
        ctx = EncodeContext(mode="mark")
        tree = encode_expr(self._node(), ctx, site="s")
        assert tree == {"kind": "opaque", "$opaque": True}
        assert ctx.dropped == []

    def test_drop_mode_yields_the_marker_and_manifests_the_site(self):
        ctx = EncodeContext(mode="drop")
        tree = encode_expr(self._node(), ctx, site="s")
        assert tree == {"kind": "opaque", "$opaque": True}
        assert ctx.dropped == ["s: ds.value fn (opaque)"]

    def test_opaque_node_nested_in_a_larger_tree_still_raises(self):
        outer = BoolOp("and", Compare("gt", self._node(), Literal(0)), BoolLiteral(True))
        with pytest.raises(SerializationError):
            encode_expr(outer)

    def test_decode_opaque_marker_raises(self):
        with pytest.raises(SerializationError):
            decode_expr({"kind": "opaque", "$opaque": True})


class TestTagValue:
    @pytest.mark.parametrize("value", [1, 1.0, True, False, "s", None, 0.0, -0.0])
    def test_round_trip(self, value):
        assert untag_value(tag_value(value)) == value

    def test_bool_and_int_tag_differently(self):
        assert tag_value(1) != tag_value(True)

    def test_int_and_float_tag_differently(self):
        assert tag_value(1) != tag_value(1.0)

    def test_negative_zero_normalizes(self):
        assert tag_value(-0.0) == tag_value(0.0)

    def test_nan_rejected(self):
        with pytest.raises(SerializationError):
            tag_value(float("nan"))

    def test_inf_rejected(self):
        with pytest.raises(SerializationError):
            tag_value(float("inf"))


DOMAIN_CASES = {
    "real": ("real", RealDomain(0.0, 1.0)),
    "integer": ("integer", IntegerDomain(0, 10)),
    "categorical": ("categorical", CategoricalDomain((1, 2.0, "s", True))),
    "ordinal": ("ordinal", OrdinalDomain(("lo", "mid", "hi"))),
    "bool": ("bool", BoolDomain()),
    "subset": ("subset", SubsetDomain(items=("a", "b", "c"), min_size=1, max_size=2)),
    "subset_no_max": ("subset", SubsetDomain(items=("a", "b"), min_size=0, max_size=None)),
    "permutation": ("permutation", PermutationDomain(("a", "b", "c"))),
    "choice": (
        "choice",
        ChoiceDomain(variants=("a", "b", "c"), has_payload=frozenset({"b", "c"})),
    ),
    "space": ("space", StructDomain()),
}


@pytest.mark.parametrize("kind_domain", DOMAIN_CASES.values(), ids=DOMAIN_CASES.keys())
def test_domain_round_trip(kind_domain):
    kind, domain = kind_domain
    ctx = EncodeContext(mode="raise")
    tree = encode_domain(kind, domain, "document", ctx, "x")
    decoded = decode_domain(kind, tree, "x")
    ctx2 = EncodeContext(mode="raise")
    assert encode_domain(kind, decoded, "document", ctx2, "x") == tree


class TestListDomainRoundTrip:
    def _ctx(self):
        return EncodeContext(mode="raise")

    def test_scalar_element_static_count(self):
        domain = ListDomain(
            element_kind="real",
            element_domain=RealDomain(0.0, 1.0),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=3,
            list_default=None,
        )
        tree = encode_domain("list", domain, "document", self._ctx(), "xs")
        decoded = decode_domain("list", tree, "xs")
        assert encode_domain("list", decoded, "document", self._ctx(), "xs") == tree
        assert tree["count"] == {"kind": "static", "n": 3}

    def test_dynamic_count_expression(self):
        domain = ListDomain(
            element_kind="real",
            element_domain=RealDomain(0.0, 1.0),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=ParamExpr(path="n"),
            list_default=None,
        )
        tree = encode_domain("list", domain, "document", self._ctx(), "xs")
        decoded = decode_domain("list", tree, "xs")
        assert isinstance(decoded.count, ParamExpr)
        assert decoded.count.path == "n"
        assert encode_domain("list", decoded, "document", self._ctx(), "xs") == tree

    def test_nested_list_domain(self):
        inner = ListDomain(
            element_kind="integer",
            element_domain=IntegerDomain(0, 5),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=2,
            list_default=None,
        )
        outer = ListDomain(
            element_kind="list",
            element_domain=inner,
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=3,
            list_default=None,
        )
        tree = encode_domain("list", outer, "document", self._ctx(), "xs")
        decoded = decode_domain("list", tree, "xs")
        assert encode_domain("list", decoded, "document", self._ctx(), "xs") == tree

    def test_quantized_and_defaults(self):
        domain = ListDomain(
            element_kind="real",
            element_domain=RealDomain(0.0, 1.0),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=QuantizedSpec(step=0.1, factor=None, include_hi=False),
            element_default=0.5,
            count=3,
            list_default=[0.1, 0.2, 0.3],
        )
        tree = encode_domain("list", domain, "document", self._ctx(), "xs")
        decoded = decode_domain("list", tree, "xs")
        assert decoded.element_default == 0.5
        assert decoded.list_default == [0.1, 0.2, 0.3]
        assert encode_domain("list", decoded, "document", self._ctx(), "xs") == tree

    def test_struct_shaped_list_default(self):
        # `list_default` items can be full phenotype values -- a struct
        # dict, a bare choice-variant string, or a parameterized-choice
        # dict, and never a flat scalar. `tests/unit/test_resolve_m6.py`'s
        # struct and lifted-choice list_default cases mirror this.
        domain = ListDomain(
            element_kind="space",
            element_domain=StructDomain(),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=2,
            list_default=[{"width": 128}, {"width": 256}],
        )
        tree = encode_domain("list", domain, "document", self._ctx(), "layers")
        decoded = decode_domain("list", tree, "layers")
        assert decoded.list_default == [{"width": 128}, {"width": 256}]
        assert encode_domain("list", decoded, "document", self._ctx(), "layers") == tree

    def test_choice_shaped_list_default(self):
        domain = ListDomain(
            element_kind="choice",
            element_domain=ChoiceDomain(
                variants=("shuffle", "pmx"), has_payload=frozenset({"pmx"})
            ),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=2,
            list_default=["shuffle", {"pmx": {"swap_p": 0.2}}],
        )
        tree = encode_domain("list", domain, "document", self._ctx(), "pipeline")
        decoded = decode_domain("list", tree, "pipeline")
        assert decoded.list_default == ["shuffle", {"pmx": {"swap_p": 0.2}}]
        assert encode_domain("list", decoded, "document", self._ctx(), "pipeline") == tree


class TestDefaultValueCodec:
    def test_subset_default_round_trips(self):
        value = ["a", "c"]
        tree = encode_default_value(value)
        assert decode_default_value(tree) == value

    def test_struct_default_round_trips(self):
        value = {"width": 128, "active": True, "ratio": 0.5}
        tree = encode_default_value(value)
        assert decode_default_value(tree) == value
