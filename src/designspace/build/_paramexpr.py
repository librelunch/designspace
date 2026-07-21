"""ParamExpr: `ds.param(name)`, dual reference/definition (API.md, "Construction").

Type methods and modifiers are pure recorders: each returns a new, immutable
ParamExpr with pending state updated. No validation happens here — that is
resolve/'s job (the pass pipeline decides what is an error, not the builder).

Internal storage fields are named with a trailing `_spec`/`_value` where the
public modifier method shares the field's natural name (`prior`, `default`,
`quantized`, `meta`) — a dataclass field and a same-named method in one class
body collide (the `def` statement overwrites the field's class-level default),
so the method needs its own name for the state it reads and writes.

The type methods and `.repeat()` live in `build/_views.py`, not here — see
API.md, "Builder view types" and DECISIONS.md D-27/D-28. `ParamExpr` is
the base type: no type methods, no `.repeat()`, but every modifier that stays
universal across param types (`.prior()`, `.default()`, `.when()`, `.tag()`,
`.meta()`), the combinatorial queries, and the `VectorExpr` aggregates
(reference-position usage needs these regardless of which type, if any, the
referenced param turns out to declare).

`type_kind` is a `ClassVar`, not a field (DECISIONS.md D-28): each view in
`build/_views.py` declares its own fixed `type_kind`
(`RealParamExpr.type_kind = "real"`, …), so it is excluded from `__init__`
entirely — `ParamExpr(path="x", type_kind="integer")` is a `TypeError`, not
a value resolution can misread. A bare `ParamExpr`/`FreshParamExpr` (no type
chosen) inherits the base's `None`.
"""

from __future__ import annotations

import builtins
from collections.abc import Sequence
from dataclasses import dataclass, field, fields, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeVar

from designspace.errors import ResolutionError
from designspace.expr import (
    ArithExpr,
    BoolExpr,
    Contains,
    Expr,
    Length,
    PositionOf,
    Size,
    SumOver,
    VectorExpr,
)
from designspace.ir import Domain, QuantizedSpec, Weights

_ViewT = TypeVar("_ViewT", bound="ParamExpr")

# Names `__getattr__` recognizes as *meaningful* misses (DECISIONS.md D-28):
# a second type method (row 2) or a numeric-only modifier misapplied to a
# non-numeric view / written after `.repeat()` (row 11). Both are frozen
# error-table rows (tag R, ResolutionError) and must not degrade to a bare
# AttributeError just because the view narrowing hid the method. Any other
# attribute miss is a genuine typo and stays a plain AttributeError.
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
    }
)
_NUMERIC_ONLY_MODIFIERS = frozenset({"log_scale", "quantized"})


