"""`Space`: the resolved container `ds.space()` returns (API.md,
"Construction").

A `Space` holds the resolved parameters, the activity conditions, the
feasibility constraints, the named reference configurations `.anchor()`
adds, and the space-level metadata `.meta()` carries. It is immutable, and
every operation that appears to modify it returns a new one.

`anchors` and `meta_map` default to empty and are omitted from the
fingerprint preimage and the `to_json` document when empty, under
`identity/_ir_codec.py`'s byte-identity guarantee for additive fields.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from designspace.builder._paramexpr import ParamExpr
from designspace.custom import has_cardinality, is_generative
from designspace.display._hooks import displayable
from designspace.expr import ArithExpr, BoolExpr
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
    Condition,
    Constraint,
    ConstraintEval,
    CustomDomain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    PartialEval,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    RemainingDomain,
    SamplingReport,
    StructDomain,
    SubsetDomain,
    SubspaceInfo,
    SymbolicDomain,
    ValidationResult,
)

if TYPE_CHECKING:
    import polars as pl

    import designspace as ds  # noqa: F401
    from designspace.identity._fingerprint import FingerprintScope, FingerprintUnserializable
    from designspace.identity._ir_codec import OnUnserializable
    from designspace.represent._protocol import EncodingRule
    from designspace.represent._representation import Representation

Seed = int | np.random.Generator | None
"""What every sampling surface accepts as its source of randomness.

An `int` seeds a fresh generator reproducibly; a `numpy.random.Generator`
is used as given, which is what to pass when several draws must advance
one stream; `None` draws from fresh entropy and is not reproducible.

