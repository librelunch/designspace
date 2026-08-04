"""Builder view types (API.md, "Builder view types"; DECISIONS.md D-27,
D-28).

`ds.param(name)` returns a `FreshParamExpr` — a `ParamExpr` carrying the 12
type methods (M12 adds `.symbolic()`/`.code()` to M9's `.custom()`-updated
10). Each type method narrows to a type-specific view that omits
the type methods, so a second one is a static type error (and, via
`ParamExpr.__getattr__`, still the path-named row-2 `ResolutionError` at
runtime — never a bare `AttributeError`). `.repeat()` — available on any
typed view, not on `FreshParamExpr` or the base — narrows to `ListParamExpr`,
which re-offers `.repeat()` for nested/variadic lifts.

`TypedParamExpr` is public as of M8 (API.md, "Space — Metaprogramming":
"`TypedParamExpr` is the type-specific builder view for `pd`'s type ... when
this surface lands (M8) it becomes the common base of those views" —
D-27). It was already the shared implementation base of every narrowed view
(as `_TypedParamExpr`); M8 only promotes the name and gives
`ds.param_from_def(pd: ParamDef) -> TypedParamExpr` a base to return.

Class shape, bottom to top:
    ParamExpr                     (build/_paramexpr.py — no type methods, no .repeat();
                                    type_kind: ClassVar[str | None] = None)
    +-- FreshParamExpr            12 type methods only; inherits type_kind = None
    +-- TypedParamExpr            .repeat() only — shared by every narrowed view
        +-- _NumericParamExpr     + .log_scale()/.quantized() — Real/Integer only
        |   +-- RealParamExpr     type_kind = "real"
        |   +-- IntegerParamExpr  type_kind = "integer"
        +-- BoolParamExpr         type_kind = "bool"
        +-- CategoricalParamExpr  type_kind = "categorical"
        +-- OrdinalParamExpr      type_kind = "ordinal"
        +-- SubsetParamExpr       type_kind = "subset"
        +-- PermutationParamExpr  type_kind = "permutation"
        +-- ChoiceParamExpr       type_kind = "choice"
        +-- StructParamExpr       type_kind = "space"
        +-- CustomParamExpr       type_kind = "custom"
        +-- SymbolicParamExpr     type_kind = "symbolic"
        +-- CodeParamExpr         type_kind = "code"
        +-- ListParamExpr         type_kind = "list"

None of these subclasses add fields (API.md: "they add no state beyond
ParamExpr"); each is a thin method surface (plus, on the 13 leaves, a fixed
`type_kind` override) over the same dataclass fields, constructed via
`ParamExpr._as()`. None needs `@dataclass` redecoration — `type_kind` was
declared `ClassVar` on `ParamExpr` itself, so dataclass field processing
never sees it as a field anywhere in the hierarchy; a plain class-attribute
override is enough (DECISIONS.md D-28), and no subclass's `__init__` ever
accepts `type_kind` as an argument.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Sequence
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Self

from designspace.build._paramexpr import ParamExpr, _ElementSnapshot
from designspace.custom import ParamType
from designspace.errors import ResolutionError
from designspace.expr import ArithExpr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
    CustomDomain,
    IntegerDomain,
    Log,
    OrdinalDomain,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
    SymbolicDomain,
)
from designspace.program import FloatLiteral, IntLiteral, Primitive, Signature

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401  (doctest namespace; see conftest.py)


class FreshParamExpr(ParamExpr):
    """What `ds.param(name)` returns: a parameter with no type chosen yet.

    The nine type methods here are the fork in the road — calling one says
    what kind of value the parameter holds and narrows the builder to the
    matching view, which offers only the modifiers valid for that type.
    Calling a second one is an error, caught statically by the type checker
    and at resolution either way.

    Examples
    --------
    >>> ds.param("lr").real(1e-4, 1e-1)
    RealParamExpr(path='lr'...)
    >>> ds.param("algo").categorical("greedy", "exact")
    CategoricalParamExpr(path='algo'...)
    """

    def real(
        self, lo: float | ArithExpr, hi: float | ArithExpr, periodic: builtins.bool = False
    ) -> RealParamExpr:
        """Declare a continuous parameter on `[lo, hi]`.

        Bounds may be expressions over other parameters, which makes the
        domain depend on what has already been chosen.

        Parameters
        ----------
        lo : float | ArithExpr
            Lower bound, inclusive.
        hi : float | ArithExpr
            Upper bound, inclusive.
        periodic : bool
            Treat the domain as a circle, so `lo` and `hi` are the same
            point — for angles and phases.

        Returns
        -------
        RealParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
        >>> round(s.sample_one(seed=0)["lr"], 6)
        0.008145

        A bound can reference another parameter:

        >>> s = ds.space(
        ...     ds.param("lo").real(0.0, 1.0),
        ...     ds.param("hi").real(ds.param("lo"), 1.0),
        ... )
        >>> c = s.sample_one(seed=0)
        >>> c["lo"] <= c["hi"]
        True
        """
        return self._as(RealParamExpr, domain=RealDomain(lo, hi), periodic=periodic)

    def integer(self, lo: int | ArithExpr, hi: int | ArithExpr) -> IntegerParamExpr:
        """Declare an integer parameter on `[lo, hi]`, both inclusive.

        Parameters
        ----------
        lo : int | ArithExpr
            Lower bound, inclusive.
        hi : int | ArithExpr
            Upper bound, inclusive.

        Returns
        -------
        IntegerParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s.cardinality()
        4
        >>> s.sample_one(seed=0)
        {'depth': 3}
        """
        return self._as(IntegerParamExpr, domain=IntegerDomain(lo, hi))

    def categorical(self, *values: Any) -> CategoricalParamExpr:
        """Declare an unordered choice among `values`.

        Use this when the values have no meaningful order — solver names,
        kernel types, strategies. If they *are* ordered, use `.ordinal()`,
        which lets comparisons work. If a value needs parameters of its
        own, use `.choice()`.

        Values are compared with type-tagged equality, so `1` and `1.0` are
        distinct.

        Parameters
        ----------
        *values : Any
            The allowed values. At least one; duplicates are an error.

        Returns
        -------
        CategoricalParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("algo").categorical("greedy", "exact"))
        >>> s.sample_one(seed=0)
        {'algo': 'exact'}
        """
        return self._as(CategoricalParamExpr, domain=CategoricalDomain(tuple(values)))

    def ordinal(self, *values: Any) -> OrdinalParamExpr:
        """Declare an ordered choice among `values`.

        Order is **declaration position**, not the values' natural order —
        so `"low", "medium", "high"` compare as you would want them to.
        That is what distinguishes this from `.categorical()`: comparison
        operators work.

        Parameters
        ----------
        *values : Any
            The allowed values, in increasing order.

        Returns
        -------
        OrdinalParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("effort").ordinal("low", "medium", "high"))
        >>> s = s.require(ds.param("effort") >= "medium")
        >>> s.is_feasible({"effort": "high"})
        True
        >>> s.is_feasible({"effort": "low"})
        False
        """
        return self._as(OrdinalParamExpr, domain=OrdinalDomain(tuple(values)))

    def bool(self) -> BoolParamExpr:
        """Declare a boolean parameter.

        A bool parameter doubles as a condition, so it can be passed
        straight to `.when()` without comparing it to `True`.

        Returns
        -------
        BoolParamExpr
            The narrowed builder, which is also a boolean expression.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use_cache").bool(),
        ...     ds.param("cache_mb").integer(64, 512).when(ds.param("use_cache")),
        ... )
        >>> s.sample_one(seed=0)
        {'use_cache': False}
        """
        return self._as(BoolParamExpr, domain=BoolDomain())

    def subset(
        self, items: Sequence[Any], min_size: int = 0, max_size: int | None = None
    ) -> SubsetParamExpr:
        """Declare a selection of any number of `items`.

        Set semantics: order does not matter and there are no duplicates.
        Query it with `.contains()`, `.size()`, and `.sum_over()`.

        Parameters
        ----------
        items : Sequence[Any]
            The items available for selection.
        min_size : int
            Smallest allowed selection.
        max_size : int | None
            Largest allowed selection; `None` means all of `items`.

        Returns
        -------
        SubsetParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("passes").subset(["inline", "unroll", "vectorize"]))
        >>> s.sample_one(seed=0)
        {'passes': ['unroll', 'vectorize']}
        >>> s.cardinality()
        8
        """
        return self._as(SubsetParamExpr, domain=SubsetDomain(tuple(items), min_size, max_size))

    def permutation(self, items: Sequence[Any]) -> PermutationParamExpr:
        """Declare an ordering of all of `items`.

        Every item appears exactly once; only the order varies. Query a
        position with `.position_of()`.

        Parameters
        ----------
        items : Sequence[Any]
            The items to order.

        Returns
        -------
        PermutationParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(ds.param("order").permutation(["x", "y", "z"]))
        >>> s.sample_one(seed=0)
        {'order': ['z', 'x', 'y']}
        >>> s.cardinality()
        6
        """
        return self._as(PermutationParamExpr, domain=PermutationDomain(tuple(items)))

    def choice(self, *variants: str | tuple[str, Any], **keyword_variants: Any) -> ChoiceParamExpr:
        """Declare alternatives, each optionally carrying its own parameters.

        This is how a design space branches structurally: pick a variant,
        and that variant's parameters become active while the others'
        vanish from the config. Use it over `.categorical()` when the
        alternatives are not interchangeable — when each brings its own
        knobs.

        Three spellings, mixable in one call: a bare string for a variant
        with no payload, a `(name, space)` tuple, or `name=space` as a
        keyword. Use the tuple form when the name is not a valid Python
        identifier.

        Parameters
        ----------
        *variants : str | tuple[str, Any]
            Bare variant names, or `(name, payload_space)` pairs.
        **keyword_variants : Any
            Variants as `name=payload_space`.

        Returns
        -------
        ChoiceParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("opt").choice(
        ...         "adagrad",
        ...         sgd=ds.space(ds.param("momentum").real(0.0, 1.0)),
        ...     ),
        ... )
        >>> list(s.params)
        ['opt', 'opt.sgd.momentum']

        A bare variant is just its name; a variant with a payload nests:

        >>> s.sample_one(seed=2)
        {'opt': 'adagrad'}
        >>> s.sample_one(seed=0)
        {'opt': {'sgd': {'momentum': 0.2697867137638703}}}

        Note that `.params` uses flat definition paths while a config
        nests. `ds.flatten()` and `ds.unflatten()` convert between the two.
        """
        names: list[str] = []
        payloads: dict[str, Any] = {}
        has_payload: set[str] = set()
        for v in variants:
            if isinstance(v, str):
                names.append(v)
            else:
                name, payload = v
                names.append(name)
                if payload is not None:
                    payloads[name] = payload
                    has_payload.add(name)
        for name, payload in keyword_variants.items():
            names.append(name)
            payloads[name] = payload
            has_payload.add(name)
        return self._as(
            ChoiceParamExpr,
            domain=ChoiceDomain(tuple(names), frozenset(has_payload)),
            choice_payloads=MappingProxyType(payloads),
        )

    def custom(
        self,
        param_type: ParamType | None = None,
        sampler: Callable[[Any], Any] | None = None,
        validator: Callable[[Any], builtins.bool] | None = None,
    ) -> CustomParamExpr:
        """Declare a parameter whose values are of your own type.

        The extension point for structure the built-in types cannot
        express — a graph, a topology, a schedule with a global invariant.
        Reach for it when an invariant is genuinely global (connectivity,
        pairwise spacing) or when expressing the structure with primitives
        would leave rejection sampling doing all the work.

        Two forms, and exactly one may be used. Passing `param_type` gives
        the full protocol: the type can serialize, describe itself, expose
        properties to `.prop()`, and optionally sample. Passing `sampler`
        and `validator` is a callback shorthand for quick work — it cannot
        be serialized or fingerprinted.

        Parameters
        ----------
        param_type : ParamType | None
            An object implementing the `ParamType` protocol. Mutually
            exclusive with `sampler`/`validator`.
        sampler : Callable[[Any], Any] | None
            Shorthand form: called with a numpy generator, returns a value.
            Must be given together with `validator`.
        validator : Callable[[Any], bool] | None
            Shorthand form: returns whether a value is acceptable.

        Returns
        -------
        CustomParamExpr
            The narrowed builder.

        Raises
        ------
        ResolutionError
            If both forms are given, neither is, or the shorthand form is
            missing one of its two callbacks.

        Examples
        --------
        >>> class Weekday:
        ...     type_key = "weekday"
        ...     names = ["mon", "tue", "wed"]
        ...     def validate(self, v): return v in self.names
        ...     def to_json(self, v): return v
        ...     def from_json(self, d): return d
        ...     def describe(self): return {"names": self.names}
        ...     def sample(self, rng): return self.names[int(rng.integers(0, 3))]
        >>> s = ds.space(ds.param("day").custom(Weekday()))
        >>> s.sample_one(seed=0)
        {'day': 'wed'}
        >>> s.validate({"day": "sun"}).valid
        False

        The shorthand, for throwaway work:

        >>> quick = ds.param("u").custom(
        ...     sampler=lambda rng: float(rng.random()),
        ...     validator=lambda v: 0.0 <= v <= 1.0,
        ... )
        >>> ds.space(quick).validate({"u": 0.5}).valid
        True
        """
        full_form = param_type is not None
        shorthand_form = sampler is not None or validator is not None
        if full_form and shorthand_form:
            raise ResolutionError(
                f"param {self.path!r}: custom() takes either param_type= "
                "(full protocol) or sampler=/validator= (shorthand), not both"
            )
        if not full_form and not shorthand_form:
            raise ResolutionError(
                f"param {self.path!r}: custom() requires either param_type= "
                "or both sampler= and validator="
            )
        if shorthand_form and (sampler is None or validator is None):
            raise ResolutionError(
                f"param {self.path!r}: custom(sampler, validator) shorthand "
                "requires both sampler and validator"
            )
        return self._as(
            CustomParamExpr,
            domain=CustomDomain(param_type=param_type, sampler=sampler, validator=validator),
        )

    def symbolic(
        self,
        signature: Signature,
        primitives: Sequence[str | Primitive | FloatLiteral | IntLiteral],
        max_depth: int,
        validators: Sequence[Callable[[Any], builtins.bool]] | None = None,
        sampler: Callable[[Any], Any] | None = None,
    ) -> SymbolicParamExpr:
        """Declare a parameter holding a symbolic expression tree.

        For design spaces whose subject is a *formula* — an acquisition
        function, a cooling schedule, a heuristic. The library declares and
        validates the tree's shape but neither generates nor evaluates it:
        tree search is a solver's job, and evaluation is your interpreter's.
        Primitive names are declared metadata; nothing here calls them.

        Values are dicts of the form `{"ast": ..., "source": ...}`, where
        the AST is built from `{"op", "args"}`, `{"var"}`, and `{"const"}`
        nodes. Variables come from `signature.args`.

        The parameter is non-generative unless `sampler` is given.

        Parameters
        ----------
        signature : Signature
            Argument names and types, and the return type. The argument
            names become the usable variables.
        primitives : Sequence[str | Primitive | FloatLiteral | IntLiteral]
            The vocabulary. A bare string names an operator with unchecked
            arity; a `ds.Primitive` declares arity so it can be checked; a
            `ds.FloatLiteral`/`ds.IntLiteral` admits constants in a range.
        max_depth : int
            Maximum tree depth.
        validators : Sequence[Callable[[Any], bool]] | None
            Extra checks run against the tree. Not serializable.
        sampler : Callable[[Any], Any] | None
            Makes the parameter generative. Not serializable.

        Returns
        -------
        SymbolicParamExpr
            The narrowed builder.

        Examples
        --------
        >>> sig = ds.Signature(args={"x": float}, returns=float)
        >>> f = ds.param("f").symbolic(
        ...     sig,
        ...     primitives=["add", "mul", ds.FloatLiteral(-1.0, 1.0)],
        ...     max_depth=3,
        ... )
        >>> s = ds.space(f)
        >>> tree = {"ast": {"op": "add", "args": [{"var": "x"}, {"const": 0.5}]}}
        >>> s.validate({"f": tree}).valid
        True

        An operator outside the declared vocabulary is rejected:

        >>> s.validate({"f": {"ast": {"op": "cos", "args": [{"var": "x"}]}}}).valid
        False
        >>> s.has_nongenerative_params
        True
        """
        return self._as(
            SymbolicParamExpr,
            domain=SymbolicDomain(
                signature=signature,
                primitives=tuple(primitives),
                max_depth=max_depth,
                validators=tuple(validators) if validators is not None else None,
                sampler=sampler,
            ),
        )

    def code(
        self,
        signature: Signature,
        description: str = "",
        constraints: Sequence[str] | None = None,
        examples: Sequence[Any] | None = None,
        validators: Sequence[Callable[[str], builtins.bool]] | None = None,
    ) -> CodeParamExpr:
        """Declare a parameter holding freeform source code.

        For a design space with a slot an external process fills — a
        human, a code-generating model, a library of hand-written
        implementations. The library carries and validates the source; it
        never writes or runs it, so this parameter is **always**
        non-generative and a space containing one cannot be sampled unless
        the parameter is defaulted, frozen, or inactive.

        `description`, `constraints`, and `examples` are declared metadata:
        serialized and fingerprinted, never interpreted. They are there for
        whatever backend does the filling.

        Parameters
        ----------
        signature : Signature
            The interface the source must implement.
        description : str
            What the code should do, in prose.
        constraints : Sequence[str] | None
            Additional requirements, in prose.
        examples : Sequence[Any] | None
            Example implementations or input/output pairs.
        validators : Sequence[Callable[[str], bool]] | None
            Checks run against the source text. Not serializable.

        Returns
        -------
        CodeParamExpr
            The narrowed builder.

        Examples
        --------
        >>> sig = ds.Signature(args={"x": float}, returns=float)
        >>> impl = ds.param("impl").code(sig, description="a fitness function")
        >>> s = ds.space(impl)
        >>> s.validate({"impl": {"source": "def f(x): return x * x"}}).valid
        True
        >>> s.has_nongenerative_params
        True
        """
        return self._as(
            CodeParamExpr,
            domain=CodeDomain(
                signature=signature,
                description=description,
                constraints=tuple(constraints) if constraints is not None else None,
                examples=tuple(examples) if examples is not None else None,
                validators=tuple(validators) if validators is not None else None,
            ),
        )

    def space(self, *exprs: Any) -> StructParamExpr:
        """Declare a struct: a named group of parameters, always active together.

        Use this for pure grouping — when several parameters belong to one
        another and you want them namespaced. Unlike `.choice()`, a struct
        picks nothing: every field is always present.

        Pass a prebuilt `Space` instead of loose parameters when the group
        needs its own constraints, which is the only way to attach
        per-element constraints to a repeated struct.

        Parameters
        ----------
        *exprs : Any
            The field builders, or a single prebuilt `Space`.

        Returns
        -------
        StructParamExpr
            The narrowed builder.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("pid").space(
        ...         ds.param("kp").real(0.0, 1.0),
        ...         ds.param("ki").real(0.0, 1.0),
        ...     ),
        ... )
        >>> list(s.params)
        ['pid', 'pid.kp', 'pid.ki']
        >>> s.sample_one(seed=0)
        {'pid': {'kp': 0.6369616873214543, 'ki': 0.2697867137638703}}

        With its own constraint, via a prebuilt space:

        >>> inner = ds.space(
        ...     ds.param("lo").real(0.0, 1.0),
        ...     ds.param("hi").real(0.0, 1.0),
        ... ).require(ds.param("lo") < ds.param("hi"))
        >>> s = ds.space(ds.param("band").space(inner))
        >>> s.is_feasible({"band": {"lo": 0.2, "hi": 0.8}})
        True
        >>> s.is_feasible({"band": {"lo": 0.8, "hi": 0.2}})
        False
        """
        from designspace.build._space import Space
        from designspace.resolve._pipeline import resolve_space

        # `.space(prebuilt: Space)` (DECISIONS.md D-20/D-15): the only route
        # to per-element constraints on a repeated struct — the inline
        # `.space(*exprs)` form has nowhere to hang a `.forbid()`. A single
        # positional `Space` argument is unambiguous: the inline form's
        # `*exprs` are always bare `ParamExpr`s, never a `Space`.
        if len(exprs) == 1 and isinstance(exprs[0], Space):
            child = exprs[0]
        else:
            child = resolve_space(exprs)
        return self._as(StructParamExpr, domain=StructDomain(), struct_space=child)


class TypedParamExpr(ParamExpr):
    """A parameter whose type has been chosen.

    The common base of every narrowed view, and what `ds.param_from_def()`
    returns. It adds `.repeat()`, the one modifier that applies to every
    element type — including a list, which is how lifts nest.

    Examples
    --------
    >>> isinstance(ds.param("x").real(0, 1), ds.TypedParamExpr)
    True
    >>> isinstance(ds.param("x"), ds.TypedParamExpr)
    False
    """

    def repeat(self, *counts: int | ArithExpr) -> ListParamExpr:
        """Lift the parameter to a list of independent copies.

        Each element is drawn independently from the declared domain. The
        count may be a literal or an expression over another parameter, in
        which case the list's length varies from draw to draw.

        Several counts read as a shape: `.repeat(2, 3)` gives two rows of
        three, the first count outermost.

        Parameters
        ----------
        *counts : int | ArithExpr
            One count per nesting level, outermost first. At least one.

        Returns
        -------
        ListParamExpr
            The list-typed builder. Call `.repeat()` again to nest further.

        Raises
        ------
        ResolutionError
            If no count is given.

        Examples
        --------
        >>> ds.space(ds.param("w").real(0, 1).repeat(3)).sample_one(seed=0)
        {'w': [0.6369616873214543, 0.2697867137638703, 0.04097352393619469]}

        A shape:

        >>> ds.space(ds.param("g").real(0, 1).repeat(2, 2)).sample_one(seed=0)
        {'g': [[0.6369616873214543, 0.2697867137638703], \
[0.04097352393619469, 0.016527635528529094]]}

        A parameter-driven count:

        >>> s = ds.space(
        ...     ds.param("n").integer(1, 3),
        ...     ds.param("w").real(0, 1).repeat(ds.param("n")),
        ... )
        >>> s.sample_one(seed=0)
        {'n': 2, 'w': [0.2697867137638703, 0.04097352393619469]}
        """
        if len(counts) == 0:
            raise ResolutionError(f"param {self.path!r}: repeat() requires at least one count")
        # Variadic sugar: `.repeat(2, 3)` reads as shape (2, 3), first count
        # outermost, desugaring to chained lifts in *reverse* order —
        # `.repeat(3).repeat(2)` (API.md, "The lift").
        ordered = list(reversed(counts))
        result = self._repeat_one(ordered[0])
        for c in ordered[1:]:
            result = result._repeat_one(c)
        return result

    def _repeat_one(self, count: int | ArithExpr) -> ListParamExpr:
        if isinstance(self, ListParamExpr):
            assert self.lift is not None
            inner = self.lift
        else:
            # type(self) is always a concrete leaf here (DECISIONS.md D-28):
            # .repeat() only exists on typed views, and modifiers preserve
            # the caller's class via replace(), so this is exactly the view
            # the element was declared with — e.g. RealParamExpr.
            inner = _ElementSnapshot(
                element_class=type(self),
                domain=self.domain,
                prior_spec=self.prior_spec,
                quantized_spec=self.quantized_spec,
                periodic=self.periodic,
                default_value=self.default_value,
                struct_space=self.struct_space,
                choice_payloads=self.choice_payloads,
            )
        new_lift = _ElementSnapshot(element_class=ListParamExpr, element=inner, count=count)
        return self._as(
            ListParamExpr,
            domain=None,
            prior_spec=None,
            quantized_spec=None,
            periodic=False,
            default_value=None,
            struct_space=None,
            choice_payloads=MappingProxyType({}),
            lift=new_lift,
        )


class _NumericParamExpr(TypedParamExpr):
    """Real/Integer only: `.log_scale()`/`.quantized()` (API.md,
    "Modifiers and Layering"). Absent from every other view — misuse
    (`.categorical(...).log_scale()`) is a static `attr-defined` error and,
    at runtime, `ParamExpr.__getattr__` re-raises it as row 11's
    path-named `ResolutionError` (DECISIONS.md D-28)."""

    def log_scale(self) -> Self:
        """Sample the parameter logarithmically rather than uniformly.

        The right choice whenever a parameter spans orders of magnitude —
        a learning rate, a tolerance, a timeout — so that each decade gets
        equal attention instead of the largest one dominating. Shorthand
        for `.prior(ds.Log())`.

        Returns
        -------
        Self
            A new builder with the log prior set.

        Examples
        --------
        >>> s = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
        >>> round(s.sample_one(seed=0)["lr"], 6)
        0.008145
        >>> a = ds.space(ds.param("lr").real(1e-4, 1e-1).prior(ds.Log()))
        >>> a.fingerprint() == s.fingerprint()
        True
        """
        return self.prior(Log())

    def quantized(
        self,
        step: float | None = None,
        factor: float | None = None,
        include_hi: builtins.bool = False,
    ) -> Self:
        """Restrict the parameter to a grid.

        Give `step` for an arithmetic grid (`lo`, `lo + step`, ...) or
        `factor` for a geometric one (`lo`, `lo * factor`, ...). Quantizing
        a real makes it finite, so the space becomes countable.

        Parameters
        ----------
        step : float | None
            Spacing of an arithmetic grid. Mutually exclusive with
            `factor`.
        factor : float | None
            Ratio of a geometric grid. Mutually exclusive with `step`.
        include_hi : bool
            Include `hi` as a grid point even when the spacing would not
            land on it exactly.

        Returns
        -------
        Self
            A new builder restricted to the grid.

        Examples
        --------
        >>> s = ds.space(ds.param("x").real(0.0, 1.0).quantized(step=0.25, include_hi=True))
        >>> s.cardinality()
        5
        >>> s.sample_one(seed=0)
        {'x': 0.75}

        A geometric grid, for a parameter that scales by doubling:

        >>> b = ds.space(ds.param("batch").real(1.0, 8.0).quantized(factor=2.0))
        >>> b.cardinality()
        4
        >>> sorted({b.sample_one(seed=i)["batch"] for i in range(50)})
        [1.0, 2.0, 4.0, 8.0]
        """
        return replace(self, quantized_spec=QuantizedSpec(step, factor, include_hi))


class RealParamExpr(_NumericParamExpr):
    """A continuous parameter, declared by `.real()`.

    Adds `.log_scale()` and `.quantized()`, which are meaningful only for
    numeric parameters.
    """

    type_kind: ClassVar[str] = "real"


class IntegerParamExpr(_NumericParamExpr):
    """An integer parameter, declared by `.integer()`.

    Adds `.log_scale()` and `.quantized()`, which are meaningful only for
    numeric parameters.
    """

    type_kind: ClassVar[str] = "integer"


class BoolParamExpr(TypedParamExpr):
    """A boolean parameter, declared by `.bool()`.

    Also a boolean expression, so it can be passed straight to `.when()`
    or a constraint without being compared to `True`.
    """

    # Already a BoolExpr transitively (ParamExpr is BoolExpr-inheriting) —
    # API.md: "BoolParamExpr is additionally a BoolExpr (a boolean param
    # is usable directly as a condition)".
    type_kind: ClassVar[str] = "bool"


class CategoricalParamExpr(TypedParamExpr):
    """An unordered choice among values, declared by `.categorical()`.

    Comparison operators are not available; use `.ordinal()` if the values
    have an order.
    """

    type_kind: ClassVar[str] = "categorical"


class OrdinalParamExpr(TypedParamExpr):
    """An ordered choice among values, declared by `.ordinal()`.

    Comparisons follow declaration position, not the values' own ordering.
    """

    type_kind: ClassVar[str] = "ordinal"


class SubsetParamExpr(TypedParamExpr):
    """A selection of items, declared by `.subset()`.

    Query it with `.contains()`, `.size()`, and `.sum_over()`.
    """

    type_kind: ClassVar[str] = "subset"


class PermutationParamExpr(TypedParamExpr):
    """An ordering of items, declared by `.permutation()`.

    Query a position with `.position_of()`.
    """

    type_kind: ClassVar[str] = "permutation"


class ChoiceParamExpr(TypedParamExpr):
    """A branch among alternatives, declared by `.choice()`.

    Each variant may carry its own parameters, which are active only when
    that variant is selected.
    """

    type_kind: ClassVar[str] = "choice"


class StructParamExpr(TypedParamExpr):
    """A named group of parameters, declared by `.space()`.

    Every field is always active together; a struct chooses nothing.
    """

    type_kind: ClassVar[str] = "space"


class CustomParamExpr(TypedParamExpr):
    """`.custom()`'s return type — a thin leaf view. A custom value is
    opaque by design (API.md, "Solver Integration" — the open/closed-world
    split): no domain-specific chainers exist here beyond the universal
    modifiers (`.default()`, `.when()`, `.tag()`, `.meta()`) and `.repeat()`
    (inherited from `TypedParamExpr`). Domain-specific, fluent config lives
    on the author's own `ParamType` object, passed to `.custom()`
    (DECISIONS.md D-45) — not on this view."""

    type_kind: ClassVar[str] = "custom"


class SymbolicParamExpr(TypedParamExpr):
    """`.symbolic()`'s return type — a thin leaf view, mirroring
    `CustomParamExpr` (API.md, "Parameter Types" > "Program"). Non-
    generative unless `sampler=` was given."""

    type_kind: ClassVar[str] = "symbolic"


class CodeParamExpr(TypedParamExpr):
    """`.code()`'s return type — a thin leaf view; always non-generative
    (no `sampler=` form exists for `.code()`)."""

    type_kind: ClassVar[str] = "code"


class ListParamExpr(TypedParamExpr):
    """`.repeat()`'s return type; re-offers `.repeat()` (inherited from
    `TypedParamExpr`) for nested/variadic lifts."""

    type_kind: ClassVar[str] = "list"