@dataclass(frozen=True)
class _ElementSnapshot:
    """Builder-time closure of "everything left of `.repeat()`" (API.md,
    "Modifiers and Layering" — "The lift"; DECISIONS.md D-18).

    When `element_class is ListParamExpr`, this snapshot describes one
    `.repeat()` level: `element`/`count`/`list_default` are populated and the
    leaf fields below are unused — `element` recurses for a chained/variadic
    `.repeat().repeat()`. Otherwise it describes the element itself (a
    scalar/subset/permutation/choice/struct type), mirroring the same-named
    `ParamExpr` fields it was snapshotted from.

    `element_class` (DECISIONS.md D-28) is the actual view class the element
    was declared with (`type(self)` at `.repeat()`-time — always a concrete
    leaf, since `.repeat()` only exists on typed views) rather than a
    `type_kind` string: resolve/_pipeline.py reconstructs the element by
    calling `element_class(...)` directly, and reads `element_class.type_kind`
    (the view's `ClassVar`) wherever the IR still needs the plain string
    (`ListDomain.element_kind`).
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


@dataclass(frozen=True, eq=False)
class ParamExpr(ArithExpr, BoolExpr, VectorExpr):
    """A parameter, in reference position (bare) or definition position
    (after a type method and any modifiers).

    The base type (API.md, "Builder view types"): every param object,
    whatever its narrowed view, `isinstance`s as `ParamExpr`.
    """

    path: str
    # ClassVar, not a field (DECISIONS.md D-28): excluded from __init__, so
    # ParamExpr(path="x", type_kind="integer") is a TypeError, not a value
    # resolution has to police. Each view in build/_views.py overrides this
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
    # -- structural payloads (M3): raw builder-time state for .choice()/.space(),
    # merged into the flat IR during resolution (resolve/_relocate.py). Not part
    # of `domain` because the domain only needs variant names/has_payload, not
    # the child Spaces themselves.
    choice_payloads: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    struct_space: Any = None  # Space | None; typed Any to avoid an import cycle
    # -- the lift (M4): set once `.repeat()` has been called at least once;
    # `domain`/`prior_spec`/etc above are then reset (the fields this
    # dataclass would otherwise be reusing to mean two different things at
    # once — the class itself, a `ListParamExpr`, already carries the "this
    # is a list" fact via its `type_kind` ClassVar) and every
    # element-describing fact lives in `lift` instead — see
    # `_ElementSnapshot` and DECISIONS.md D-18/D-28.
    lift: _ElementSnapshot | None = None

    @property
    def kind(self) -> str:
        return "ref"

    @property
    def children(self) -> tuple[Expr, ...]:
        return ()

    @property
    def params(self) -> frozenset[str]:
        return frozenset({self.path})

    def _as(self, cls: type[_ViewT], **changes: Any) -> _ViewT:
        """Build a *different* concrete view from `self`'s current field
        values (DECISIONS.md D-28) — `dataclasses.replace()` always returns
        `type(self)`, which is right for ordinary modifiers (they must
        preserve the caller's view) but wrong for the type methods and
        `.repeat()`, which narrow to a specific new view.
        """
        kwargs: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        kwargs.update(changes)
        return cls(**kwargs)

    # `__getattr__` must be invisible to mypy (DECISIONS.md D-28): a class
    # with a *statically visible* `__getattr__` is treated by mypy as
    # accepting any attribute name, which would silently defeat the M4.6
    # gate's static-typing check (`.categorical(...).log_scale()` must be a
    # real `attr-defined` error). `if not TYPE_CHECKING:` makes mypy skip
    # this definition entirely while it still runs normally at import time —
    # confirmed empirically: `attr-defined` fires under mypy, the runtime
    # exception still raises under CPython.
    if not TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            if name in _TYPE_METHOD_NAMES:
                raise ResolutionError(
                    f"param {self.path!r} declares more than one type: exactly "
                    "one type method is allowed (row 2)"
                )
            if name in _NUMERIC_ONLY_MODIFIERS:
                if self.lift is not None:
                    raise ResolutionError(
                        f"param {self.path!r}: {name}() written after .repeat() applies "
                        "to the list, not the element — call it before .repeat() (row 11)"
                    )
                raise ResolutionError(
                    f"param {self.path!r}: {name}() only applies to real or integer "
                    "params (row 11)"
                )
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # `.field()` and the aggregate methods (`.sum()`, `.min()`, `.max()`,
    # `.count_of()`, `.is_sorted()`, `.distinct()`) are inherited from
    # VectorExpr — universal (DECISIONS.md D-28): API.md requires the
    # base to *be* a VectorExpr, and a bare reference (`ds.param("layers")`,
    # before any type is known at the reference site) needs them regardless
    # of what the referenced param turns out to declare.

    def length(self) -> ArithExpr:
        return Length(self)

    # -- combinatorial expression methods: kept universal, not narrowed to
    # SubsetParamExpr/PermutationParamExpr (DECISIONS.md D-28) — validity is
    # a resolution-time check (row 18: `.contains()` on permutation, etc.),
    # not a construction-time one, per M0's "no evaluation, no resolution
    # happens here" and the existing `_require_subset_domain`/
    # `_require_permutation_domain` split in resolve/_expr_checks.py -------

    def contains(self, item: Any) -> BoolExpr:
        return Contains(self, item)

    def size(self) -> ArithExpr:
        return Size(self)

    def sum_over(self, mapping: dict[Any, float]) -> ArithExpr:
        return SumOver(self, MappingProxyType(dict(mapping)))

    def position_of(self, item: Any) -> ArithExpr:
        return PositionOf(self, item)

    # -- domain-level modifiers (last-write-wins) ----------------------------

    def prior(self, dist: Any = None, *, weights: Sequence[float] | None = None) -> Self:
        if (dist is None) == (weights is None):
            raise ResolutionError(
                f"param {self.path!r}: prior() requires exactly one of a "
                "distribution or weights=..."
            )
        if weights is not None:
            return replace(self, prior_spec=Weights(tuple(weights)))
        return replace(self, prior_spec=dist)

    def default(self, value: Any) -> Self:
        # Position-sensitive (API.md, "Modifiers and Layering"): before
        # `.repeat()` this is the element default; after, it's the list
        # default for the *current* (innermost-so-far) repeat level.
        if self.type_kind == "list":
            assert self.lift is not None
            return replace(self, lift=replace(self.lift, list_default=value))
        return replace(self, default_value=value)

    # -- identity-level modifiers (accumulate, except default which is LWW) -

    def when(self, condition: BoolExpr) -> Self:
        if not isinstance(condition, BoolExpr):
            raise TypeError(".when() requires a BoolExpr condition")
        merged = condition if self.condition is None else (self.condition & condition)
        return replace(self, condition=merged)

    def tag(self, *tags: str) -> Self:
        return replace(self, tags=self.tags | frozenset(tags))

    def meta(self, mapping: dict[str, Any] | None = None, **kwargs: Any) -> Self:
        merged = dict(self.meta_map)
        if mapping:
            merged.update(mapping)
        merged.update(kwargs)
        return replace(self, meta_map=MappingProxyType(merged))
