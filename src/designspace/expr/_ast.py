"""Expression AST nodes: BoolExpr and ArithExpr trees, construction only.

Every node is an immutable, hashable dataclass exposing `.kind`, `.children`,
and `.params` (API_v3.md, "Expressions"). No evaluation or resolution happens
here — building a node never inspects a Space or a config.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NoReturn

_BOOL_GUARD = (
    "designspace expressions cannot be coerced to bool (this is what makes "
    "`and`/`or`, chained comparisons, and `if <expr>:` fail loudly instead of "
    "silently miscompiling). Combine BoolExprs with `&`, `|`, `~`, or build "
    "one with ds.all_()/ds.any_()."
)
_CONTAINS_GUARD = (
    "designspace expressions do not support Python's `in` operator. Use "
    "`.is_in(...)` for membership against declared values, or `.contains(...)` "
    "for subset membership."
)


class Expr:
    """Shared base of BoolExpr and ArithExpr AST nodes."""

    @property
    def kind(self) -> str:
        raise NotImplementedError

    @property
    def children(self) -> tuple[Expr, ...]:
        raise NotImplementedError

    @property
    def params(self) -> frozenset[str]:
        result: frozenset[str] = frozenset()
        for child in self.children:
            result = result | child.params
        return result

    def is_active(self) -> BoolExpr:
        return IsActive(self)

    def __bool__(self) -> NoReturn:
        raise TypeError(_BOOL_GUARD)

    def __contains__(self, item: object) -> NoReturn:
        raise TypeError(_CONTAINS_GUARD)


class BoolExpr(Expr):
    """An expression node that evaluates to a (Kleene) truth value."""

    def __and__(self, other: BoolExpr) -> BoolExpr:
        if not isinstance(other, BoolExpr):
            return NotImplemented
        return BoolOp("and", self, other)

    def __or__(self, other: BoolExpr) -> BoolExpr:
        if not isinstance(other, BoolExpr):
            return NotImplemented
        return BoolOp("or", self, other)

    def __invert__(self) -> BoolExpr:
        return Not(self)

    def implies(self, other: BoolExpr) -> BoolExpr:
        if not isinstance(other, BoolExpr):
            raise TypeError("implies() requires a BoolExpr operand")
        return Implies(self, other)


def _coerce_arith(value: object) -> ArithExpr:
    if isinstance(value, ArithExpr):
        return value
    return Literal(value)


class ArithExpr(Expr):
    """An expression node that evaluates to a scalar (numeric or otherwise) value."""

    def __add__(self, other: object) -> ArithExpr:
        return ArithOp("add", self, _coerce_arith(other))

    def __radd__(self, other: object) -> ArithExpr:
        return ArithOp("add", _coerce_arith(other), self)

    def __sub__(self, other: object) -> ArithExpr:
        return ArithOp("sub", self, _coerce_arith(other))

    def __rsub__(self, other: object) -> ArithExpr:
        return ArithOp("sub", _coerce_arith(other), self)

    def __mul__(self, other: object) -> ArithExpr:
        return ArithOp("mul", self, _coerce_arith(other))

    def __rmul__(self, other: object) -> ArithExpr:
        return ArithOp("mul", _coerce_arith(other), self)

    def __truediv__(self, other: object) -> ArithExpr:
        return ArithOp("div", self, _coerce_arith(other))

    def __rtruediv__(self, other: object) -> ArithExpr:
        return ArithOp("div", _coerce_arith(other), self)

    def __pow__(self, other: object) -> ArithExpr:
        return ArithOp("pow", self, _coerce_arith(other))

    def __rpow__(self, other: object) -> ArithExpr:
        return ArithOp("pow", _coerce_arith(other), self)

    def __mod__(self, other: object) -> ArithExpr:
        return ArithOp("mod", self, _coerce_arith(other))

    def __rmod__(self, other: object) -> ArithExpr:
        return ArithOp("mod", _coerce_arith(other), self)

    def __eq__(self, other: object) -> BoolExpr:  # type: ignore[override]
        # Overridden by design: `==` builds a Compare node rather than
        # comparing values (API_v3.md, "Expressions" — BoolExpr).
        return Compare("eq", self, _coerce_arith(other))

    def __ne__(self, other: object) -> BoolExpr:  # type: ignore[override]
        return Compare("ne", self, _coerce_arith(other))

    def __gt__(self, other: object) -> BoolExpr:
        return Compare("gt", self, _coerce_arith(other))

    def __lt__(self, other: object) -> BoolExpr:
        return Compare("lt", self, _coerce_arith(other))

    def __ge__(self, other: object) -> BoolExpr:
        return Compare("ge", self, _coerce_arith(other))

    def __le__(self, other: object) -> BoolExpr:
        return Compare("le", self, _coerce_arith(other))

    # `__eq__` is overridden for DSL purposes above; restore hashability
    # explicitly (Python nulls `__hash__` when a class defines `__eq__`).
    __hash__ = object.__hash__

    def is_in(self, *values: Any) -> BoolExpr:
        return IsIn(self, tuple(values))

    def if_inactive(self, fallback: object) -> ArithExpr:
        return IfInactive(self, _coerce_arith(fallback))


@dataclass(frozen=True, eq=False)
class Literal(ArithExpr):
    """A literal scalar value used as an operand (e.g. the `3` in `x > 3`)."""

    value: Any

    @property
    def kind(self) -> str:
        return "literal"

    @property
    def children(self) -> tuple[Expr, ...]:
        return ()


@dataclass(frozen=True, eq=False)
class BoolLiteral(BoolExpr):
    """A literal True/False BoolExpr (e.g. `ds.all_()`'s zero-arg identity)."""

    value: bool

    @property
    def kind(self) -> str:
        return "literal"

    @property
    def children(self) -> tuple[Expr, ...]:
        return ()


@dataclass(frozen=True, eq=False)
class Compare(BoolExpr):
    """`==`, `!=`, `>`, `<`, `>=`, `<=` between two ArithExpr operands."""

    op: str
    left: ArithExpr
    right: ArithExpr

    @property
    def kind(self) -> str:
        return self.op

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, eq=False)
class ArithOp(ArithExpr):
    """`+`, `-`, `*`, `/`, `**`, `%` between two ArithExpr operands."""

    op: str
    left: ArithExpr
    right: ArithExpr

    @property
    def kind(self) -> str:
        return self.op

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, eq=False)
class BoolOp(BoolExpr):
    """`&` / `|` between two BoolExpr operands."""

    op: str
    left: BoolExpr
    right: BoolExpr

    @property
    def kind(self) -> str:
        return self.op

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, eq=False)
class Not(BoolExpr):
    """`~expr`."""

    operand: BoolExpr

    @property
    def kind(self) -> str:
        return "not"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Implies(BoolExpr):
    """`expr.implies(other)`; desugared to `~expr | other` at resolution."""

    left: BoolExpr
    right: BoolExpr

    @property
    def kind(self) -> str:
        return "implies"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.left, self.right)


