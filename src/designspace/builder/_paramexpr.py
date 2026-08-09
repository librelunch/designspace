"""ParamExpr: `ds.param(name)`, dual reference/definition (API.md, "Construction").

Type methods and modifiers are pure recorders: each returns a new, immutable
`ParamExpr` with its pending state updated. Nothing is validated here. The
pass pipeline in `resolve/` decides what is an error, not the builder.

An internal storage field takes a trailing `_spec` or `_value` where the
public modifier method shares the field's natural name, as with `prior`,
`default`, `quantized` and `meta`. A dataclass field and a same-named method
collide in one class body, the `def` statement overwriting the field's
class-level default, so the method needs its own name for the state it reads
and writes.

The type methods and `.repeat()` live in `builder/_views.py`; see API.md,
"Builder view types". `ParamExpr` is the base type, with no type methods and
no `.repeat()`, but with every modifier that stays universal across param
types, namely `.prior()`, `.default()`, `.when()`, `.tag()` and `.meta()`,
along with the combinatorial queries and the `VectorExpr` aggregates.
Reference-position usage needs those regardless of which type, if any, the
referenced param turns out to declare.

`type_kind` is a `ClassVar` rather than a field. Each view in
`builder/_views.py` declares its own fixed `type_kind`, as with
`RealParamExpr.type_kind = "real"`, so it is excluded from `__init__`
entirely: `ParamExpr(path="x", type_kind="integer")` is a `TypeError` rather
than a value resolution could misread. A bare `ParamExpr` or
`FreshParamExpr`, with no type chosen, inherits the base's `None`.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeVar

from designspace.display._hooks import displayable
from designspace.errors import ResolutionError
from designspace.expr import (
    ArithExpr,
    BoolExpr,
    Contains,
    Expr,
    Length,
    PositionOf,
    Prop,
    Size,
    SumOver,
    VectorExpr,
)
from designspace.ir import Domain, QuantizedSpec, Weights

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)

_ViewT = TypeVar("_ViewT", bound="ParamExpr")

# The names `__getattr__` recognizes as meaningful misses: a second type
# method, which is row 2, and a numeric-only modifier misapplied to a
# non-numeric view or written after `.repeat()`, which is row 11. Both are
# frozen error-table rows, tagged R for ResolutionError, and must not
# degrade to a bare AttributeError merely because the view narrowing hid the
# method. Any other attribute miss is a genuine typo and stays a plain
# AttributeError.
_TYPE_METHOD_NAMES = frozenset(
    {
        "real",
        "integer",
        "categorical",
        "ordinal",
        "bool",
        "subset",
        "permutation",
        "choice",
        "space",
        "custom",
        "symbolic",
        "code",
    }
)
_NUMERIC_ONLY_MODIFIERS = frozenset({"log_scale", "quantized"})


@dataclass(frozen=True)
class _ElementSnapshot:
    """Builder-time closure of everything left of `.repeat()`.

    See API.md, "Modifiers and Layering" > "The lift".

    When `element_class is ListParamExpr`, the snapshot describes one
    `.repeat()` level: `element`, `count` and `list_default` are populated,
    the leaf fields below are unused, and `element` recurses for a chained
    or variadic `.repeat().repeat()`. Otherwise it describes the element
    itself, of a scalar, subset, permutation, choice or struct type,
    mirroring the same-named `ParamExpr` fields it was snapshotted from.

    `element_class` is the view class the element was declared with,
    `type(self)` at the time `.repeat()` was called, rather than a
    `type_kind` string. It is always a concrete leaf, `.repeat()` existing
    only on typed views. `resolve/_pipeline.py` reconstructs the element by
    calling `element_class(...)` directly, and reads the view's
    `element_class.type_kind` `ClassVar` wherever the IR needs the plain
    string, as `ListDomain.element_kind` does.
    """

    element_class: type[ParamExpr]
    domain: Domain | None = None
    prior_spec: Any = None
    quantized_spec: QuantizedSpec | None = None
    periodic: builtins.bool = False
    default_value: Any = None
    struct_space: Any = None
    choice_payloads: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    element: _ElementSnapshot | None = None
    count: int | ArithExpr | None = None
    list_default: Any = None


@displayable("designspace.display._space.render_param_expr")
@dataclass(frozen=True, eq=False)
class ParamExpr(ArithExpr, BoolExpr, VectorExpr):
    """A parameter, either being declared or being referred to.

    `ds.param("x")` returns one of these, and every method on it returns a
    new one. Nothing is ever mutated, so a partly-built parameter can be
    shared and branched freely.

    The same object plays two roles depending on where it is used. Passed
    to `ds.space()`, it **declares** a parameter. Used inside a constraint
    or condition, it **refers** to one, and behaves as an expression: the
    comparison and arithmetic operators build expression trees rather than
    computing anything.

    `ParamExpr` is the common base of every builder view. Once a type
    method has been called you hold a narrower view (`RealParamExpr`,
    `ChoiceParamExpr`, ...) exposing only the modifiers valid for that
    type, but everything here is available throughout.

    Attributes
    ----------
    path : str
        The parameter's name or path. The one attribute worth reading.
    domain : Domain | None
        The declared domain so far, or `None` before a type method.
    periodic : bool
        Whether the domain wraps.
    prior_spec : Any
        The prior set by `.prior()` or `.log_scale()`.
    quantized_spec : QuantizedSpec | None
        The grid set by `.quantized()`.
    default_value : Any
        The value set by `.default()`.
    condition : BoolExpr | None
        The condition accumulated by `.when()`.
    tags : frozenset[str]
        Labels accumulated by `.tag()`.
    meta_map : MappingProxyType[str, Any]
        Metadata accumulated by `.meta()`.
    choice_payloads : MappingProxyType[str, Any]
        Per-variant payload spaces, for a `.choice()`.
    struct_space : Any
        The field space, for a `.space()`.
    lift : Any
        Element and count state, once `.repeat()` has been called.

    Notes
    -----
    Every attribute but `path` is the builder's accumulated state, not a
    stable surface: it is what resolution consumes to produce the IR.
    Read `Space.params[path]`, a `ParamDef`, for introspection instead.

    Examples
    --------
    Declaring:

    >>> lr = ds.param("lr").real(1e-4, 1e-1).log_scale().default(0.01)
    >>> ds.space(lr).apply_defaults({})
    {'lr': 0.01}

    Referring:

    >>> s = ds.space(
    ...     ds.param("lo").integer(0, 5),
    ...     ds.param("hi").integer(0, 5),
    ... ).require(ds.param("lo") < ds.param("hi"))
    >>> s.is_feasible({"lo": 1, "hi": 3})
    True
    """

    path: str
    # A ClassVar rather than a field, excluded from __init__, so that
    # ParamExpr(path="x", type_kind="integer") is a TypeError, not a value
    # resolution has to police. Each view in builder/_views.py overrides this
    # with its own fixed string; a bare ParamExpr/FreshParamExpr (no type
    # chosen) inherits None.
    type_kind: ClassVar[str | None] = None
    domain: Domain | None = None
    periodic: builtins.bool = False
    prior_spec: Any = None
    quantized_spec: QuantizedSpec | None = None
    default_value: Any = None
    condition: BoolExpr | None = None
    tags: frozenset[str] = frozenset()
    meta_map: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    # -- structural payloads: raw builder-time state for .choice() and
    # .space(), merged into the flat IR during resolution by
    # resolve/_relocate.py. They are not part of `domain`, which needs only
    # the variant names and has_payload rather than the child Spaces.
    choice_payloads: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    struct_space: Any = None  # Space | None; typed Any to avoid an import cycle
    # -- the lift: set once `.repeat()` has been called at least once.
    # `domain`, `prior_spec` and the rest above are then reset, since the
    # dataclass would otherwise reuse them to mean two things at once, and
    # every element-describing fact lives in `lift` instead; see
    # `_ElementSnapshot`. The class itself, a `ListParamExpr`, already
    # carries the "this is a list" fact through its `type_kind` ClassVar.
    lift: _ElementSnapshot | None = None

    @property
    def kind(self) -> str:
        """The expression node kind, always `"ref"` for a parameter reference.

        Every expression node reports a `kind`, which is how a consumer
        walks a constraint tree without isinstance chains.

        Examples
        --------
        >>> ds.param("x").kind
        'ref'
        """
        return "ref"

    @property
    def children(self) -> tuple[Expr, ...]:
        """The node's operands, always empty, a reference being a leaf.

        Examples
        --------
        >>> ds.param("x").children
        ()
        >>> [c.path for c in (ds.param("x") < ds.param("y")).children]
        ['x', 'y']
        """
        return ()

    @property
    def params(self) -> frozenset[str]:
        """The parameter paths this expression references.

        On a bare reference that is just its own path; on a compound
        expression it is every path underneath, which is what the
        dependency graph is built from.

        Examples
        --------
        >>> ds.param("x").params
        frozenset({'x'})
        >>> sorted((ds.param("x") + ds.param("y")).params)
        ['x', 'y']
        """
        return frozenset({self.path})

    def _as(self, cls: type[_ViewT], **changes: Any) -> _ViewT:
        """Build a different concrete view from `self`'s current field values.

        `dataclasses.replace()` always returns `type(self)`, which is right
        for an ordinary modifier, since those must preserve the caller's
        view, and wrong for the type methods and `.repeat()`, which narrow
        to a specific new view.
        """
        kwargs: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        kwargs.update(changes)
        return cls(**kwargs)

    # `__getattr__` must be invisible to mypy. A class with a statically
    # visible `__getattr__` is treated by mypy as accepting any attribute
    # name, which would defeat the static-typing check that
    # `.categorical(...).log_scale()` is a real `attr-defined` error.
    # `if not TYPE_CHECKING:` makes mypy skip this definition entirely while
    # it still runs normally at import time: `attr-defined` fires under
    # mypy, and the runtime exception still raises under CPython.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            if name in _TYPE_METHOD_NAMES:
                raise ResolutionError(
                    f"param {self.path!r} declares more than one type: exactly "
                    "one type method is allowed"
                )
            if name in _NUMERIC_ONLY_MODIFIERS:
                if self.lift is not None:
                    raise ResolutionError(
                        f"param {self.path!r}: {name}() written after .repeat() applies "
                        "to the list, not the element; call it before .repeat()"
                    )
                raise ResolutionError(
                    f"param {self.path!r}: {name}() only applies to real or integer params"
                )
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # `.field()` and the aggregate methods `.sum()`, `.min()`, `.max()`,
    # `.count_of()`, `.is_sorted()` and `.distinct()` are inherited from
    # VectorExpr and stay universal. API.md requires the base to be a
    # VectorExpr, and a bare reference such as `ds.param("layers")`, written
    # before any type is known at the reference site, needs them whatever
    # the referenced param turns out to declare.

    def length(self) -> ArithExpr:
        """How many elements a `.repeat()` list holds, as an expression.

        Useful when the count is itself a parameter and you want to
        constrain the realized length.

        Returns
        -------
        ArithExpr
            An integer-valued expression.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("n").integer(1, 3),
        ...     ds.param("w").real(0, 1).repeat(ds.param("n")),
        ... ).require(ds.param("w").length() >= 2)
        >>> s.is_feasible({"n": 2, "w": [0.1, 0.2]})
        True
        >>> s.is_feasible({"n": 1, "w": [0.1]})
        False
        """
        return Length(self)

    # -- combinatorial expression methods: kept universal rather than
    # narrowed to SubsetParamExpr and PermutationParamExpr. Validity is a
    # resolution-time check, row 18 covering `.contains()` on a permutation
    # and the like, rather than a construction-time one; no evaluation and
    # no resolution happen here. `resolve/_expr_checks.py` already splits
    # `_require_subset_domain` from `_require_permutation_domain`. --------

    def contains(self, item: Any) -> BoolExpr:
        """Whether a subset parameter includes `item`, as an expression.

        Parameters
        ----------
        item : Any
            One of the subset's declared items.

        Returns
        -------
        BoolExpr
            A condition usable in `.require()`, `.forbid()`, or `.when()`.

        Examples
        --------
        >>> s = ds.space(ds.param("items").subset(["a", "b", "c"]))
        >>> s = s.require(ds.param("items").contains("a"))
        >>> s.is_feasible({"items": ["a", "b"]})
        True
        >>> s.is_feasible({"items": ["b"]})
        False
        """
        return Contains(self, item)

    def size(self) -> ArithExpr:
        """How many items a subset holds, as an expression.

        Returns
        -------
        ArithExpr
            An integer-valued expression.

        Examples
        --------
        >>> s = ds.space(ds.param("items").subset(["a", "b", "c"]))
        >>> s = s.require(ds.param("items").size() >= 2)
        >>> s.is_feasible({"items": ["a", "b"]})
        True
        >>> s.is_feasible({"items": ["a"]})
        False
        """
        return Size(self)

    def sum_over(self, mapping: dict[Any, float]) -> ArithExpr:
        """Total a per-item weight over a subset's members, as an expression.

        The natural way to write a budget: give each item a cost, then
        constrain the total of whichever items are selected.

        Parameters
        ----------
        mapping : dict[Any, float]
            Weight per declared item.

        Returns
        -------
        ArithExpr
            The sum of `mapping[i]` over the selected items `i`.

        Examples
        --------
        >>> s = ds.space(ds.param("items").subset(["a", "b", "c"]))
        >>> cost = ds.param("items").sum_over({"a": 1.0, "b": 2.0, "c": 3.0})
        >>> s = s.require(cost <= 3.0)
        >>> s.is_feasible({"items": ["a", "b"]})
        True
        >>> s.is_feasible({"items": ["b", "c"]})
        False
        """
        return SumOver(self, MappingProxyType(dict(mapping)))

    def position_of(self, item: Any) -> ArithExpr:
        """Where `item` sits in a permutation, as a zero-based expression.

        Parameters
        ----------
        item : Any
            One of the permutation's declared items.

        Returns
        -------
        ArithExpr
            The item's index.

        Examples
        --------
        >>> s = ds.space(ds.param("order").permutation(["x", "y", "z"]))
        >>> s = s.require(ds.param("order").position_of("x") == 0)
        >>> s.is_feasible({"order": ["x", "y", "z"]})
        True
        >>> s.is_feasible({"order": ["y", "x", "z"]})
        False
        """
        return PositionOf(self, item)

    def prop(self, name: str) -> Prop:
        """Read a named property of a `.custom()` value, as an expression.

        A custom type's values are opaque to the library, so this is the
        window into them: the type's `properties()` supplies the named
        quantities, and constraints can then be written over those. The
        result is dual-typed, usable as a number or as a condition,
        depending on what the property returns.

        Parameters
        ----------
        name : str
            A property name the custom type reports.

        Returns
        -------
        Prop
            An expression reading that property.

        Examples
        --------
        >>> class GridType:
        ...     type_key = "grid"
        ...     def validate(self, v): return v["n"] >= 1
        ...     def to_json(self, v): return v
        ...     def from_json(self, d): return d
        ...     def describe(self): return {"kind": "grid"}
        ...     def properties(self): return {"cells": int}
        ...     def extract(self, v, prop): return v["n"] * v["n"]
        >>> s = ds.space(ds.param("g").custom(GridType()))
        >>> s = s.require(ds.param("g").prop("cells") <= 4)
        >>> s.is_feasible({"g": {"n": 2}})
        True
        >>> s.is_feasible({"g": {"n": 3}})
        False
        """
        return Prop(self, name)

    # -- domain-level modifiers (last-write-wins) ----------------------------

    def prior(self, dist: Any = None, *, weights: Sequence[float] | None = None) -> Self:
        """Set the parameter's prior, the measure it is sampled from.

        A prior is not a hint: it is the coordinate system the parameter
        lives in. It determines both how the reference sampler draws and
        how a solver perturbs, which is why there is no separate "transform"
        concept. Pass a distribution for a numeric parameter, or `weights=`
        for a categorical or choice.

        Parameters
        ----------
        dist : Any
            A prior for a numeric parameter: `ds.Log()`, `ds.Logit()`,
            `ds.Power(p)`, or any object implementing the external-prior
            protocol (a `ppf`, optionally a `cdf`). Mutually exclusive with
            `weights`.
        weights : Sequence[float] | None
            Relative weights, one per declared value or variant, for a
            categorical, ordinal, or choice parameter. Need not sum to 1.

        Returns
        -------
        Self
            A new builder with the prior set. Last call wins.

        Raises
        ------
        ResolutionError
            If neither or both of `dist` and `weights` are given.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact").prior(weights=[9, 1]),
        ... )
        >>> s.sample_dicts(4, seed=0)
        [{'algo': 'greedy'}, {'algo': 'greedy'}, {'algo': 'greedy'}, {'algo': 'greedy'}]

        `.log_scale()` is shorthand for the equivalent `Log` prior:

        >>> a = ds.space(ds.param("lr").real(1e-4, 1.0).log_scale())
        >>> b = ds.space(ds.param("lr").real(1e-4, 1.0).prior(ds.Log()))
        >>> a.fingerprint() == b.fingerprint()
        True
        """
        if (dist is None) == (weights is None):
            raise ResolutionError(
                f"param {self.path!r}: prior() requires exactly one of a "
                "distribution or weights=..."
            )
        if weights is not None:
            return replace(self, prior_spec=Weights(tuple(weights)))
        return replace(self, prior_spec=dist)

    def default(self, value: Any) -> Self:
        """Set the value used to fill this parameter in when it is unset.

        Defaults are for *completing* a configuration, not for repairing
        one: `Space.apply_defaults()` fills only what is missing and only
        where the parameter is active, and it never clamps a value into
        range.

        Position matters around `.repeat()`. Called before, it sets the
        default for each *element*; called after, it sets the default for
        the *list* as a whole.

        Parameters
        ----------
        value : Any
            The fill value. It must be valid for the parameter's domain.

        Returns
        -------
        Self
            A new builder with the default set. Last call wins.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 8).default(3))
        >>> s.apply_defaults({})
        {'depth': 3}
        >>> s.apply_defaults({"depth": 7})
        {'depth': 7}

        Element default versus list default:

        >>> element = ds.space(ds.param("w").real(0, 1).default(0.5).repeat(3))
        >>> element.apply_defaults({})
        {'w': [0.5, 0.5, 0.5]}
        >>> whole = ds.space(ds.param("w").real(0, 1).repeat(3).default([0.1, 0.2, 0.3]))
        >>> whole.apply_defaults({})
        {'w': [0.1, 0.2, 0.3]}
        """
        # Position-sensitive (API.md, "Modifiers and Layering"): before
        # `.repeat()` this is the element default; after, it's the list
        # default for the *current* (innermost-so-far) repeat level.
        if self.type_kind == "list":
            assert self.lift is not None
            return replace(self, lift=replace(self.lift, list_default=value))
        return replace(self, default_value=value)

    # -- identity-level modifiers (accumulate, except default which is LWW) -

    def when(self, condition: BoolExpr) -> Self:
        """Make the parameter active only when `condition` holds.

        This is how a design space branches. An inactive parameter is
        **absent** from the configuration dict entirely, not `None` and not a
        placeholder, so a config always says exactly what applies to it.

        Calling `.when()` more than once accumulates: the conditions are
        combined with `and`, in call order.

        Parameters
        ----------
        condition : BoolExpr
            A boolean expression over other parameters. A bool parameter
            can be used directly, without comparing it to `True`.

        Returns
        -------
        Self
            A new builder carrying the condition.

        Raises
        ------
        TypeError
            If `condition` is not a boolean expression. In particular
            Python's `and`/`or`/`in` cannot be used, since they would coerce the
            expression to a bool. Use `&`, `|`, `~`, and `.is_in()` instead.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use_cache").bool(),
        ...     ds.param("cache_mb").integer(64, 512).when(ds.param("use_cache")),
        ... )
        >>> s.sample_one(seed=0)
        {'use_cache': False}
        >>> s.sample_one(seed=2)
        {'use_cache': True, 'cache_mb': 198}
        """
        if not isinstance(condition, BoolExpr):
            raise TypeError(".when() requires a BoolExpr condition")
        merged = condition if self.condition is None else (self.condition & condition)
        return replace(self, condition=merged)

    def tag(self, *tags: str) -> Self:
        """Attach labels to the parameter.

        Tags are how you address groups of parameters later, with `.filter()`
        selects by them. They carry no meaning to the library.

        Parameters
        ----------
        *tags : str
            Labels to add. Repeated calls accumulate.

        Returns
        -------
        Self
            A new builder carrying the tags.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lr").real(1e-4, 1.0).tag("optimizer"),
        ...     ds.param("batch").integer(8, 64),
        ... )
        >>> list(s.filter(("optimizer",)).params)
        ['lr']
        """
        return replace(self, tags=self.tags | frozenset(tags))

    def meta(self, mapping: dict[str, Any] | None = None, **kwargs: Any) -> Self:
        """Attach arbitrary metadata to the parameter.

        Metadata is carried through serialization and the fingerprint but
        never interpreted: units, help text, a UI hint, provenance.

        Parameters
        ----------
        mapping : dict[str, Any] | None
            Metadata as a dict, for keys that are not valid identifiers.
        **kwargs : Any
            The same, as keyword arguments.

        Returns
        -------
        Self
            A new builder carrying the metadata, merged over any already
            set.

        Examples
        --------
        >>> p = ds.param("timeout").real(0.1, 60.0).meta(unit="seconds")
        >>> dict(ds.space(p).params["timeout"].meta)
        {'unit': 'seconds'}
        """
        merged = dict(self.meta_map)
        if mapping:
            merged.update(mapping)
        merged.update(kwargs)
        return replace(self, meta_map=MappingProxyType(merged))
