"""Support types for `.symbolic()` and `.code()`.

See API.md, "Support Types" and "Parameter Types" > "Program".

Core defines and checks the `.symbolic()` AST's structure: the vocabulary
this param declared, arity where a `Primitive` declares one, variable names,
literal bounds and tree depth. It ships no evaluator, and a bare string
primitive carries no arity or meaning of its own. `Primitive.fn` and a bare
string are declared metadata for a consumer's own interpreter, never called
by core.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from designspace.charts import build_chart
from designspace.ir import Chart, IntegerDomain, RealDomain

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


@dataclass(frozen=True)
class Signature:
    """The interface a `.symbolic()` or `.code()` parameter must satisfy.

    For a symbolic parameter the argument names also become the variables
    usable in the tree. Argument order is meaningful and preserved.

    Types may be given as Python types or as bare strings; a type is
    normalized to its name, so the signature stays serializable.

    Attributes
    ----------
    args : MappingProxyType[str, str]
        Argument names to type names, in order.
    returns : str
        The return type's name.

    Examples
    --------
    >>> sig = ds.Signature(args={"x": float, "y": float}, returns=float)
    >>> dict(sig.args), sig.returns
    ({'x': 'float', 'y': 'float'}, 'float')
    """

    args: MappingProxyType[str, str]
    returns: str

    def __init__(self, args: Mapping[str, type | str], returns: type | str) -> None:
        normalized = {name: t.__name__ if isinstance(t, type) else t for name, t in args.items()}
        object.__setattr__(self, "args", MappingProxyType(normalized))
        object.__setattr__(
            self, "returns", returns.__name__ if isinstance(returns, type) else returns
        )


@dataclass(frozen=True)
class FloatLiteral:
    """A range of real constants admissible in a `.symbolic()` tree.

    Declare one among a symbolic parameter's `primitives` to allow
    `{"const": v}` nodes; a constant is valid only if it falls within some
    declared literal's bounds.

    Attributes
    ----------
    lo : float
        Lowest admissible constant.
    hi : float
        Highest admissible constant.

    Examples
    --------
    >>> lit = ds.FloatLiteral(-1.0, 1.0)
    >>> lit.lo, lit.hi
    (-1.0, 1.0)
    """

    lo: float
    hi: float

    @property
    def chart(self) -> Chart:
        """A chart over the literal's range, for a consumer that generates trees.

        Offered for convenience only: the library ships no evaluator and
        never draws constants itself.

        Examples
        --------
        >>> ds.FloatLiteral(-1.0, 1.0).chart.from_unit(0.5)
        0.0
        """
        chart = build_chart("<literal>", "real", RealDomain(self.lo, self.hi), None, None)
        assert chart is not None
        return chart


@dataclass(frozen=True)
class IntLiteral:
    """A range of integer constants admissible in a `.symbolic()` tree.

    The integer counterpart of `FloatLiteral`.

    Attributes
    ----------
    lo : int
        Lowest admissible constant, inclusive.
    hi : int
        Highest admissible constant, inclusive.

    Examples
    --------
    >>> lit = ds.IntLiteral(0, 4)
    >>> lit.lo, lit.hi
    (0, 4)
    """

    lo: int
    hi: int

    @property
    def chart(self) -> Chart:
        """A chart over the literal's range, for a consumer that generates trees.

        Offered for convenience only: the library ships no evaluator and
        never draws constants itself.

        Examples
        --------
        >>> ds.IntLiteral(0, 4).chart.from_unit(0.5)
        2
        """
        chart = build_chart("<literal>", "integer", IntegerDomain(self.lo, self.hi), None, None)
        assert chart is not None
        return chart


@dataclass(frozen=True)
class Primitive:
    """An operator declared for a `.symbolic()` parameter, with its arity.

    Naming a primitive as a bare string is enough to admit it, but then
    nothing checks how many arguments it is given. Declaring it this way
    adds that check. `fn` is metadata for your own interpreter, and the
    library never calls it.

    Attributes
    ----------
    name : str
        The operator name, as it appears in a tree's `"op"` field.
    arity : int | tuple[int, int | None]
        An exact count, or a `(lo, hi)` range with `hi=None` for
        unbounded.
    fn : Any
        An implementation, for a consumer's own evaluator. Never called by
        the library, and not serializable.

    Examples
    --------
    >>> ds.Primitive("add", 2).arity_range
    (2, 2)
    >>> ds.Primitive("sum", (1, None)).arity_range
    (1, None)
    """

    name: str
    arity: int | tuple[int, int | None]
    fn: Any = None

    @property
    def arity_range(self) -> tuple[int, int | None]:
        """The arity as a `(lo, hi)` pair, whichever form it was declared in.

        Examples
        --------
        >>> ds.Primitive("neg", 1).arity_range
        (1, 1)
        """
        if isinstance(self.arity, tuple):
            return self.arity
        return (self.arity, self.arity)