@dataclass(frozen=True, eq=False)
class IsIn(BoolExpr):
    """`expr.is_in(*values)`. `values` are literal data, not sub-expressions."""

    operand: ArithExpr
    values: tuple[Any, ...]

    @property
    def kind(self) -> str:
        return "is_in"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class IsActive(BoolExpr):
    """`expr.is_active()`; total — always True or False, never Unknown."""

    operand: Expr

    @property
    def kind(self) -> str:
        return "is_active"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Count(ArithExpr):
    """`ds.count(*bool_exprs)`: number of True operands."""

    operands: tuple[BoolExpr, ...]

    @property
    def kind(self) -> str:
        return "count"

    @property
    def children(self) -> tuple[Expr, ...]:
        return self.operands


@dataclass(frozen=True, eq=False)
class IfInactive(ArithExpr):
    """`expr.if_inactive(fallback)`: inactive -> fallback; unset stays pending."""

    operand: ArithExpr
    fallback: ArithExpr

    @property
    def kind(self) -> str:
        return "if_inactive"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand, self.fallback)


@dataclass(frozen=True, eq=False)
class Contains(BoolExpr):
    """`ds.param("s").contains(item)`: subset membership (invalid on
    permutation; checked at resolution, error row 18)."""

    operand: ArithExpr
    item: Any

    @property
    def kind(self) -> str:
        return "contains"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Size(ArithExpr):
    """`ds.param("s").size()`: subset cardinality."""

    operand: ArithExpr

    @property
    def kind(self) -> str:
        return "size"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class SumOver(ArithExpr):
    """`ds.param("s").sum_over(mapping)`: Σ mapping[item] over included
    items. `mapping` is literal data (keys ⊆ item universe, checked at
    resolution, error row 18), not a sub-expression."""

    operand: ArithExpr
    mapping: Any  # MappingProxyType[Any, float]

    @property
    def kind(self) -> str:
        return "sum_over"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class PositionOf(ArithExpr):
    """`ds.param("p").position_of(item)`: permutation index of `item`
    (must be a declared member, checked at resolution, error row 18)."""

    operand: ArithExpr
    item: Any

    @property
    def kind(self) -> str:
        return "position_of"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Length(ArithExpr):
    """`ds.param("r").length()`: a lift's realized element count."""

    operand: ArithExpr

    @property
    def kind(self) -> str:
        return "length"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


