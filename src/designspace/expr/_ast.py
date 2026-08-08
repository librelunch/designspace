"""Expression AST nodes: BoolExpr and ArithExpr trees, construction only.

Every node is an immutable, hashable dataclass exposing `.kind`, `.children`,
and `.params` (API.md, "Expressions"). Nothing here evaluates or resolves:
building a node never inspects a `Space` or a config.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)

# The dual-typed scalar universe `.prop()` and `ds.value()` may declare/return
# (API.md, "Expressions": row 16's scalar restriction "applies identically" to
# `ds.value`). Shared here rather than duplicated in resolve/_expr_checks.py,
# which imports it back. `resolve` already depends on `expr`, never the
# reverse.
SCALAR_TYPES = (int, float, bool, str)

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
    """An expression: the shared base of conditions and arithmetic.

    Expressions are trees, not values. Writing `ds.param("x") < 3` builds a
    comparison node; nothing is evaluated until a configuration is supplied.
    That is what lets the library analyse constraints (derive the
    dependency graph, compute margins, narrow domains) rather than merely
    run them.

    Every node reports `.kind`, `.children`, and `.params`, so a consumer
    can walk a constraint without knowing the node types.

    Two Python operators are deliberately refused. `and`/`or`/`not` and
    `in` coerce their operands to bools, which would silently collapse an
    expression into `True`; using them raises `TypeError` pointing at `&`,
    `|`, `~`, and `.is_in()`.
    """

    @property
    def kind(self) -> str:
        """A short string naming the node type.

        Examples
        --------
        >>> ds.param("x").kind
        'ref'
        >>> (ds.param("x") < 3).kind
        'lt'
        """
        raise NotImplementedError

    @property
    def children(self) -> tuple[Expr, ...]:
        """The node's operands, in order.

        Together with `.kind` this is enough to walk or rebuild any
        expression tree. A leaf has none.

        Examples
        --------
        >>> [c.kind for c in (ds.param("x") < 3).children]
        ['ref', 'literal']
        """
        raise NotImplementedError

    @property
    def params(self) -> frozenset[str]:
        """Every parameter path this expression references.

        What the dependency graph is built from, and how a constraint
        knows which parameters it belongs to.

        Examples
        --------
        >>> sorted((ds.param("x") + ds.param("y") < 3).params)
        ['x', 'y']
        """
        result: frozenset[str] = frozenset()
        for child in self.children:
            result = result | child.params
        return result

    def is_active(self) -> BoolExpr:
        """Whether the referenced parameter is active, as a condition.

        Lets a constraint ask about presence rather than value: "if the
        cache is switched on at all, then ...". Distinct from reading the
        value, which would be unknown for an inactive parameter.

        Returns
        -------
        BoolExpr
            A condition, true when the parameter is present.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use_cache").bool(),
        ...     ds.param("cache_mb").integer(64, 512).when(ds.param("use_cache")),
        ...     ds.param("workers").integer(1, 8),
        ... )
        >>> s = s.require(
        ...     ds.param("cache_mb").is_active().implies(ds.param("workers") <= 4)
        ... )
        >>> s.is_feasible({"use_cache": True, "cache_mb": 128, "workers": 2})
        True
        >>> s.is_feasible({"use_cache": True, "cache_mb": 128, "workers": 8})
        False
        >>> s.is_feasible({"use_cache": False, "workers": 8})
        True
        """
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
        """Material implication: if this holds, `other` must too.

        The natural shape for a conditional rule such as "if we are on GPU, the
        batch must be at least 32", and much clearer than the equivalent
        `~a | b`, which it is exactly (down to the fingerprint).

        Parameters
        ----------
        other : BoolExpr
            The consequent.

        Returns
        -------
        BoolExpr
            A condition, false only when this holds and `other` does not.

        Raises
        ------
        TypeError
            If `other` is not a boolean expression.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("gpu").bool(),
        ...     ds.param("batch").integer(1, 64),
        ... ).require(ds.param("gpu").implies(ds.param("batch") >= 32))
        >>> s.is_feasible({"gpu": True, "batch": 64})
        True
        >>> s.is_feasible({"gpu": True, "batch": 8})
        False

        The rule says nothing when the antecedent is false:

        >>> s.is_feasible({"gpu": False, "batch": 8})
        True
        """
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
        # comparing values (API.md, "Expressions" > BoolExpr).
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
        """Whether the value is one of `values`.

        The replacement for Python's `in`, which cannot be used on an
        expression: `in` coerces its result to a bool and would collapse
        the tree.

        Parameters
        ----------
        *values : Any
            The values to test membership against.

        Returns
        -------
        BoolExpr
            A condition.

        Examples
        --------
        >>> s = ds.space(ds.param("algo").categorical("a", "b", "c"))
        >>> s = s.require(ds.param("algo").is_in("a", "b"))
        >>> s.is_feasible({"algo": "a"})
        True
        >>> s.is_feasible({"algo": "c"})
        False
        """
        return IsIn(self, tuple(values))

    def if_inactive(self, fallback: object) -> ArithExpr:
        """Substitute `fallback` when this expression has no value.

        An expression over an inactive parameter, or an aggregate over a
        list that is switched off, evaluates to *unknown*, and a
        constraint that cannot be decided is treated as inapplicable
        rather than violated. That is usually right, but sometimes the
        intended reading is "absent means zero". This says so.

        It substitutes only for **inactivity**. An expression that is
        unknown because a value has not been chosen yet stays unknown, and
        an aggregate over an active but empty list keeps its own empty
        value, which the fallback would otherwise mask.

        Parameters
        ----------
        fallback : object
            The value to use when the expression is inactive.

        Returns
        -------
        ArithExpr
            An expression that is never unknown for want of activity.

        Examples
        --------
        Without a fallback the budget cannot be decided, so it does not
        constrain anything:

        >>> s = ds.space(
        ...     ds.param("use_cache").bool(),
        ...     ds.param("cache_mb").integer(64, 512).when(ds.param("use_cache")),
        ...     ds.param("heap_mb").integer(64, 512),
        ... )
        >>> total = ds.param("cache_mb") + ds.param("heap_mb")
        >>> loose = s.require(total <= 512)
        >>> loose.is_feasible({"use_cache": False, "heap_mb": 512})
        True

        With one, an absent cache counts as zero and the rule applies:

        >>> guarded = s.require(ds.param("cache_mb").if_inactive(0) + ds.param("heap_mb") <= 400)
        >>> guarded.is_feasible({"use_cache": False, "heap_mb": 512})
        False
        >>> guarded.is_feasible({"use_cache": False, "heap_mb": 256})
        True
        """
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
    """`expr.is_active()`, a total predicate: always True or False, never Unknown."""

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


@dataclass(frozen=True, eq=False)
class Prop(ArithExpr, BoolExpr):
    """`ds.param("c").prop(name)`: a custom type's declared scalar
    property (int/float/bool/str only). `operand` is the custom-typed
    param reference; `name` is checked against the type's `properties()`
    at resolution. Dual-typed like `ParamExpr` itself: a
    bool-declared prop is usable directly as a condition (`.require(x.prop
    ("ok"))`, `&`/`|`/`~`), not just inside a `Compare`, matching the same
    "bare BoolExpr coerces via `bool(value)`" convention every param
    reference already gets. Bare boolean-position usage carries no
    `type_kind` or declared-type gate anywhere in the library, while the
    *declared* and *scalar* checks do still apply uniformly here.

    Exported because it is `.prop()`'s return type and no other public
    type captures it: being both an `ArithExpr` and a `BoolExpr` is what
    lets a bool-declared property serve as a bare condition, which neither
    base alone expresses.

    Attributes
    ----------
    operand : ArithExpr
        The custom-typed parameter reference being read.
    name : str
        The property name, checked against the type's `properties()` at
        resolution.
    """

    operand: ArithExpr
    name: str

    @property
    def kind(self) -> str:
        """The node kind, always `"prop"`."""
        return "prop"

    @property
    def children(self) -> tuple[Expr, ...]:
        """The operands, just the custom-typed parameter being read."""
        return (self.operand,)


@dataclass(frozen=True, eq=False)
class Value(ArithExpr, BoolExpr):
    """`ds.value(fn, *operands, returns=type)`: an opaque derived quantity:
    `.prop()` generalized from *one custom param, named property* to *any
    operands, arbitrary function*. `fn` is called with exactly the operand
    values, positionally, and never the config; every operand is checked
    to be an expression at construction. The
    referenced params are the union of the operands' own references, so
    `dependency_graph`/ordering/cycle detection are unaffected. Dual-typed
    like `Prop`: a `returns=bool` node is usable directly as a condition,
    matching the same "bare BoolExpr coerces via `bool(value)`" convention.
    `returns` is one of `SCALAR_TYPES`.

    Exported because it is `ds.value()`'s return type and no other public
    type captures it: being both an `ArithExpr` and a `BoolExpr` is what
    lets a `returns=bool` node serve as a bare condition, which neither
    base alone expresses.

    Attributes
    ----------
    fn : Callable[..., Any]
        The consumer's function, called with the operands' values.
        Opaque to the library, and not serializable.
    operands : tuple[Expr, ...]
        The expressions supplying `fn`'s arguments, in order.
    returns : type
        The declared scalar return type: `int`, `float`, `bool`, or `str`.
    """

    fn: Callable[..., Any]
    operands: tuple[Expr, ...]
    returns: type

    @property
    def kind(self) -> str:
        """The node kind, always `"value"`."""
        return "value"

    @property
    def children(self) -> tuple[Expr, ...]:
        """The operands, in the order `fn` receives their values."""
        return self.operands


class VectorExpr(Expr):
    """The mixin exposing the aggregate namespace.

    API.md, "Expressions" > "Vector expressions and aggregates" says that "a
    scalar lift *is* a vector expression; `.field(name)` projects a struct
    lift into one".

    Shared by `ParamExpr` in `builder/_paramexpr.py`, when it references a
    lift, and by `Field` below. Neither the mixin nor its methods validate
    that the operand is lift-typed; that is `resolve/`'s job, as it is for
    `.contains()` and `.size()`.
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