Defined alongside `Space` rather than with the sampler, which imports this
module, so that both sides share one upstream definition.
"""


@displayable(
    "designspace.display._space.render_space", "designspace.display._html.render_space_html"
)
@dataclass(frozen=True)
class Space:
    """A resolved design space: the set of configurations you can draw from.

    Build one with `ds.space()`. By the time you hold a `Space`, every
    declaration has been checked: names, references, dependency cycles,
    expression types, domains. The errors you would otherwise meet during
    sampling have already been raised.

    A `Space` is immutable and safe to share across threads. Every operation
    that appears to modify it (`.forbid()`, `.freeze()`, `.select()`,
    `.extend()`, ...) returns a new `Space` and leaves this one untouched,
    which is what makes chaining safe:

    >>> base = ds.space(ds.param("depth").integer(1, 8))
    >>> shallow = base.freeze(depth=2)
    >>> base.cardinality(), shallow.cardinality()
    (8, 1)

    Three ideas explain most of the API. **Inactive means absent:** a
    parameter switched off by a `.when()` condition is missing from the
    config dict entirely, never `None`. **Priors are coordinate systems:**
    every generative parameter resolves to a chart mapping `[0, 1]` onto its
    domain, which is what both the sampler and a solver consume. **Sampling
    is declared measure, not search:** `.sample()` interprets the priors you
    declared; it is not an optimizer.

    Attributes
    ----------
    params : MappingProxyType[str, ParamDef]
        The resolved parameters, keyed by path, in declaration order. This
        is the introspection surface a solver reads. Read-only.
    conditions : tuple[Condition, ...]
        The activity conditions attached by `.when()` and injected by
        struct/choice nesting. Each names the parameter it governs.
    constraints : tuple[Constraint, ...]
        Every constraint on the space, of any kind: `forbid`, `require`,
        `encourage`, `discourage`, and the `bound` constraints that
        expression bounds desugar into. Read `Constraint.kind` rather than
        re-deriving polarity.
    anchors : MappingProxyType[str, Any]
        Named reference configurations added by `.anchor()`, such as an
        incumbent or a shipped baseline. Read-only.
    meta_map : MappingProxyType[str, Any]
        Space-level metadata added by `.meta()`. Carried through
        serialization and never interpreted by the library. Read-only.

    Examples
    --------
    >>> s = ds.space(
    ...     ds.param("algo").categorical("greedy", "exact"),
    ...     ds.param("depth").integer(1, 4),
    ... )
    >>> s.n_params
    2
    >>> s.sample_one(seed=0)
    {'algo': 'exact', 'depth': 2}
    >>> s.is_feasible({"algo": "greedy", "depth": 3})
    True
    """

    params: MappingProxyType[str, ParamDef]
    conditions: tuple[Condition, ...]
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)
    # Named reference configs, from `.anchor()`, and space-level metadata,
    # from `.meta()`. The field is `meta_map` rather than `meta` because a
    # same-named field and method collide, the `def meta` statement
    # overwriting the field's class-level default. `ParamExpr` splits
    # `meta_map` from `.meta()` the same way.
    anchors: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    meta_map: MappingProxyType[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    # A lazily built, cached index backing `_direct_children` below. It is
    # a pure function of `params`, so `compare=False, repr=False` keeps it
    # out of `__eq__` and `__repr__` rather than treating it as part of a
    # space's identity.
    #
    # It is lazy rather than built at each of the dozen construction sites,
    # which are `_emit`, `from_json`, `space_from_ir`, `extend`, `freeze`,
    # the two throwaway `skeleton = Space(...)` spaces in
    # `ops/_structural.py`, and every `dataclasses.replace(space, ...)`
    # call. Each of those would have to remember to rebuild it; laziness
    # requires nothing of them.
    _child_index: dict[str, tuple[str, ...]] | None = field(
        default=None, init=False, compare=False, repr=False
    )

    @property
    def n_params(self) -> int:
        """How many parameters the space declares.

        Counts resolved paths, so a struct's fields and a choice variant's
        payload parameters each count individually.

        Examples
        --------
        >>> ds.space(ds.param("a").integer(0, 1), ds.param("b").bool()).n_params
        2
        """
        return len(self.params)

    @property
    def is_conditional(self) -> bool:
        """Whether any parameter's presence depends on another's value.

        One of the questions a solver asks when negotiating what it can
        handle: a solver with no conditional support can reject the space
        with its own message rather than silently mishandling it.

        Examples
        --------
        >>> ds.space(ds.param("x").real(0, 1)).is_conditional
        False
        >>> ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... ).is_conditional
        True
        """
        return any(p.condition is not None for p in self.params.values())

    @property
    def is_hierarchical(self) -> bool:
        """Whether the space nests, through a struct or a choice.

        Examples
        --------
        >>> ds.space(ds.param("lr").real(1e-3, 1.0)).is_hierarchical
        False
        >>> nested = ds.space(
        ...     ds.param("opt").choice(sgd=ds.space(ds.param("momentum").real(0, 1))),
        ... )
        >>> nested.is_hierarchical
        True
        """
        return any(pd.type_kind in ("space", "choice") for pd in self.params.values())

    @property
    def has_variable_length(self) -> bool:
        """Whether any `.repeat()` has a count that is not a fixed integer.

        A dynamic count means configurations differ in shape from draw to
        draw, so there is no fixed coordinate vector, and
        `.coordinate_paths()` will refuse such a space.

        Examples
        --------
        >>> ds.space(ds.param("w").real(0, 1).repeat(4)).has_variable_length
        False
        >>> ds.space(
        ...     ds.param("n").integer(1, 5),
        ...     ds.param("w").real(0, 1).repeat(ds.param("n")),
        ... ).has_variable_length
        True
        """
        return any(
            pd.type_kind == "list" and _has_dynamic_count(pd.domain)
            for pd in self.params.values()
            if isinstance(pd.domain, ListDomain)
        )

    @property
    def is_finite(self) -> bool:
        """Whether every parameter has finitely many values.

        A cheap check on the declarations alone: it is `False` exactly when
        an unquantized real appears somewhere. It does not consider whether
        a constraint happens to cut a continuous domain down to finitely
        many points. Counting is `.cardinality()`'s job.

        Examples
        --------
        >>> ds.space(ds.param("x").real(0, 1)).is_finite
        False
        >>> ds.space(ds.param("x").real(0, 1).quantized(step=0.25)).is_finite
        True
        """
        return all(_is_finite_domain(pd) for pd in self.params.values())

    @property
    def has_nongenerative_params(self) -> bool:
        """Whether any parameter cannot be sampled from.

        A non-generative parameter can be declared, validated, serialized,
        and reasoned about, but the library cannot invent a value for it,
        so `.sample()` on such a space raises `SamplingError` unless the
        parameter is switched off, frozen, or has a default. Three kinds
        qualify: a `.custom()` type whose `ParamType` provides no `sample`,
        a `.symbolic()` without a `sampler=`, and any `.code()` (which has
        no `sampler=` form at all, since generating source is out of scope).

        Check this before sampling a space you did not build yourself.

        Examples
        --------
        >>> ds.space(ds.param("x").real(0, 1)).has_nongenerative_params
        False
        >>> impl = ds.param("impl").code(
        ...     ds.Signature(args={"x": float}, returns=float),
        ...     description="a fitness function",
        ... )
        >>> ds.space(impl).has_nongenerative_params
        True
        """
        return any(_is_nongenerative_paramdef(pd) for pd in self.params.values())

    def cardinality(self) -> int | None:
        """Count the configurations in the space, or `None` if uncountable.

        The count multiplies out the structure: domain sizes for scalars,
        a sum over variants for a choice, a product over fields for a
        struct, and so on for subsets, permutations, and fixed-count lifts.

        Returns
        -------
        int | None
            The exact number of configurations, or `None` when the space is
            not finitely enumerable. `None` is returned for a continuous
            (unquantized real) domain, an unbounded `.custom()` type, and,
            conservatively, for a space where a parameter carries its own
            `.when()` condition, since counting under arbitrary conditions
            would need constraint solving. `None` therefore means "cannot
            say", not "infinite".

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> s.cardinality()
        8

        Freezing one parameter collapses its factor:

        >>> s.freeze(depth=3).cardinality()
        2

        A continuous domain cannot be counted:

        >>> ds.space(ds.param("x").real(0, 1)).cardinality() is None
        True
        """
        from designspace.resolve._pipeline import check_fully_resolved

        check_fully_resolved(self)
        roots = [p for p in self.params if "." not in p and "[" not in p]
        total = 1
        for path in roots:
            pd = self.params[path]
            if pd.condition is not None:
                return None  # a root param's own .when() -- not structural injection
            n = _param_cardinality(path, pd, self)
            if n is None:
                return None
            total *= n
        return total

    @property
    def subspaces(self) -> dict[str, SubspaceInfo]:
        """The nested regions of the space, keyed by path prefix.

        One entry per choice variant and per struct, each describing which
        parameters live inside it and the condition under which they are
        active. Empty for a flat space.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("opt").choice(
        ...         sgd=ds.space(ds.param("momentum").real(0, 1)),
        ...         adam=ds.space(ds.param("beta").real(0, 1)),
        ...     ),
        ... )
        >>> sorted(s.subspaces)
        ['opt.adam.', 'opt.sgd.']
        >>> s.subspaces["opt.sgd."].member_paths
        ('opt.sgd.momentum',)
        >>> s.subspaces["opt.sgd."].variant_name
        'sgd'
        """
        from designspace.ops._introspect import subspaces as _subspaces

        return _subspaces(self)

    @property
    def dependency_graph(self) -> dict[str, frozenset[str]]:
        """Which parameters each parameter is coupled to.

        Every parameter appears as a key, mapped to the set of parameters
        it shares a condition, constraint, or expression bound with. Use
        `.topological_order` for a valid assignment order.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lo").integer(0, 5),
        ...     ds.param("hi").integer(0, 5),
        ... ).require(ds.param("lo") < ds.param("hi"))
        >>> s.dependency_graph == {"lo": frozenset({"hi"}), "hi": frozenset({"lo"})}
        True
        """
        from designspace.ops._introspect import dependency_graph as _dependency_graph

        return _dependency_graph(self)

    def param_def(self, path: str) -> ParamDef:
        """The parameter definition at a definition or instance path.

        `params` is keyed by definition path, where every element of a
        `.repeat()` shares one entry, as `workers[].timeout_s`. The surfaces
        that name a parameter given a configuration report instance paths
        instead, one per element, as `workers[0].timeout_s`. This resolves
        either form, so what `next_assignable`, `missing_params`,
        `param_activity` and `evaluate_partial` report can be looked up
        directly.

        Parameters
        ----------
        path : str
            A definition path or an instance path.

        Returns
        -------
        ParamDef
            The definition, carrying the chart, prior and grid a caller needs
            in order to choose a value. Every element of a lift shares one
            definition, and equal paths give equal definitions.

        Raises
        ------
        ResolutionError
            When no parameter is defined at the path, naming it.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("n").integer(0, 3),
        ...     ds.param("timeouts").integer(1, 3600).log_scale().repeat(ds.param("n")),
        ... )
        >>> s.param_def("timeouts[0]").type_kind
        'integer'

        The element is described, not the list holding it, so the chart is
        the one a value is drawn through.

        >>> s.param_def("timeouts[0]").chart.from_unit(1.0)
        3600
        >>> s.params["timeouts"].type_kind, s.params["timeouts"].chart
        ('list', None)

        Every element resolves alike.

        >>> s.param_def("timeouts[2]") == s.param_def("timeouts[0]")
        True
        """
        from designspace.errors import ResolutionError
        from designspace.paths import definition_form

        key = path if path in self.params else definition_form(path)
        if key in self.params:
            return self.params[key]
        derived = self._lift_element_def(key)
        if derived is None:
            raise ResolutionError(f"param_def(): no parameter is defined at {path!r}")
        return derived

    def _lift_element_def(self, key: str) -> ParamDef | None:
        """The definition of a scalar lift's element, which `params` does not hold.

        A struct or choice lift stores a template per field, `workers[].timeout_s`,
        and needs nothing here. A scalar lift has no field to store, so its
        element's kind, chart, prior and grid live on the container's
        `ListDomain` instead, and the element path resolves to no entry at all.
        The element is what a caller naming `timeouts[0]` means, so it is
        assembled from those fields rather than the container being handed back
        with the list's own kind and no chart.
        """
        depth = 0
        container = key
        while container.endswith("[]"):
            container = container[:-2]
            depth += 1
        if depth == 0 or container not in self.params:
            return None
        defn = self.params[container]
        domain = defn.domain
        for _ in range(depth):
            if not isinstance(domain, ListDomain):
                return None
            element = domain.element_domain
            if domain.element_kind == "list":
                domain = element
                continue
            return ParamDef(
                path=key,
                type_kind=domain.element_kind,
                domain=element,
                prior=domain.element_prior,
                periodic=domain.element_periodic,
                default=domain.element_default,
                condition=None,
                tags=defn.tags,
                meta=defn.meta,
                chart=domain.element_chart,
                quantized=domain.element_quantized,
            )
        return None

    def param_constraints(self, path: str) -> list[Constraint]:
        """The constraints that mention `path`.

        Parameters
        ----------
        path : str
            A parameter path. Unknown paths yield an empty list rather than
            an error.

        Returns
        -------
        list[Constraint]
            Every constraint referencing the parameter, of any kind. Read
            `Constraint.kind` to tell them apart.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lo").integer(0, 5),
        ...     ds.param("hi").integer(0, 5),
        ... ).require(ds.param("lo") < ds.param("hi"))
        >>> [c.kind for c in s.param_constraints("lo")]
        ['require']
        >>> s.param_constraints("nonexistent")
        []
        """
        return [c for c in self.constraints if path in c.params]

    def param_conditions(self, path: str) -> list[Condition]:
        """The activity conditions involving `path`.

        Returns conditions that govern the parameter as well as conditions
        on *other* parameters that read it, so it answers both "when is
        this active?" and "what does this switch on?".

        Parameters
        ----------
        path : str
            A parameter path.

        Returns
        -------
        list[Condition]
            The matching conditions; empty when the parameter is
            unconditional and governs nothing.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> [c.target for c in s.param_conditions("level")]
        ['level']
        >>> [c.target for c in s.param_conditions("use")]
        ['level']
        """
        return [c for c in self.conditions if c.target == path or path in c.params]

    def _direct_children(self, prefix: str) -> tuple[str, ...]:
        """Template paths one segment below `prefix`.

        This is the traversal primitive every space-guided walker shares.
        `prefix` is `""` for the root, `"algo.svm."` inside a chosen variant,
        or `"edges[]."` inside a lift's element template. It must be `""` or
        end in `"."`, the only two forms any caller constructs; a non-empty
        prefix without a trailing dot, such as `"algo"`, is not a valid query
        and returns `()`.

        Backed by the lazily built, cached `_child_index` rather than a
        per-call scan of `space.params`. The scan is quadratic in param
        count, a struct with many fields paying it once per field, whereas
        the index is one pass, and `Space` is frozen, so caching is safe.
        """
        index = self._child_index
        if index is None:
            index = _build_child_index(self.params)
            object.__setattr__(self, "_child_index", index)
        return index.get(prefix, ())

    def coordinate_paths(self) -> tuple[str, ...]:
        """The fixed leaf layout, for packing a config into a positional vector.

        A solver that works in vectors needs to know which flat keys are
        actual coordinates and which are bookkeeping. For a nested
        `.repeat()`, `x` and `x[0]` are lengths while `x[0][0]` is a
        coordinate. Deriving that by hand fails silently; this derives it.
        The order matches `ds.flatten()` and the DataFrame column order.

        Returns
        -------
        tuple[str, ...]
            The coordinate paths, in layout order.

        Raises
        ------
        ResolutionError
            If the space has no fixed layout, because a dynamic `.repeat()`
            count or a conditional parameter means different configs have
            different shapes. The message names the offending parameter.
            Use `.slice()` or `.freeze()` on the count to fix the layout.

        Examples
        --------
        >>> ds.space(ds.param("w").real(0, 1).repeat(2, 3)).coordinate_paths()
        ('w[0][0]', 'w[0][1]', 'w[0][2]', 'w[1][0]', 'w[1][1]', 'w[1][2]')
        """
        from designspace.config._coordinates import coordinate_paths as _coordinate_paths

        return _coordinate_paths(self)

    def slice(self, values: dict[str, Any] | None = None, **kw: Any) -> Space:
        """Fix values and **remove** those parameters from the space.

        The value is substituted everywhere the parameter was referenced,
        in conditions, constraint expressions and `.repeat()` counts, and any
        structure that becomes determined is then resolved statically: a
        count folds to a plain `int`, a condition that is now always true
        disappears. That static fold is what makes `.slice()` the way to
        turn a variable-length space into one with a fixed layout.

        Contrast `.freeze()`, which keeps the parameter and pins it.

        Parameters
        ----------
        values : dict[str, Any] | None
            Path-to-value mapping. Required for paths containing `.` or
            `[]`, which are not valid keyword names.
        **kw : Any
            The same, as keyword arguments, for simple names.

        Returns
        -------
        Space
            A new space without the sliced parameters.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> list(s.slice(algo="exact").params)
        ['depth']

        Slicing a count fixes the layout of a lift that had none:

        >>> v = ds.space(
        ...     ds.param("n").integer(1, 3),
        ...     ds.param("w").real(0, 1).repeat(ds.param("n")),
        ... )
        >>> v.has_variable_length
        True
        >>> v.slice(n=2).coordinate_paths()
        ('w[0]', 'w[1]')
        """
        from designspace.ops._structural import parse_path_values, slice_space

        return slice_space(self, parse_path_values(values, kw, call=".slice()"))

    def freeze(self, values: dict[str, Any] | None = None, **kw: Any) -> Space:
        """Fix values but **keep** those parameters in the space.

        The parameter stays visible in `.params`, so configs still carry it
        and the path namespace is unchanged, which helps when a consumer's
        schema must not shift. How the value is pinned depends on the kind:
        a real, integer, categorical, or ordinal has its domain narrowed to
        the single value; a bool, choice, subset, permutation, custom, or
        program parameter is pinned by a `require` constraint, which is
        deliberately visible in `.constraints`.

        Contrast `.slice()`, which removes the parameter entirely.

        Parameters
        ----------
        values : dict[str, Any] | None
            Path-to-value mapping. Required for paths containing `.` or
            `[]`.
        **kw : Any
            The same, as keyword arguments, for simple names.

        Returns
        -------
        Space
            A new space in which those parameters admit only the given
            values.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> frozen = s.freeze(depth=3)
        >>> list(frozen.params)
        ['algo', 'depth']
        >>> frozen.cardinality()
        2
        >>> frozen.sample_one(seed=0)
        {'algo': 'exact', 'depth': 3}
        """
        from designspace.ops._structural import freeze as _freeze
        from designspace.ops._structural import parse_path_values

        return _freeze(self, parse_path_values(values, kw, call=".freeze()"))

    def active_subspace(self, config: dict[str, Any]) -> Space:
        """The subspace of parameters active for this configuration.

        Answers "given these choices, what is still in play?". The
        parameters switched off by the config's own values are dropped.

        Parameters
        ----------
        config : dict[str, Any]
            A configuration, complete or partial.

        Returns
        -------
        Space
            A new space containing only the parameters active under
            `config`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> list(s.active_subspace({"use": True}).params)
        ['use', 'level']
        >>> list(s.active_subspace({"use": False}).params)
        ['use']
        """
        from designspace.ops._structural import active_subspace as _active_subspace

        return _active_subspace(self, config)

    def select(self, *paths: str, strict: bool = False) -> Space:
        """Keep only the named parameters and everything beneath them.

        Selection is by definition-path prefix, so naming a struct or a
        choice brings its fields or variants along.

        Parameters
        ----------
        *paths : str
            The parameter paths to keep.
        strict : bool
            By default a constraint that references a dropped parameter is
            itself dropped, with a warning. Set `True` to raise instead.

        Returns
        -------
        Space
            A new space restricted to the selected subtree.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> list(s.select("depth").params)
        ['depth']

        Selecting a choice brings its variants:

        >>> n = ds.space(
        ...     ds.param("opt").choice(sgd=ds.space(ds.param("momentum").real(0, 1))),
        ...     ds.param("seed").integer(0, 9),
        ... )
        >>> list(n.select("opt").params)
        ['opt', 'opt.sgd.momentum']
        """
        from designspace.ops._structural import select as _select

        return _select(self, paths, strict=strict)

    def filter(self, tags: tuple[str, ...] = (), mode: str = "any", strict: bool = False) -> Space:
        """Keep only the parameters carrying the given tags.

        Tags are attached with `.tag()` at declaration time; this is how you
        carve out, say, only the parameters a particular tuning stage owns.

        Parameters
        ----------
        tags : tuple[str, ...]
            The tags to match.
        mode : str
            `"any"` keeps a parameter carrying at least one of `tags`;
            `"all"` requires every one of them.
        strict : bool
            By default a constraint referencing a dropped parameter is
            dropped, with a warning. Set `True` to raise instead.

        Returns
        -------
        Space
            A new space restricted to the matching parameters.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lr").real(1e-4, 1.0).tag("optimizer"),
        ...     ds.param("momentum").real(0, 1).tag("optimizer"),
        ...     ds.param("batch").integer(8, 64),
        ... )
        >>> list(s.filter(("optimizer",)).params)
        ['lr', 'momentum']
        """
        from designspace.ops._structural import filter_space

        return filter_space(self, tags, mode=mode, strict=strict)

    def extend(self, *exprs: ParamExpr) -> Space:
        """Add parameters, keeping everything already declared.

        Conditions, constraints, anchors, and metadata all carry over, and
        the new declarations are resolved against the combined space, so a
        new constraint may reference an existing parameter. `.extend()` with
        no arguments is the identity.

        Parameters
        ----------
        *exprs : ParamExpr
            The parameter builders to add.

        Returns
        -------
        Space
            A new space containing the original parameters followed by the
            new ones.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> list(s.extend(ds.param("seed").integer(0, 9)).params)
        ['depth', 'seed']
        >>> s.extend().fingerprint() == s.fingerprint()
        True
        """
        from designspace.ops._structural import extend as _extend

        return _extend(self, exprs)

    def forbid(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        """Rule out configurations where `conditions` hold.

        A hard constraint naming a **bad** state. Configurations satisfying
        it are infeasible, and the sampler rejects them.

        The four constraint verbs form a 2x2 over hard/soft and
        good-state/bad-state: `.forbid()` and `.require()` are hard,
        `.encourage()` and `.discourage()` are soft annotations that never
        affect feasibility. `forbid(e)` and `require(~e)` are the same
        constraint, down to the fingerprint.

        Parameters
        ----------
        *conditions : BoolExpr
            Boolean expressions over the space's parameters. Several
            arguments are independent constraints, not a conjunction.
        tags : tuple[str, ...]
            Labels for later retrieval or removal via
            `.without_constraints()`.
        meta : dict[str, Any] | None
            Arbitrary metadata carried with the constraint and never
            interpreted by the library.

        Returns
        -------
        Space
            A new space with the constraints added.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... ).forbid(ds.param("algo").is_in("exact") & (ds.param("depth") > 2))
        >>> s.is_feasible({"algo": "greedy", "depth": 4})
        True
        >>> s.is_feasible({"algo": "exact", "depth": 4})
        False
        """
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=True, tags=tags, meta=meta)

    def require(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        """Demand that `conditions` hold.

        A hard constraint naming a **good** state, the mirror of
        `.forbid()`, and often the more natural way to write the same rule.
        Configurations violating it are infeasible.

        Parameters
        ----------
        *conditions : BoolExpr
            Boolean expressions over the space's parameters. Several
            arguments are independent constraints.
        tags : tuple[str, ...]
            Labels for later retrieval or removal.
        meta : dict[str, Any] | None
            Arbitrary metadata carried with the constraint.

        Returns
        -------
        Space
            A new space with the constraints added.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lo").integer(0, 5),
        ...     ds.param("hi").integer(0, 5),
        ... ).require(ds.param("lo") < ds.param("hi"))
        >>> s.is_feasible({"lo": 1, "hi": 4})
        True
        >>> s.is_feasible({"lo": 4, "hi": 1})
        False

        `require` and `forbid` of the negation are the same constraint:

        >>> base = ds.space(ds.param("d").integer(1, 4))
        >>> good = ds.param("d") <= 2
        >>> base.require(good).fingerprint() == base.forbid(~good).fingerprint()
        True
        """
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=True, tags=tags, meta=meta, origin="require")

    def encourage(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        """Prefer configurations where `conditions` hold, without requiring it.

        A soft constraint naming a **good** state. It never changes what is
        feasible, since violating configurations remain valid. It records
        the preference, which `.evaluate_constraints()` reports and which a
        consumer may act on. Pass `reject_soft=True` to a sampler to draw
        only from configurations satisfying the soft constraints too.

        Parameters
        ----------
        *conditions : BoolExpr
            Boolean expressions over the space's parameters.
        tags : tuple[str, ...]
            Labels for later retrieval or removal.
        meta : dict[str, Any] | None
            Arbitrary metadata carried with the constraint.

        Returns
        -------
        Space
            A new space with the soft constraints added.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s = s.encourage(ds.param("depth") <= 2)
        >>> s.is_feasible({"depth": 4})
        True
        >>> ev = s.evaluate_constraints({"depth": 4})[0]
        >>> ev.constraint.kind, ev.satisfied, ev.margin
        ('encourage', False, -2.0)

        Sampling honours it only when asked:

        >>> s.sample_dicts(3, seed=0)
        [{'depth': 3}, {'depth': 2}, {'depth': 1}]
        >>> s.sample_dicts(3, seed=0, reject_soft=True)
        [{'depth': 2}, {'depth': 1}, {'depth': 1}]
        """
        from designspace.resolve._constraints import add_constraints

        return add_constraints(self, conditions, hard=False, tags=tags, meta=meta)

    def discourage(
        self, *conditions: BoolExpr, tags: tuple[str, ...] = (), meta: dict[str, Any] | None = None
    ) -> Space:
        """Prefer configurations where `conditions` do *not* hold.

        A soft constraint naming a **bad** state, the complement of
        `.encourage()`, and identical to `encourage(~e)` down to the
        fingerprint. Like `.encourage()`, it never affects feasibility.

        Parameters
        ----------
        *conditions : BoolExpr
            Boolean expressions over the space's parameters.
        tags : tuple[str, ...]
            Labels for later retrieval or removal.
        meta : dict[str, Any] | None
            Arbitrary metadata carried with the constraint.

        Returns
        -------
        Space
            A new space with the soft constraints added.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> bad = ds.param("depth") > 2
        >>> s.discourage(bad).is_feasible({"depth": 4})
        True
        >>> s.discourage(bad).fingerprint() == s.encourage(~bad).fingerprint()
        True
        """
        from designspace.resolve._constraints import add_constraints

        return add_constraints(
            self, conditions, hard=False, tags=tags, meta=meta, origin="discourage"
        )

    def anchor(self, configs: dict[str, dict[str, Any]]) -> Space:
        """Attach named reference configurations to the space.

        An anchor is a whole config worth carrying with the space: an
        incumbent, a published baseline, the vendor default. Anchors are
        validated on attachment and re-validated by structural operations,
        so they cannot drift out of the space they describe. Roles such as
        "incumbent" are a naming convention, not API.

        Anchors are not defaults: a default is a per-parameter fill value
        used to complete a partial config, an anchor is a named whole. When
        a space has complete defaults, derive rather than duplicate.

        Parameters
        ----------
        configs : dict[str, dict[str, Any]]
            Name-to-configuration mapping. Each configuration must be valid
            for this space.

        Returns
        -------
        Space
            A new space carrying the anchors.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> s = s.anchor(configs={"shipped": {"algo": "greedy", "depth": 1}})
        >>> dict(s.anchors)
        {'shipped': {'algo': 'greedy', 'depth': 1}}
        """
        from designspace.resolve._anchors import add_anchors

        return add_anchors(self, configs)

    def meta(self, mapping: dict[str, Any] | None = None, **kwargs: Any) -> Space:
        """Attach space-level metadata.

        Metadata is carried through serialization and the fingerprint but
        never interpreted. It is where a consumer records provenance, a
        version, an owning team, or anything else the library should not
        have an opinion about.

        Parameters
        ----------
        mapping : dict[str, Any] | None
            Metadata as a dict, for keys that are not valid identifiers.
        **kwargs : Any
            The same, as keyword arguments.

        Returns
        -------
        Space
            A new space carrying the metadata, merged over any already set.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4)).meta(owner="search-team")
        >>> dict(s.meta_map)
        {'owner': 'search-team'}
        """
        from designspace.resolve._anchors import add_meta

        return add_meta(self, mapping, kwargs)

    def map_params(self, fn: Callable[[ParamDef], ParamDef]) -> Space:
        """Rewrite every parameter definition through `fn`.

        The bulk-edit primitive of the metaprogramming surface: `fn` sees
        each `ParamDef` and returns a replacement, and the results are
        re-resolved, so whatever it produces is validated like any other
        declaration. Useful for sweeping transformations: coarsening every
        real to a grid, retagging, relabelling.

        Parameters
        ----------
        fn : Callable[[ParamDef], ParamDef]
            Called once per parameter, in declaration order.

        Returns
        -------
        Space
            A new space built from the rewritten definitions.

        Raises
        ------
        ResolutionError
            If the rewritten definitions do not form a valid space.

        Examples
        --------
        Coarsen every real parameter onto a grid:

        >>> import dataclasses
        >>> s = ds.space(
        ...     ds.param("x").real(0.0, 1.0),
        ...     ds.param("k").integer(1, 3),
        ... )
        >>> def coarsen(pd):
        ...     if pd.type_kind == "real":
        ...         grid = ds.QuantizedSpec(step=0.5, factor=None, include_hi=True)
        ...         return dataclasses.replace(pd, quantized=grid)
        ...     return pd
        >>> s.map_params(coarsen).cardinality()
        9
        """
        from designspace.meta._meta import space_from_ir

        new_params = [fn(pd) for pd in self.params.values()]
        return space_from_ir(
            new_params, self.conditions, self.constraints, dict(self.anchors), dict(self.meta_map)
        )

    def without_constraints(self, tags: tuple[str, ...] = ()) -> Space:
        """Drop the constraints carrying any of `tags`.

        Removes constraints of every kind (`forbid`, `require`,
        `encourage`, `discourage`, and the `bound` constraints that
        expression bounds desugar into) whose own tags intersect `tags`.
        Calling it with no tags removes nothing, since nothing intersects
        the empty set; tag the constraints you intend to be able to lift.

        Parameters
        ----------
        tags : tuple[str, ...]
            The tags to drop by.

        Returns
        -------
        Space
            A new space without those constraints.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s = s.forbid(ds.param("depth") > 2, tags=("perf",))
        >>> len(s.without_constraints(("perf",)).constraints)
        0
        >>> len(s.without_constraints().constraints)
        1
        """
        from designspace.meta._meta import space_from_ir

        tag_set = frozenset(tags)
        kept = [c for c in self.constraints if not (c.tags & tag_set)]
        return space_from_ir(
            self.params, self.conditions, kept, dict(self.anchors), dict(self.meta_map)
        )

    def validate(self, config: dict[str, Any]) -> ValidationResult:
        """Check a configuration against the space, in full.

        Validation covers two separate things: whether each value is
        legal for its parameter (in domain, right type, present exactly
        when active), and whether the constraints hold. The result reports
        both, so a caller can tell a malformed config from a well-formed
        but infeasible one.

        Parameters
        ----------
        config : dict[str, Any]
            The configuration to check. Parameters that are inactive under
            this config must be absent, not `None`.

        Returns
        -------
        ValidationResult
            With `.valid`, the per-parameter `.param_errors`, and the
            per-constraint `.constraint_evals`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> s.validate({"algo": "greedy", "depth": 2}).valid
        True
        >>> bad = s.validate({"algo": "greedy", "depth": 9})
        >>> bad.valid
        False
        >>> bad.param_errors[0].param, bad.param_errors[0].reason
        ('depth', 'out_of_bounds')
        """
        from designspace.validate import validate as _validate

        return _validate(self, config)

    def validate_param(
        self, path: str, value: Any, context: dict[str, Any] | None = None
    ) -> ValidationResult:
        """Check a single value for one parameter.

        The check a driver loop wants: validate an answer as it arrives,
        without waiting for the config to be complete. Pass `context` when
        the parameter's legality depends on other values, such as an
        expression bound or a condition deciding whether it is active.

        Parameters
        ----------
        path : str
            The parameter path to check against.
        value : Any
            The candidate value.
        context : dict[str, Any] | None
            Other values already chosen, used to resolve bounds and
            activity. Optional for a parameter that depends on nothing.

        Returns
        -------
        ValidationResult
            Scoped to this parameter.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s.validate_param("depth", 2).valid
        True
        >>> s.validate_param("depth", 9).param_errors[0].reason
        'out_of_bounds'
        """
        from designspace.validate import validate_param as _validate_param

        return _validate_param(self, path, value, context)

    def is_feasible(self, config: dict[str, Any]) -> bool:
        """Whether the configuration satisfies every hard constraint.

        Feasibility is about constraints only. Soft constraints
        (`.encourage()`, `.discourage()`) never make a config infeasible.

        Parameters
        ----------
        config : dict[str, Any]
            The configuration to check.

        Returns
        -------
        bool
            `True` when no hard constraint is violated.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4)).forbid(ds.param("depth") > 2)
        >>> s.is_feasible({"depth": 1})
        True
        >>> s.is_feasible({"depth": 4})
        False
        """
        from designspace.validate import is_feasible as _is_feasible

        return _is_feasible(self, config)

    def infeasibility_reasons(self, config: dict[str, Any]) -> list[str]:
        """Explain why a configuration is infeasible.

        One human-readable line per violated hard constraint, naming the
        kind and the margin. Empty for a feasible config, which makes it a
        drop-in explanation for a failed `.is_feasible()`.

        Parameters
        ----------
        config : dict[str, Any]
            The configuration to explain.

        Returns
        -------
        list[str]
            The reasons, one per violated hard constraint.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4)).forbid(ds.param("depth") > 2)
        >>> s.infeasibility_reasons({"depth": 4})
        ['forbid violated (margin=2.0): depth > 2']
        >>> s.infeasibility_reasons({"depth": 1})
        []
        """
        from designspace.validate import infeasibility_reasons as _infeasibility_reasons

        return _infeasibility_reasons(self, config)

    def evaluate_constraints(self, config: dict[str, Any]) -> list[ConstraintEval]:
        """Evaluate every constraint against a configuration.

        Unlike `.is_feasible()`, this reports on all constraints, soft
        included, and gives the **margin**, how far the configuration is
        from the boundary, which is what a repair heuristic or a penalty
        method needs. Read `.violated` rather than `.satisfied` unless you
        want to reason about polarity yourself: a `forbid` names a bad
        state, so satisfying it is the unhealthy outcome.

        Parameters
        ----------
        config : dict[str, Any]
            The configuration to evaluate.

        Returns
        -------
        list[ConstraintEval]
            One entry per constraint, or per instance for a constraint
            inside a `.repeat()`.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4)).forbid(ds.param("depth") > 2)
        >>> ev = s.evaluate_constraints({"depth": 4})[0]
        >>> ev.constraint.kind, ev.violated, ev.margin
        ('forbid', True, 2.0)
        """
        from designspace.validate import evaluate_constraints as _evaluate_constraints

        return _evaluate_constraints(self, config)

    def sample_one(self, seed: Seed = None, reject_soft: bool = False) -> dict[str, Any]:
        """Draw a single feasible configuration.

        Values come from the declared priors, and configurations violating
        a hard constraint are rejected and redrawn. Inactive parameters are
        absent from the result.

        Parameters
        ----------
        seed : int | numpy.random.Generator | None
            Seed or generator. Pass an int for a reproducible draw; pass a
            generator to keep drawing from one stream.
        reject_soft : bool
            Also reject configurations that violate a soft constraint.

        Returns
        -------
        dict[str, Any]
            One configuration.

        Raises
        ------
        SamplingError
            If rejection exhausts the retry budget, in which case the
            message names the constraints doing the rejecting, or if it has a
            non-generative parameter with no default.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> s.sample_one(seed=0)
        {'algo': 'exact', 'depth': 2}
        >>> s.sample_one(seed=0) == s.sample_one(seed=0)
        True
        """
        from designspace.sample import sample_one as _sample_one

        return _sample_one(self, seed=seed, reject_soft=reject_soft)

    def sample_dicts(
        self, n: int, seed: Seed = None, reject_soft: bool = False
    ) -> list[dict[str, Any]]:
        """Draw `n` feasible configurations as dicts.

        The dict-shaped counterpart of `.sample()`, which returns a
        DataFrame. This one needs no optional dependency.

        Parameters
        ----------
        n : int
            How many configurations to draw.
        seed : int | numpy.random.Generator | None
            Seed or generator.
        reject_soft : bool
            Also reject configurations that violate a soft constraint.

        Returns
        -------
        list[dict[str, Any]]
            `n` configurations.

        Raises
        ------
        SamplingError
            If rejection exhausts the retry budget, or the space has a
            non-generative parameter with no default.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s.sample_dicts(3, seed=0)
        [{'depth': 3}, {'depth': 2}, {'depth': 1}]
        """
        from designspace.sample import sample_dicts as _sample_dicts

        return _sample_dicts(self, n, seed=seed, reject_soft=reject_soft)

    def sample(self, n: int, seed: Seed = None, reject_soft: bool = False) -> pl.DataFrame:
        """Draw `n` feasible configurations as a polars DataFrame.

        Column names are the path grammar, and inactive parameters come
        back as null. Requires the optional `polars` extra; use
        `.sample_dicts()` if you would rather not take the dependency.

        Parameters
        ----------
        n : int
            How many configurations to draw.
        seed : int | numpy.random.Generator | None
            Seed or generator.
        reject_soft : bool
            Also reject configurations that violate a soft constraint.

        Returns
        -------
        polars.DataFrame
            One row per configuration.

        Raises
        ------
        ImportError
            If polars is not installed. Install `designspace[polars]`.
        SamplingError
            If rejection exhausts the retry budget, or the space has a
            non-generative parameter with no default.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s.sample(3, seed=0).columns  # doctest: +SKIP
        ['depth']
        """
        from designspace.frame import sample_frame as _sample_frame

        return _sample_frame(self, n, seed=seed, reject_soft=reject_soft)

    def sampling_report(
        self, n: int = 1000, seed: Seed = None, tighten_bounds: bool = False
    ) -> SamplingReport:
        """Diagnose how the space behaves under sampling.

        Draws without rejection and reports what happened, which is the
        only way to see the two pathologies that rejection hides: a
        constraint almost never *applicable* (its parameters are usually
        inactive, so it silently governs nothing) and a constraint usually
        violated (rejection is working hard, and the accepted draws are a
        heavily distorted slice of the declared measure).

        It reports; it never repairs, reweights, or suggests.

        Parameters
        ----------
        n : int
            How many draws to base the report on.
        seed : int | numpy.random.Generator | None
            Seed or generator, for a reproducible report.
        tighten_bounds : bool
            Apply the bound-tightening optimization while drawing.

        Returns
        -------
        SamplingReport
            With `.acceptance_rate` and a `.constraints` row per
            constraint. Read `ConstraintReport.violation_rate` for a
            polarity-resolved reading.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4)).forbid(ds.param("depth") > 2)
        >>> report = s.sampling_report(n=100, seed=0)
        >>> report.acceptance_rate
        0.44
        >>> row = report.constraints[0]
        >>> row.applicable, row.violation_rate
        (1.0, 0.56)
        """
        from designspace.sample import sampling_report as _sampling_report

        return _sampling_report(self, n, seed=seed, tighten_bounds=tighten_bounds)

    def apply_defaults(self, config: dict[str, Any]) -> dict[str, Any]:
        """Fill in declared defaults for whatever the config leaves unset.

        Fill-only: a value already present is never overwritten, and a
        parameter that is inactive under the config is never filled. The
        operation is idempotent and monotone, so applying it twice changes
        nothing and it only ever adds keys.

        It is deliberately blind to constraints. It completes a config, it
        does not repair one, and it never silently clamps a value into
        range.

        Parameters
        ----------
        config : dict[str, Any]
            A configuration, possibly partial or empty.

        Returns
        -------
        dict[str, Any]
            A new configuration with defaults filled in.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact").default("greedy"),
        ...     ds.param("depth").integer(1, 4).default(2),
        ... )
        >>> s.apply_defaults({})
        {'algo': 'greedy', 'depth': 2}
        >>> s.apply_defaults({"depth": 4})
        {'algo': 'greedy', 'depth': 4}
        """
        from designspace.defaults import apply_defaults as _apply_defaults

        return _apply_defaults(self, config)

    @property
    def has_complete_defaults(self) -> bool:
        """Whether `apply_defaults({})` yields a complete configuration.

        True when every parameter that would be active has a default, so
        the space describes a usable configuration on its own. This is
        the precondition for deriving an anchor from defaults rather than
        writing one out twice.

        Examples
        --------
        >>> ds.space(ds.param("depth").integer(1, 4)).has_complete_defaults
        False
        >>> ds.space(ds.param("depth").integer(1, 4).default(2)).has_complete_defaults
        True
        """
        from designspace.defaults import apply_defaults as _apply_defaults
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, _apply_defaults(self, {}))

    def evaluate_partial(self, config: dict[str, Any]) -> PartialEval:
        """Evaluate the space against an incomplete configuration.

        The core of building configs interactively. Every parameter gets a
        status (`set`, `active_unset`, `inactive`, or `unknown` when its
        activity cannot be decided yet), and constraints are split into
        those already evaluable and those still pending on unset values.

        Parameters
        ----------
        config : dict[str, Any]
            A partial configuration.

        Returns
        -------
        PartialEval
            With `.param_status`, `.evaluable_constraints`,
            `.pending_constraints`, and `.n_remaining`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> dict(s.evaluate_partial({}).param_status)
        {'use': 'active_unset', 'level': 'unknown'}
        >>> dict(s.evaluate_partial({"use": True}).param_status)
        {'use': 'set', 'level': 'active_unset'}
        """
        from designspace.partial import evaluate_partial as _evaluate_partial

        return _evaluate_partial(self, config)

    def remaining_domain(self, path: str, config: dict[str, Any]) -> RemainingDomain | None:
        """What values are still available for one parameter.

        Narrows the declared domain by whatever the partial config already
        determines, so once `lo` is chosen, the domain left for `hi` under
        `require(lo < hi)` reflects it. Narrowing is **sound but not
        complete**: it reduces a constraint with exactly one unset operand,
        and leaves anything harder alone rather than guessing.

        Parameters
        ----------
        path : str
            The parameter to ask about.
        config : dict[str, Any]
            What has been decided so far.

        Returns
        -------
        RemainingDomain | None
            A per-kind descriptor of what remains, or `None` if the
            parameter is inactive under this config.

        Raises
        ------
        TypeError
            If `path` is empty or names no parameter. This is misuse
            rather than a resolution failure.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("lo").integer(0, 5),
        ...     ds.param("hi").integer(0, 5),
        ... ).require(ds.param("lo") < ds.param("hi"))
        >>> s.remaining_domain("hi", {})
        IntegerRemaining(lo=0, hi=5, grid=None)
        >>> s.remaining_domain("hi", {"lo": 3})
        IntegerRemaining(lo=4, hi=5, grid=None)
        """
        from designspace.partial import remaining_domain as _remaining_domain

        return _remaining_domain(self, path, config)

    def param_activity(self, config: dict[str, Any]) -> dict[str, str]:
        """Which parameters are switched on, off, or not yet decided.

        Three-valued, because a partial config may not yet determine
        activity: `"active"`, `"inactive"`, or `"unknown"`. On a complete
        config it collapses to the first two.

        Parameters
        ----------
        config : dict[str, Any]
            A configuration, complete or partial.

        Returns
        -------
        dict[str, str]
            Path to activity status.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> s.param_activity({})
        {'use': 'active', 'level': 'unknown'}
        >>> s.param_activity({"use": False})
        {'use': 'active', 'level': 'inactive'}
        """
        from designspace.partial import param_activity as _param_activity

        return _param_activity(self, config)

    def is_complete(self, config: dict[str, Any]) -> bool:
        """Whether every active parameter has a value.

        Completeness is about presence, not legality. A complete config
        may still be invalid or infeasible. Note that switching a branch
        off can *complete* a config by removing the need for its
        parameters.

        Parameters
        ----------
        config : dict[str, Any]
            The configuration to check.

        Returns
        -------
        bool
            `True` when nothing active is still unset.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> s.is_complete({"use": False})
        True
        >>> s.is_complete({"use": True})
        False
        """
        from designspace.partial import is_complete as _is_complete

        return _is_complete(self, config)

    def missing_params(self, config: dict[str, Any]) -> list[str]:
        """The active parameters still without a value.

        Parameters
        ----------
        config : dict[str, Any]
            A partial configuration.

        Returns
        -------
        list[str]
            The paths still to be filled. Empty exactly when
            `.is_complete()` is `True`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> s.missing_params({"use": True})
        ['level']
        >>> s.missing_params({"use": False})
        []
        """
        from designspace.partial import missing_params as _missing_params

        return _missing_params(self, config)

    @property
    def topological_order(self) -> list[str]:
        """A parameter order that respects every dependency.

        Assigning in this order guarantees that whatever a parameter's
        activity or bounds depend on has already been decided.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> s.topological_order
        ['use', 'level']
        """
        from designspace.partial import topological_order as _topological_order

        return _topological_order(self)

    def next_assignable(self, config: dict[str, Any]) -> list[str]:
        """The parameters that can be decided right now.

        The driver of an interactive loop: ask what is assignable, assign
        one, ask again. A parameter appears once it is known to be active
        and everything it depends on has a value. The list is empty exactly
        when the config is complete.

        Parameters
        ----------
        config : dict[str, Any]
            What has been decided so far.

        Returns
        -------
        list[str]
            Paths ready to be assigned.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("use").bool(),
        ...     ds.param("level").integer(1, 3).when(ds.param("use")),
        ... )
        >>> s.next_assignable({})
        ['use']
        >>> s.next_assignable({"use": True})
        ['level']
        >>> s.next_assignable({"use": False})
        []
        """
        from designspace.partial import next_assignable as _next_assignable

        return _next_assignable(self, config)

    def to_json(self, on_unserializable: OnUnserializable = "raise") -> dict[str, Any]:
        """Serialize the space to a JSON-compatible dict.

        The document carries the full definition (parameters, domains,
        priors, conditions, constraints, anchors, metadata) and a format
        version. `.from_json()` reverses it.

        Some things cannot cross the wire: a Python callable such as a
        `.custom()` sampler, a validator, or a `ds.value` function. Choose
        what should happen when one is met.

        Parameters
        ----------
        on_unserializable : {"raise", "mark", "drop"}
            `"raise"` fails loudly (the default, since silence here loses
            meaning). `"mark"` replaces the value with a sentinel so the
            shape survives. `"drop"` omits it and records the omission in a
            manifest.

        Returns
        -------
        dict[str, Any]
            The JSON document.

        Raises
        ------
        SerializationError
            If the space contains something unserializable and
            `on_unserializable` is `"raise"`.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> doc = s.to_json()
        >>> sorted(doc)
        ['conditions', 'constraints', 'params', 'version']
        >>> doc["version"]
        1
        >>> ds.Space.from_json(doc).fingerprint() == s.fingerprint()
        True
        """
        from designspace.serialize import to_json as _to_json

        return _to_json(self, on_unserializable=on_unserializable)

    @classmethod
    def from_json(cls, data: dict[str, Any], custom_types: dict[str, Any] | None = None) -> Space:
        """Rebuild a space from a `.to_json()` document.

        The document is re-resolved, not trusted, so a hand-edited or
        corrupted one fails here rather than later.

        Parameters
        ----------
        data : dict[str, Any]
            A document produced by `.to_json()`.
        custom_types : dict[str, Any] | None
            Registry mapping each `type_key` in the document to its
            `ParamType`. Required if the space uses `.custom()` parameters,
            whose behaviour cannot be carried in the document itself.

        Returns
        -------
        Space
            The rebuilt space, fingerprint-equal to the original.

        Raises
        ------
        SerializationError
            If the format version is unknown, or a custom type in the
            document is missing from `custom_types`.
        ResolutionError
            If the document does not describe a valid space.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> ds.Space.from_json(s.to_json()).cardinality()
        4
        """
        from designspace.serialize import from_json as _from_json

        return _from_json(data, custom_types=custom_types)

    def represent(self, *rules: EncodingRule) -> Representation:
        """Build a `Representation`: a morphism onto another space.

        A solver usually cannot work with your space directly. It wants
        unit-interval coordinates, or a flat vector. A `Representation`
        gives it a *target* space that is an ordinary `Space` (so the same
        introspection applies) together with `decode`/`encode` to move
        values between them.

        With no rules you get the **induced** representation: every
        chart-bearing parameter is re-expressed on `[0, 1]`, which is free
        and mechanical because a chart is exactly that map. Supply an
        `EncodingRule` to override particular parameters, such as a custom type
        bridged to coordinates, say. The library ships no chosen encodings
        beyond the induced one; anything opinionated is yours to supply.

        Parameters
        ----------
        *rules : EncodingRule
            Per-parameter overrides, tried in order before the induced
            rule.

        Returns
        -------
        Representation
            With `.target`, `.decode`, `.encode`, `.then`, and `.check`.

        Examples
        --------
        >>> s = ds.space(
        ...     ds.param("algo").categorical("greedy", "exact"),
        ...     ds.param("depth").integer(1, 4),
        ... )
        >>> rep = s.represent()
        >>> [p.type_kind for p in rep.target.params.values()]
        ['categorical', 'real']
        >>> genotype = rep.encode({"algo": "greedy", "depth": 2})
        >>> genotype
        {'algo': 'greedy', 'depth': 0.375}
        >>> rep.decode(genotype)
        {'algo': 'greedy', 'depth': 2}
        """
        from designspace.represent._build import represent as _represent

        return _represent(self, *rules)

    def fingerprint(
        self,
        scope: FingerprintScope = "full",
        on_unserializable: FingerprintUnserializable = "raise",
    ) -> str:
        """A stable digest identifying the space.

        Two spaces with equal fingerprints have identical sets of valid
        configurations, so this is what to key a cache, an experiment
        record, or a results database on. Sugar and its expansion agree, so
        `require(e)` and `forbid(~e)` fingerprint the same, while
        declaration order does not: permuting two parameters gives a
        different digest, because it is a different space.

        The converse does not hold: two spaces may describe the same
        configurations and still fingerprint differently.

        Parameters
        ----------
        scope : {"full", "sampling"}
            Which facts to include. `"full"` is document identity. It
            covers everything, declared constraints, defaults, tags, meta
            and anchors included. `"sampling"` narrows to what determines
            the feasible set, the measure, and chart geometry, so two
            spaces differing only in tags or defaults agree at this scope.
        on_unserializable : {"raise", "mark"}
            What to do with a Python callable in the space. `"raise"` is
            the default; `"mark"` substitutes a sentinel so a space with an
            opaque part can still be identified.

        Returns
        -------
        str
            The digest, prefixed with the format version and the scope.

        Raises
        ------
        SerializationError
            If the space contains something unserializable and
            `on_unserializable` is `"raise"`.

        Examples
        --------
        >>> s = ds.space(ds.param("depth").integer(1, 4))
        >>> s.fingerprint().startswith("1:full:")
        True
        >>> s.fingerprint() == ds.Space.from_json(s.to_json()).fingerprint()
        True

        Order is part of a space's identity:

        >>> a = ds.space(ds.param("x").bool(), ds.param("y").bool())
        >>> b = ds.space(ds.param("y").bool(), ds.param("x").bool())
        >>> a.fingerprint() == b.fingerprint()
        False
        """
        from designspace.identity import fingerprint as _fingerprint

        return _fingerprint(self, scope=scope, on_unserializable=on_unserializable)


def _build_child_index(params: Mapping[str, ParamDef]) -> dict[str, tuple[str, ...]]:
    """Bucket each path in `space.params` by its parent prefix, in one pass.

    The prefix is `path[: path.rfind(".") + 1]`, or `""` when the path is
    dotless. For the `""` and dot-terminated prefixes every caller builds,
    each bucket is exactly the set a `startswith(prefix)` test with a
    dot-free remainder selects. Dict order preserves `params`' declaration
    order, which is already `flatten`'s order and the DataFrame column
    order.
    """
    buckets: dict[str, list[str]] = {}
    for path in params:
        prefix = path[: path.rfind(".") + 1]
        buckets.setdefault(prefix, []).append(path)
    return {prefix: tuple(paths) for prefix, paths in buckets.items()}


def _is_nongenerative_paramdef(pd: ParamDef) -> bool:
    if pd.type_kind == "custom":
        domain = pd.domain
        assert isinstance(domain, CustomDomain)
        return domain.param_type is not None and not is_generative(domain.param_type)
    if pd.type_kind == "symbolic":
        domain = pd.domain
        assert isinstance(domain, SymbolicDomain)
        return domain.sampler is None
    if pd.type_kind == "code":
        return True
    if pd.type_kind == "list":
        domain = pd.domain
        assert isinstance(domain, ListDomain)
        return _is_nongenerative_list_domain(domain)
    return False


def _is_nongenerative_list_domain(domain: ListDomain) -> bool:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _is_nongenerative_list_domain(domain.element_domain)
    if domain.element_kind == "custom":
        assert isinstance(domain.element_domain, CustomDomain)
        elem = domain.element_domain
        return elem.param_type is not None and not is_generative(elem.param_type)
    if domain.element_kind == "symbolic":
        assert isinstance(domain.element_domain, SymbolicDomain)
        return domain.element_domain.sampler is None
    return domain.element_kind == "code"


def _has_dynamic_count(domain: ListDomain) -> bool:
    if isinstance(domain.count, ArithExpr):
        return True
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _has_dynamic_count(domain.element_domain)
    return False


def _is_finite_domain(pd: ParamDef) -> bool:
    if isinstance(pd.domain, RealDomain):
        return pd.quantized is not None
    if isinstance(pd.domain, ListDomain):
        return _is_finite_list_domain(pd.domain)
    return True


def _is_finite_list_domain(domain: ListDomain) -> bool:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return _is_finite_list_domain(domain.element_domain)
    if domain.element_kind == "real":
        assert isinstance(domain.element_domain, RealDomain)
        return domain.element_quantized is not None
    return True


# -- .cardinality() -----------------------------------------------------------


def _condition_matches_injection(actual: BoolExpr | None, expected: BoolExpr | None) -> bool:
    """Whether a descendant's condition is exactly relocation's own injection.

    `actual` is a struct field's or choice variant's descendant's stored,
    folded `.condition`. It matches when the field or variant carries no
    independent `.when()` of its own.

    The comparison is structural rather than by identity, through the
    canonical AST encoder, because `relocate_child`'s choice-variant path
    builds a fresh `and_(...)` composite rather than reusing an existing
    object.

    A condition referencing a `ds.value(...)` makes `encode_expr` raise,
    the node being opaque and no context supplied, rather than return a
    comparable tree. This is a structural-equality check rather than
    serialization, so the error is degraded to an identity comparison rather
    than propagated. An opaque condition can never structurally equal a
    freshly built injection object, so `_struct_cardinality` and
    `_choice_cardinality` correctly read it as not enumerable, returning
    `None`.
    """
    from designspace.errors import SerializationError
    from designspace.identity._tags import encode_expr

    if actual is None and expected is None:
        return True
    if actual is None or expected is None:
        return False
    try:
        return encode_expr(actual) == encode_expr(expected)
    except SerializationError:
        return actual is expected


def _grid_cardinality(lo: float, hi: float, quantized: QuantizedSpec) -> int:
    from designspace.charts._grid import build_grid_shape

    shape = build_grid_shape(lo, hi, quantized.step, quantized.factor, quantized.include_hi)
    return shape.K + 1 + (1 if shape.has_extra_hi else 0)


def _struct_cardinality(path: str, pd: ParamDef, space: Space) -> int | None:
    total = 1
    for child_path in space._direct_children(f"{path}."):
        child_pd = space.params[child_path]
        if not _condition_matches_injection(child_pd.condition, pd.condition):
            return None  # an independent .when() on a struct field
        n = _param_cardinality(child_path, child_pd, space)
        if n is None:
            return None
        total *= n
    return total


def _choice_cardinality(path: str, domain: ChoiceDomain, pd: ParamDef, space: Space) -> int | None:
    from designspace.expr import Compare, Literal
    from designspace.resolve._relocate import and_

    total = 0
    for variant in domain.variants:
        if variant not in domain.has_payload:
            total += 1
            continue
        prefix = f"{path}.{variant}."
        discriminator_eq = Compare("eq", ParamExpr(path=path), Literal(variant))
        expected = and_(pd.condition, discriminator_eq)
        variant_total = 1
        for child_path in space._direct_children(prefix):
            child_pd = space.params[child_path]
            if not _condition_matches_injection(child_pd.condition, expected):
                return None  # an independent .when() on a variant's own field
            n = _param_cardinality(child_path, child_pd, space)
            if n is None:
                return None
            variant_total *= n
        total += variant_total
    return total


def _list_cardinality(path: str, domain: ListDomain, space: Space) -> int | None:
    if isinstance(domain.count, ArithExpr):
        return None  # dynamic (runtime-dependent) count -- not enumerable here
    n = domain.count
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        elem = _list_cardinality(f"{path}[]", domain.element_domain, space)
    elif domain.element_kind in ("space", "choice"):
        elem_pd = ParamDef(
            path=f"{path}[]",
            type_kind=domain.element_kind,
            domain=domain.element_domain,
            prior=None,
            periodic=False,
            default=None,
            condition=None,
            tags=frozenset(),
            meta=MappingProxyType({}),
        )
        elem = _param_cardinality(f"{path}[]", elem_pd, space)
    else:
        elem_pd = ParamDef(
            path=f"{path}[]",
            type_kind=domain.element_kind,
            domain=domain.element_domain,
            prior=None,
            periodic=domain.element_periodic,
            default=None,
            condition=None,
            tags=frozenset(),
            meta=MappingProxyType({}),
            quantized=domain.element_quantized,
        )
        elem = _param_cardinality(f"{path}[]", elem_pd, space)
    if elem is None:
        return None
    return int(elem**n)


def _param_cardinality(path: str, pd: ParamDef, space: Space) -> int | None:
    domain = pd.domain
    if isinstance(domain, RealDomain):
        if pd.quantized is None:
            return None
        assert isinstance(domain.lo, int | float) and isinstance(domain.hi, int | float)
        return _grid_cardinality(float(domain.lo), float(domain.hi), pd.quantized)
    if isinstance(domain, IntegerDomain):
        assert isinstance(domain.lo, int) and isinstance(domain.hi, int)
        if pd.quantized is not None:
            return _grid_cardinality(float(domain.lo), float(domain.hi), pd.quantized)
        return domain.hi - domain.lo + 1
    if isinstance(domain, CategoricalDomain | OrdinalDomain):
        return len(domain.values)
    if isinstance(domain, BoolDomain):
        return 2
    if isinstance(domain, SubsetDomain):
        n_items = len(domain.items)
        max_size = domain.max_size if domain.max_size is not None else n_items
        return sum(math.comb(n_items, k) for k in range(domain.min_size, max_size + 1))
    if isinstance(domain, PermutationDomain):
        return math.factorial(len(domain.items))
    if isinstance(domain, ChoiceDomain):
        return _choice_cardinality(path, domain, pd, space)
    if isinstance(domain, StructDomain):
        return _struct_cardinality(path, pd, space)
    if isinstance(domain, CustomDomain):
        if domain.param_type is not None and has_cardinality(domain.param_type):
            return cast("int | None", domain.param_type.cardinality())
        return None
    if isinstance(domain, SymbolicDomain | CodeDomain):
        # Opaque, with no declared-cardinality capability of any kind,
        # unlike a custom type's optional `.cardinality()`, and so never
        # enumerable.
        return None
    if isinstance(domain, ListDomain):
        return _list_cardinality(path, domain, space)
    return None  # pragma: no cover - unreachable: every Domain variant handled above