class VectorExpr(Expr):
    """Mixin exposing the aggregate namespace (API_v3.md, "Expressions" —
    "Vector expressions and aggregates"): "a scalar lift *is* a vector
    expression; `.field(name)` projects a struct lift into one." Shared by
    `ParamExpr` (build/_paramexpr.py, when it references a lift) and
    `Field` below — neither the mixin nor its methods validate that the
    operand is actually lift-typed; that is resolve/'s job (M0's "no
    validation happens here" principle, same as `.contains()`/`.size()`).
    """

    def field(self, name: str) -> Field:
        return Field(self, name)

    def sum(self) -> ArithExpr:
        return Sum(self)

    def min(self) -> ArithExpr:
        return Min(self)

    def max(self) -> ArithExpr:
        return Max(self)

    def count_of(self, *values: Any) -> ArithExpr:
        return CountOf(self, tuple(values))

    def is_sorted(self, descending: bool = False) -> BoolExpr:
        return IsSorted(self, descending)

    def distinct(self, *fields: str) -> BoolExpr:
        return Distinct(self, tuple(fields))


@dataclass(frozen=True, eq=False)
class Field(VectorExpr):
    """`.field(name)`: projects a struct lift into the vector of its
    `name` member's values, one per instance (nested lifts: shape-
    preserving; aggregates flatten across levels regardless)."""

    operand: Expr
    name: str

    @property
    def kind(self) -> str:
        return "field"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Sum(ArithExpr):
    """`.sum()`: numeric aggregate over a vector's leaves."""

    operand: Expr

    @property
    def kind(self) -> str:
        return "sum"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Min(ArithExpr):
    """`.min()`: empty vector -> Unknown (rule 6)."""

    operand: Expr

    @property
    def kind(self) -> str:
        return "min"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Max(ArithExpr):
    """`.max()`: empty vector -> Unknown (rule 6)."""

    operand: Expr

    @property
    def kind(self) -> str:
        return "max"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class CountOf(ArithExpr):
    """`.count_of(*values)`: count of leaves equal to any of `values`
    (equality-comparable elements; on a lifted choice, counts variants)."""

    operand: Expr
    values: tuple[Any, ...]

    @property
    def kind(self) -> str:
        return "count_of"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class IsSorted(BoolExpr):
    """`.is_sorted(descending=False)`. Depth 1 only (row 24)."""

    operand: Expr
    descending: bool = False

    @property
    def kind(self) -> str:
        return "is_sorted"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Distinct(BoolExpr):
    """`.distinct()` (scalar lift: pairwise-distinct elements) /
    `.distinct(*fields)` (struct lift: distinct field tuples)."""

    operand: Expr
    fields: tuple[str, ...] = ()

    @property
    def kind(self) -> str:
        return "distinct"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)