@dataclass(frozen=True, eq=False)
class ChartApply(ArithExpr, VectorExpr):
    """A representation's decode, substituted into a transported expression.

    See API.md, "Expressions" > "Chart application" and "The Representation
    Layer" > "Transport". With `ds.value`, this is one of the two nodes the
    expression language will ever grow, and unlike `ds.value` it is
    opaque-free: `fn` is always `chart.from_unit`, a pure function of the
    declaration already on `ParamDef`.

    It is not user-constructible. `represent/_transport.py` emits it when
    leaf substitution rewrites a reference to an encoded param, wrapping
    whatever reference node sits at the substitution site: a bare
    `ParamExpr`, for a scalar or a direct lift, or a `Field` projection, for
    a struct lift's member.

    It carries the source chart's declaration, meaning its domain, prior,
    quantization and periodicity, because the param `operand` reads in the
    genotype is an ordinary `real(0, 1)` whose own chart is uniform. API.md
    puts it as "It carries the source chart's declaration ... because the
    param it reads in the genotype is an ordinary real(0,1) whose own chart
    is uniform".

    It is vector-polymorphic like `Field`: applied to a lift or a projection
    of one, it maps element-wise over the leaves, which `_vector_values` in
    `eval/_kleene.py` performs. That is why it is a `VectorExpr` and not an
    `ArithExpr` alone.

    IR-typed fields are `Any` here to avoid a cycle, `expr/` never importing
    `ir/`, as `CustomDomain.param_type` and `ListDomain.element_constraints`
    do in the other direction.
    """

    operand: Expr
    chart: Any  # designspace.ir.Chart: decodes a unit coordinate to a source value
    type_kind: str  # "real" | "integer" -- the SOURCE kind
    domain: Any  # designspace.ir.RealDomain | IntegerDomain (source)
    prior: Any = None  # designspace.ir.PriorSpec | None (source)
    quantized: Any = None  # designspace.ir.QuantizedSpec | None (source)
    periodic: bool = False

    @property
    def kind(self) -> str:
        return "chart_apply"

    @property
    def children(self) -> tuple[Expr, ...]:
        return (self.operand,)
