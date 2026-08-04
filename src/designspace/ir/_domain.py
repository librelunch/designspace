"""Domain: type-specific declared value space (API.md, "IR").

M1 covers the scalar rows; M3 adds combinatorial (subset, permutation) and
structural (choice, struct) domains. M4 adds the recursive list (lift)
domain — see DECISIONS.md D-18.

`QuantizedSpec` lives here (not ir/_param.py, where API.md's illustrative
ParamDef listing might suggest) because `ListDomain.element_quantized` needs
it and ir/_param.py already imports from this module — defining it in
ir/_param.py would make that a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from designspace.expr import ArithExpr

if TYPE_CHECKING:
    from designspace.ir._chart import Chart
    from designspace.ir._priors import PriorSpec


@dataclass(frozen=True)
class QuantizedSpec:
    """A grid restricting a numeric domain, set by `.quantized()`.

    Attributes
    ----------
    step : float | None
        Spacing of an arithmetic grid, or `None` if the grid is geometric.
    factor : float | None
        Ratio of a geometric grid, or `None` if the grid is arithmetic.
    include_hi : bool
        Whether the domain's upper bound is a grid point even when the
        spacing would not land on it.
    """

    step: float | None
    factor: float | None
    include_hi: bool = False


@dataclass(frozen=True)
class RealDomain:
    """A continuous interval, declared by `.real()`.

    Attributes
    ----------
    lo : float | ArithExpr
        Lower bound, inclusive. An expression when the bound depends on
        another parameter.
    hi : float | ArithExpr
        Upper bound, inclusive.
    """

    lo: float | ArithExpr
    hi: float | ArithExpr


@dataclass(frozen=True)
class IntegerDomain:
    """A range of integers, declared by `.integer()`.

    Attributes
    ----------
    lo : int | ArithExpr
        Lower bound, inclusive. An expression when the bound depends on
        another parameter.
    hi : int | ArithExpr
        Upper bound, inclusive.
    """

    lo: int | ArithExpr
    hi: int | ArithExpr


@dataclass(frozen=True)
class CategoricalDomain:
    """An unordered set of values, declared by `.categorical()`.

    Attributes
    ----------
    values : tuple[Any, ...]
        The allowed values, in declaration order. Compared with type-tagged
        equality, so `1` and `1.0` are distinct members.
    """

    values: tuple[Any, ...]


@dataclass(frozen=True)
class OrdinalDomain:
    """An ordered set of values, declared by `.ordinal()`.

    Attributes
    ----------
    values : tuple[Any, ...]
        The allowed values in increasing order. Comparisons use this
        position, not the values' own ordering.
    """

    values: tuple[Any, ...]


@dataclass(frozen=True)
class BoolDomain:
    """The two truth values, declared by `.bool()`.

    Carries no fields: a boolean domain has nothing to configure.
    """


@dataclass(frozen=True)
class SubsetDomain:
    """A selection of items, declared by `.subset()`.

    Set semantics: order is irrelevant and there are no duplicates.

    Attributes
    ----------
    items : tuple[Any, ...]
        The items available for selection.
    min_size : int
        Smallest allowed selection.
    max_size : int | None
        Largest allowed selection; `None` means `len(items)`.
    """

    items: tuple[Any, ...]
    min_size: int
    max_size: int | None


@dataclass(frozen=True)
class PermutationDomain:
    """An ordering of all items, declared by `.permutation()`.

    Attributes
    ----------
    items : tuple[Any, ...]
        The items being ordered. Every one appears exactly once in a value.
    """

    items: tuple[Any, ...]


@dataclass(frozen=True)
class ChoiceDomain:
    """A branch among named variants, declared by `.choice()`.

    Attributes
    ----------
    variants : tuple[str, ...]
        Variant names in declaration order, which is the order
        `.prior(weights=...)` aligns to.
    has_payload : frozenset[str]
        The variants carrying parameters of their own. A value for one of
        these nests a payload dict; a value for any other variant is just
        the name.
    """

    variants: tuple[str, ...]
    has_payload: frozenset[str]


@dataclass(frozen=True)
class StructDomain:
    """A named group of parameters, declared by `.space()`.

    Carries no fields: a struct is a pure namespace with no value of its
    own. Its members are separate `ParamDef` entries under a dotted path.
    """


@dataclass(frozen=True)
class CustomDomain:
    """A consumer-supplied type, declared by `.custom()`.

    The value is opaque to the library: no bounds, no chart, no
    domain-level modifiers. Exactly one of `param_type` or the
    `sampler`/`validator` pair is set.

    Attributes
    ----------
    param_type : Any
        The `ParamType` implementation, for the full protocol form.
    sampler : Any
        Callback returning a value given a numpy generator, for the
        shorthand form. Not serializable.
    validator : Any
        Callback returning whether a value is acceptable, for the
        shorthand form. Not serializable.
    """

    param_type: Any = None  # designspace.custom.ParamType | None
    sampler: Any = None  # Callable[[Any], Any] | None (shorthand)
    validator: Any = None  # Callable[[Any], bool] | None (shorthand)


@dataclass(frozen=True)
class SymbolicDomain:
    """A symbolic expression tree, declared by `.symbolic()`.

    Values have the shape `{"ast": <node>, "source": <str>}`, where
    `"source"` is optional and never cross-checked against the tree.
    Non-generative unless `sampler` is given.

    Attributes
    ----------
    signature : Any
        The `Signature`: argument names and types, and the return type.
        Argument names become the tree's usable variables.
    primitives : Any
        The declared vocabulary: operator names, `Primitive` entries with
        arities, and literal ranges.
    max_depth : int
        Maximum tree depth.
    validators : Any
        Extra checks run against the tree. Not serializable.
    sampler : Any
        Makes the parameter generative when present. Not serializable.
    """

    signature: Any  # designspace.program.Signature
    primitives: Any  # tuple[str | Primitive | FloatLiteral | IntLiteral, ...]
    max_depth: int
    validators: Any = None  # tuple[Callable[[Any], bool], ...] | None
    sampler: Any = None  # Callable[[Any], Any] | None


@dataclass(frozen=True)
class CodeDomain:
    """Freeform source code, declared by `.code()`.

    Values have the shape `{"source": <str>}`. Always non-generative:
    there is no `sampler` form, because writing code is out of scope.

    Attributes
    ----------
    signature : Any
        The `Signature` the source must implement.
    description : str
        What the code should do, in prose. Declared metadata for a
        consumer's own backend; never interpreted.
    constraints : Any
        Additional requirements, in prose. Declared metadata.
    examples : Any
        Example implementations or input/output pairs. Declared metadata.
    validators : Any
        Checks run against the source text. Not serializable.
    """

    signature: Any  # designspace.program.Signature
    description: str = ""
    constraints: Any = None  # tuple[str, ...] | None
    examples: Any = None  # tuple[Any, ...] | None
    validators: Any = None  # tuple[Callable[[str], bool], ...] | None


@dataclass(frozen=True)
class ListDomain:
    """A list of independent copies, declared by `.repeat()`.

    Recursive: for a chained or shaped `.repeat(2, 3)`, `element_domain`
    is itself a `ListDomain`.

    Every fact about the element lives here rather than on the enclosing
    `ParamDef`, which stays chartless, so code looking for a lifted
    parameter's chart must read `element_chart`, not `ParamDef.chart`. A
    struct or choice element is the exception: its descendant parameters
    are separate `Space.params` entries under a bracketed path such as
    `"edges[].src"`.

    Attributes
    ----------
    element_kind : str
        The element's type, as a string such as `"real"` or `"choice"`.
    element_domain : Domain
        The element's own domain, or another `ListDomain` when lifts nest.
    element_chart : Chart | None
        The element's chart, if it has one.
    element_prior : PriorSpec | None
        The element's declared prior.
    element_periodic : bool
        Whether the element's domain wraps.
    element_quantized : QuantizedSpec | None
        The element's grid, if quantized.
    element_default : Any
        The default for each element, set by `.default()` before
        `.repeat()`.
    count : int | ArithExpr
        How many elements. An expression here means the length varies
        between configurations.
    list_default : Any
        The default for the list as a whole, set by `.default()` after
        `.repeat()`. Mutually exclusive with `element_default`.
    element_constraints : Any
        Constraints declared on a prebuilt element space, held as a
        template and instantiated per element during evaluation.
    """

    element_kind: str
    element_domain: Domain
    element_chart: Chart | None
    element_prior: PriorSpec | None
    element_periodic: bool
    element_quantized: QuantizedSpec | None
    element_default: Any
    count: int | ArithExpr
    list_default: Any = None
    # `tuple[Constraint, ...]`; typed Any to avoid a cycle (ir/_param.py,
    # where Constraint is defined, imports this module for `Domain`).
    # Constraints declared on a `.space(prebuilt)` element (DECISIONS.md
    # D-20) — a *template*, `"[]"`-prefixed like the element's descendant
    # params, expanded per active instance at evaluation time.
    element_constraints: Any = ()


Domain = (
    RealDomain
    | IntegerDomain
    | CategoricalDomain
    | OrdinalDomain
    | BoolDomain
    | SubsetDomain
    | PermutationDomain
    | ChoiceDomain
    | StructDomain
    | CustomDomain
    | SymbolicDomain
    | CodeDomain
    | ListDomain
)
"""Any parameter domain.

The union of every domain type, and what `ParamDef.domain` holds. Match on
it to handle a parameter by kind; `ParamDef.type_kind` gives the same
information as a string.
"""
