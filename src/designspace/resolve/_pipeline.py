"""The resolve pass pipeline (API.md, "Resolution").

Steps 1 through 8: collect, type-check, desugar, resolve references,
cycle-check, compute bound envelopes (`resolve/_bounds.py`), validate
declarations, build charts, emit IR. Desugaring covers `implies` alone;
`log_scale` resolves to a prior at the builder and leaves nothing to do
here.

Each numbered step is a plain function over the previous step's output.

Structural expansion of a choice or struct happens in step 8, in `_emit`,
rather than earlier. A choice or struct param's own condition is an
ordinary `ParamExpr` entry in `defs`, so steps 4 and 5 resolve and
cycle-check it exactly as they do any other param's `.when()` at this
level. Its payload's descendant params were already fully resolved by their
own earlier `resolve_space` call, made from `.space()` or `.choice()` in
`builder/_paramexpr.py`. They need reprefixing and one folded-in activation
condition, applied by `resolve/_relocate.py`, and never re-validation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.builder._names import check_meta_json_serializable, check_name
from designspace.builder._paramexpr import ParamExpr, _ElementSnapshot
from designspace.builder._space import Space
from designspace.builder._views import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    CodeParamExpr,
    CustomParamExpr,
    IntegerParamExpr,
    ListParamExpr,
    OrdinalParamExpr,
    PermutationParamExpr,
    RealParamExpr,
    StructParamExpr,
    SubsetParamExpr,
    SymbolicParamExpr,
)
from designspace.charts import build_chart, build_grid_shape, grid_membership
from designspace.errors import ResolutionError
from designspace.expr import (
    ArithExpr,
    ArithOp,
    Compare,
    Count,
    CountOf,
    Expr,
    IfInactive,
    Length,
    Literal,
    Max,
    Min,
    PositionOf,
    Prop,
    Size,
    Sum,
    SumOver,
    Value,
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    Chart,
    ChoiceDomain,
    CodeDomain,
    Condition,
    Constraint,
    CustomDomain,
    Domain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    ParamDef,
    ParamError,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
    SymbolicDomain,
    Weights,
)
from designspace.paths import element_prefix, instance_prefix
from designspace.program import FloatLiteral, IntLiteral, Primitive
from designspace.program._validate import program_value_error
from designspace.resolve._bounds import bound_deps, check_bound_refs, compute_bound_envelopes
from designspace.resolve._desugar import desugar_bool
from designspace.resolve._expr_checks import (
    _is_declared,
    check_expr_types,
    check_refs_declared,
    prop_type,
)
from designspace.resolve._relocate import and_, relocate_child

_NON_CHART_KINDS = (
    "subset",
    "permutation",
    "choice",
    "space",
    "custom",
    "list",
    "symbolic",
    "code",
)


def resolve_space(exprs: tuple[ParamExpr, ...]) -> Space:
    defs = _collect(exprs)  # step 1
    _check_types_and_names(defs)  # step 2
    defs = _desugar(defs)  # step 3: implies -> ~left | right. log_scale
    # resolves to a prior at the builder, and lift layer folding already
    # happened there too, in `.repeat()` (builder/_paramexpr.py). This step
    # rewrites `.when()` conditions and nothing else.
    defs_by_path = {d.path: d for d in defs}
    _resolve_condition_refs(defs, defs_by_path)  # step 4
    check_bound_refs(defs, defs_by_path)  # step 4, bound side (rows 6 and 14;
    # eager, with no up-reference tolerance)
    _check_condition_cycles(defs)  # step 5 (condition/bound/repeat-count DAG)
    defs, bound_constraints = compute_bound_envelopes(defs, defs_by_path)  # step 6
    defs_by_path = {d.path: d for d in defs}  # bounds are now plain numbers
    _validate_declarations(defs, defs_by_path)  # step 7 (bounds, weights and
    # the rest). Must precede chart-building, which assumes sane bounds.
    defs = _build_list_domains(defs)  # fold each lift's `_ElementSnapshot`
    # chain into a resolved, chart-carrying `ListDomain`.
    charts = _build_charts(defs)  # step 6, chart side
    space = _emit(defs, charts)  # step 8
    _check_nested_container_lifts(space)  # the compositional route to a
    # two-level container-element lift
    if bound_constraints:
        space = replace(space, constraints=space.constraints + tuple(bound_constraints))
    _validate_list_defaults_deep(space)  # row 21, continued; needs space.params
    return space


def _check_nested_container_lifts(space: Space) -> None:
    """Reject a two-level container-element lift reached compositionally.

    A struct or choice element under more than one `.repeat()` level is
    unsupported, and declaring the inner lift inside the outer lift's
    element `Space` composes to exactly that shape.

    `_validate_lift`'s own guard reads one param's chained
    `_ElementSnapshot` depth, so it catches only `.repeat().repeat()`. The
    compositional route instead produces two separate lift params whose
    merged definition path carries the nesting, as in `"row[].spans"`, which
    is visible only here, after relocation. Unguarded, it falls through into
    machinery that never instantiates the inner elements: a struct lift
    samples empty element dicts, and a lifted choice samples an empty
    payload that `validate()` then accepts.

    The rule is the merged shape rather than the syntax. It fires for a
    param whose own definition path already sits inside a lift element,
    carrying `"[]"`, and which is itself a struct- or choice-elemented lift.
    A scalar lift nested the same way is fine, since scalar, subset and
    permutation elements support arbitrary nesting, as is a struct lift
    inside a plain struct or a choice variant, which is one lift level
    rather than two.
    """
    for path, pd in space.params.items():
        if "[]" not in path or not isinstance(pd.domain, ListDomain):
            continue
        if _innermost_domain_element_kind(pd.domain) in ("space", "choice"):
            raise ResolutionError(
                f"param {path!r}: a struct/choice element nested under more than one "
                ".repeat() level is not supported; scalar/subset/permutation "
                "elements support arbitrary nesting"
            )


def check_fully_resolved(space: Space) -> None:
    """Re-run the deferred row 6, 7 and 14 checks over the merged space.

    A `.when()` condition may reference a param bound in an enclosing scope,
    under API.md's sole scoping rule: resolve the first segment by walking
    up. Such an up-reference cannot be resolved while its payload is
    resolved standalone, so per-scope resolution tolerates it, skipping it
    in `check_refs_declared`, `check_expr_types` and cycle detection. This
    function runs at every terminal entry point, such as sample and
    validate, once every enclosing scope has contributed its params, and
    re-runs the checks strictly over the merged graph:

    - row 6: an up-reference that binds nowhere is a genuine typo and
      raises;
    - row 14: a comparison or arithmetic over a now-visible up-referenced
      param is type-checked, having been skipped standalone;
    - row 7: a cross-scope cycle, formable only through an up-reference plus
      a matching down-reference, is caught here, since per-scope cycle
      detection never sees both edges.

    It also re-checks `space.constraints`, which closes the metaprogramming
    hole. A builder-built space's constraints are already strict at
    `add_constraints`, so this is a confirming no-op for one of those. A
    raw-IR constraint arriving through `space_from_ir` in `meta/_meta.py`
    would otherwise never be expression-checked at all, letting a row 6, 12,
    14, 18 or 29 violation, such as an out-of-range static index or a
    lift-valued boolean operand, reach `sample`, `validate` or `fingerprint`
    silently.

    A space with only local references arrives here already fully checked,
    and every clause below is then a confirming no-op.
    """
    defs_by_path = dict(space.params)
    for cond in space.conditions:
        context = f"param {cond.target!r}"
        check_refs_declared(cond.expr, defs_by_path, context=context)
        check_expr_types(cond.expr, defs_by_path, context=context)
    for c in space.constraints:
        context = f"{c.kind}() constraint"
        check_refs_declared(c.expr, defs_by_path, context=context)
        check_expr_types(c.expr, defs_by_path, context=context)
    _check_domain_carried_refs(space, defs_by_path)
    _check_merged_cycles(space)


def _check_domain_carried_refs(space: Space, defs_by_path: dict[str, ParamDef]) -> None:
    """Rows 6, 12 and 14 over the reference stores a `ListDomain` carries.

    Two of a lift's reference stores live inside the domain rather than on
    the `ParamDef`: the `count` expression and the per-element constraint
    templates.

    Auditing them per-scope, over the child `Space`'s own paths, leaves two
    silent failures once relocation has reprefixed those paths. A dangling
    count reads as Kleene Unknown from inactivity and materializes `[]`. A
    dangling element constraint goes inapplicable under Kleene rule 4, so a
    hard `.forbid()` stops deciding feasibility while `validate()` still
    reports `valid`. Neither is reachable any other way, which is why the
    audit belongs here rather than in a caller.

    This is also what makes deferring a count's up-reference safe. The
    per-scope check tolerates a reference that binds nowhere locally, and
    this pass is where it must finally bind.
    """
    for path, pd in space.params.items():
        domain = pd.domain
        while isinstance(domain, ListDomain):
            _check_count_type(path, domain.count, defs_by_path)
            for c in domain.element_constraints:
                context = f"param {path!r} element {c.kind}() constraint"
                check_refs_declared(c.expr, defs_by_path, context=context)
                check_expr_types(c.expr, defs_by_path, context=context)
            domain = domain.element_domain


def _merged_count_deps(pd: ParamDef) -> frozenset[str]:
    """Repeat-count references across a possibly chained lift.

    Read from the resolved `ListDomain` chain, this is the
    finalization-side counterpart of `_count_deps`' builder-side `.lift`
    walk.
    """
    deps: frozenset[str] = frozenset()
    domain = pd.domain
    while isinstance(domain, ListDomain):
        if isinstance(domain.count, ArithExpr):
            deps = deps | domain.count.params
        domain = domain.element_domain
    return deps


def _check_merged_cycles(space: Space) -> None:
    deps: dict[str, frozenset[str]] = {c.target: c.params for c in space.conditions}
    # A count imposes assignment order exactly as a condition does, so a
    # cross-scope cycle formed through an up-referencing count is row 7. It
    # is visible only here, over the merged graph.
    for path, pd in space.params.items():
        count_deps = _merged_count_deps(pd)
        if count_deps:
            deps[path] = deps.get(path, frozenset()) | count_deps
    for target, target_deps in deps.items():
        if target in target_deps:
            raise ResolutionError(f"param {target!r}: condition/repeat-count references itself")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        if path in visiting:
            raise ResolutionError(f"cycle detected in condition dependencies involving {path!r}")
        visiting.add(path)
        for dep in deps.get(path, frozenset()):
            visit(dep)
        visiting.discard(path)
        done.add(path)

    for target in deps:
        visit(target)


# -- ParamDef <-> ParamExpr view inversion, and re-validation of a ------------
# hand-assembled or rewritten flat IR (API.md, "Space: Metaprogramming":
# "the IR is bidirectional"; "resolution re-validates whatever comes in").
# Shared by `meta/_meta.py` (`param_from_def`, `space_from_ir`) and
# `serialize/_fromjson.py` (chart rebuilding on load). Kept here, next to
# `_build_list_domain` and `_validate_declarations`, whose exact inverse and
# re-check this is.

_VIEW_BY_KIND: dict[str, type[ParamExpr]] = {
    "real": RealParamExpr,
    "integer": IntegerParamExpr,
    "bool": BoolParamExpr,
    "categorical": CategoricalParamExpr,
    "ordinal": OrdinalParamExpr,
    "subset": SubsetParamExpr,
    "permutation": PermutationParamExpr,
    "choice": ChoiceParamExpr,
    "space": StructParamExpr,
    "custom": CustomParamExpr,
    "symbolic": SymbolicParamExpr,
    "code": CodeParamExpr,
}


def param_def_to_view(pd: ParamDef) -> ParamExpr:
    """Invert a resolved `ParamDef` into the `ParamExpr` view that built it.

    This reverses `_emit`'s per-definition half. Structural relocation, the
    other half of `_emit`, folds a struct or choice payload's descendants
    into the flat space and has no single-`ParamDef` inverse: a struct or
    choice view built here is always payload-less, with `struct_space=None`
    or empty `choice_payloads`, because its descendants are separate
    `ParamDef` entries this function never sees.

    That suits every caller. `validate_param_defs` below needs each
    definition's own declaration only, and the public, single-`ParamDef`
    `param_from_def` in `meta/_meta.py` rejects the two container kinds
    before reaching this function rather than returning a view silently
    short of its descendants.
    """
    if pd.type_kind == "list":
        assert isinstance(pd.domain, ListDomain)
        return ListParamExpr(
            path=pd.path,
            condition=pd.condition,
            tags=pd.tags,
            meta_map=pd.meta,
            lift=_list_domain_to_snapshot(pd.domain),
        )
    view_class = _VIEW_BY_KIND[pd.type_kind]
    return view_class(
        path=pd.path,
        domain=pd.domain,
        periodic=pd.periodic,
        prior_spec=pd.prior,
        quantized_spec=pd.quantized,
        default_value=pd.default,
        condition=pd.condition,
        tags=pd.tags,
        meta_map=pd.meta,
    )


def _list_domain_to_snapshot(domain: ListDomain) -> _ElementSnapshot:
    """Inverse of `_build_list_domain`.

    Rebuilds the `_ElementSnapshot` chain `.repeat()` would have produced
    for this resolved `ListDomain`, recursing once per chained lift level as
    `_build_list_domain` does in the other direction. A struct or choice
    element's snapshot is payload-less; see `param_def_to_view`.
    """
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        inner = _list_domain_to_snapshot(domain.element_domain)
    elif domain.element_kind in ("space", "choice"):
        inner = _ElementSnapshot(
            element_class=_VIEW_BY_KIND[domain.element_kind], domain=domain.element_domain
        )
    else:
        inner = _ElementSnapshot(
            element_class=_VIEW_BY_KIND[domain.element_kind],
            domain=domain.element_domain,
            prior_spec=domain.element_prior,
            quantized_spec=domain.element_quantized,
            periodic=domain.element_periodic,
            default_value=domain.element_default,
        )
    return _ElementSnapshot(
        element_class=ListParamExpr,
        element=inner,
        count=domain.count,
        list_default=domain.list_default,
    )


def validate_param_defs(defs_by_path: Mapping[str, ParamDef]) -> None:
    """Re-validate a flat mapping of already-resolved `ParamDef` records.

    Each one's own domain, prior, quantized spec, default, tags and metadata
    are checked. A `.repeat()`-closed "list" kind additionally has its
    element checked, and a dynamic count has the type of the param it
    references checked.

    These are the per-definition checks `_validate_declarations` runs during
    ordinary builder resolution. Row 2's "more than one type" cannot recur
    here, since a `ParamDef.type_kind` string names exactly one kind by
    construction, unlike a hand-built `ParamExpr`. Conditions and cycles are
    `check_fully_resolved`'s separate job, over the merged `Space`.
    """
    views: dict[str, ParamExpr] = {path: param_def_to_view(pd) for path, pd in defs_by_path.items()}
    for path, pd in defs_by_path.items():
        view = views[path]
        if pd.type_kind == "list":
            _validate_lift(view, views)
        else:
            _validate_domain(view)
            _validate_prior(view)
            _validate_quantized(view)
            _validate_default(view)
        _validate_tags_meta(view)


def rebuild_charts(pd: ParamDef) -> ParamDef:
    """Rebuild every chart from its domain, prior and quantized spec.

    Charts are always derived and never trusted from input, so whatever
    `pd.chart` already holds is discarded. Shared by
    `serialize/_fromjson.py`, loading a `to_json` document, and
    `space_from_ir` in `meta/_meta.py`, assembling a `Space` from raw
    `ParamDef` records. Both start from a `pd.chart` that is absent or not
    to be trusted.
    """
    if pd.type_kind == "list":
        assert isinstance(pd.domain, ListDomain)
        return replace(pd, domain=rebuild_list_domain_charts(pd.path, pd.domain))
    chart = build_chart(pd.path, pd.type_kind, pd.domain, pd.prior, pd.quantized)
    return replace(pd, chart=chart)


def rebuild_list_domain_charts(path: str, domain: ListDomain) -> ListDomain:
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        return replace(
            domain, element_domain=rebuild_list_domain_charts(path, domain.element_domain)
        )
    element_chart = (
        build_chart(
            path,
            domain.element_kind,
            domain.element_domain,
            domain.element_prior,
            domain.element_quantized,
        )
        if domain.element_kind in ("real", "integer")
        else None
    )
    return replace(domain, element_chart=element_chart)


def revalidate_space(space: Space) -> Space:
    """Re-run every resolution check over an already-flat `Space`.

    The space was assembled from raw IR by `space_from_ir` in
    `meta/_meta.py` rather than produced by `resolve_space`'s own pipeline.
    "Resolution re-validates whatever comes in" (API.md, "Space:
    Metaprogramming"): a `ParamDef` reaching `space_from_ir` may have come
    from a coarsening `map_params` rewrite, a hand-built registry or a
    foreign document, so it is held to the same standard as one the fluent
    builder produced.

    Returns `space`, for chaining.
    """
    validate_param_defs(space.params)
    _validate_list_defaults_deep(space)
    check_fully_resolved(space)
    return space


def _desugar(defs: tuple[ParamExpr, ...]) -> tuple[ParamExpr, ...]:
    return tuple(
        replace(d, condition=desugar_bool(d.condition)) if d.condition is not None else d
        for d in defs
    )


def _build_list_domains(defs: tuple[ParamExpr, ...]) -> tuple[ParamExpr, ...]:
    """Fold each lift's `_ElementSnapshot` chain into a resolved `ListDomain`.

    The innermost element's chart is built along the way. `build_chart` is
    oblivious to lifts, needing only a path, `type_kind`, domain, prior and
    quantized spec, all of which the snapshot carries.

    Runs after `_validate_lift` has confirmed the element's bounds and
    priors are sane, matching the order scalar params already use: validate
    before chart-building.
    """
    return tuple(
        replace(d, domain=_build_list_domain(d.path, d.lift)) if d.lift is not None else d
        for d in defs
    )


def _build_list_domain(path: str, lift: _ElementSnapshot) -> ListDomain:
    assert lift.element_class is ListParamExpr
    assert lift.count is not None
    inner = lift.element
    assert inner is not None
    if inner.element_class is ListParamExpr:
        return ListDomain(
            element_kind="list",
            element_domain=_build_list_domain(path, inner),
            element_chart=None,
            element_prior=None,
            element_periodic=False,
            element_quantized=None,
            element_default=None,
            count=lift.count,
            list_default=lift.list_default,
        )
    assert inner.domain is not None
    inner_kind = inner.element_class.type_kind
    assert inner_kind is not None  # every concrete leaf but FreshParamExpr sets one
    element_chart = (
        build_chart(path, inner_kind, inner.domain, inner.prior_spec, inner.quantized_spec)
        if inner_kind in ("real", "integer")
        else None
    )
    return ListDomain(
        element_kind=inner_kind,
        element_domain=inner.domain,
        element_chart=element_chart,
        element_prior=inner.prior_spec,
        element_periodic=inner.periodic,
        element_quantized=inner.quantized_spec,
        element_default=inner.default_value,
        count=lift.count,
        list_default=lift.list_default,
    )


def _build_charts(defs: tuple[ParamExpr, ...]) -> dict[str, Chart | None]:
    charts: dict[str, Chart | None] = {}
    for d in defs:
        assert d.type_kind is not None and d.domain is not None
        if d.type_kind in _NON_CHART_KINDS:
            charts[d.path] = None
            continue
        charts[d.path] = build_chart(d.path, d.type_kind, d.domain, d.prior_spec, d.quantized_spec)
    return charts


# -- step 1: collect ---------------------------------------------------------


def _collect(exprs: tuple[ParamExpr, ...]) -> tuple[ParamExpr, ...]:
    for e in exprs:
        if not isinstance(e, ParamExpr):
            raise ResolutionError(
                f"ds.space() requires ParamExpr definitions, got {type(e).__name__}"
            )
    return tuple(exprs)


# -- step 2: type-check -------------------------------------------------------


def _check_types_and_names(defs: tuple[ParamExpr, ...]) -> None:
    seen: set[str] = set()
    for d in defs:
        check_name(d.path, what="param name")
        if d.path in seen:
            raise ResolutionError(f"duplicate param name {d.path!r} in this scope")
        seen.add(d.path)

        # "More than one type", row 2's other half, is structurally
        # unreachable here: type_kind is a ClassVar fixed by whichever view
        # class built `d`, so no runtime state is left to misrepresent it,
        # fluent or hand-built alike. `ParamExpr(type_kind=...)` is a
        # TypeError before this function would see the object. Only "no type
        # chosen", a bare FreshParamExpr or ParamExpr reaching resolution,
        # remains checkable.
        if d.type_kind is None:
            raise ResolutionError(
                f"param {d.path!r} has no type: call exactly one of "
                ".real/.integer/.categorical/.ordinal/.bool"
            )
        _check_modifier_placement(d)


def _check_modifier_placement(d: ParamExpr) -> None:
    numeric = d.type_kind in ("real", "integer")
    weighted = d.type_kind in ("categorical", "ordinal", "bool", "choice", "subset")

    if d.prior_spec is not None:
        if d.lift is not None:
            raise ResolutionError(
                f"param {d.path!r}: prior()/log_scale() written after .repeat() applies "
                "to the list, not the element; call it before .repeat()"
            )
        if isinstance(d.prior_spec, Weights) and not weighted:
            raise ResolutionError(
                f"param {d.path!r}: prior(weights=...) only applies to "
                "categorical, ordinal, bool, choice, or subset params"
            )
        if not isinstance(d.prior_spec, Weights) and not numeric:
            raise ResolutionError(
                f"param {d.path!r}: prior(dist) only applies to real or integer params"
            )
    if d.quantized_spec is not None:
        if d.lift is not None:
            raise ResolutionError(
                f"param {d.path!r}: quantized() written after .repeat() applies to the "
                "list, not the element; call it before .repeat()"
            )
        if not numeric:
            raise ResolutionError(
                f"param {d.path!r}: quantized() only applies to real or integer params"
            )


# -- step 4: resolve references (+ row-14 operand type-checking) -------------


def _resolve_condition_refs(
    defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]
) -> None:
    for d in defs:
        if d.condition is None:
            continue
        context = f"param {d.path!r}"
        # Condition up-references to an enclosing scope's params, under
        # API.md's sole scoping rule, are tolerated here and re-checked at
        # finalization over the merged space, once every enclosing scope has
        # contributed its params.
        check_refs_declared(d.condition, defs_by_path, context=context, tolerate_undeclared=True)
        check_expr_types(d.condition, defs_by_path, context=context, tolerate_undeclared=True)


# -- step 5: cycle detection ---------------------------------------------------


def _count_deps(lift: _ElementSnapshot | None) -> frozenset[str]:
    """Repeat-count references across a possibly chained lift.

    These join the same dependency graph as conditions: a count must be
    known before this param's instances can be materialized, just as a
    condition must be known before activity can be decided.
    """
    deps: frozenset[str] = frozenset()
    while lift is not None and lift.element_class is ListParamExpr:
        if isinstance(lift.count, ArithExpr):
            deps = deps | lift.count.params
        lift = lift.element
    return deps


def _check_condition_cycles(defs: tuple[ParamExpr, ...]) -> None:
    """Row 7: a cycle in the condition, bound and repeat-count graph.

    Also fires when a param's condition, bounds or repeat count references
    itself. Runs before bound envelopes are computed, since
    `compute_bound_envelopes`' `envelope_of` is a memoized recursion that
    assumes this already holds.
    """
    deps: dict[str, frozenset[str]] = {
        d.path: (d.condition.params if d.condition is not None else frozenset())
        | _count_deps(d.lift)
        | bound_deps(d)
        for d in defs
    }
    for path, own_deps in deps.items():
        if path in own_deps:
            raise ResolutionError(f"param {path!r}: condition/bound/repeat-count references itself")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        if path in visiting:
            raise ResolutionError(
                f"cycle detected in condition/bound dependencies involving {path!r}"
            )
        visiting.add(path)
        for dep in deps[path]:
            # A non-local dependency is an up-reference into an enclosing
            # scope. It has no node here, so skip it; a cross-scope cycle
            # through it is caught at finalization over the merged graph.
            if dep in deps:
                visit(dep)
        visiting.discard(path)
        done.add(path)

    for d in defs:
        visit(d.path)


# -- step 7: validate declarations --------------------------------------------


def _validate_declarations(defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]) -> None:
    for d in defs:
        if d.lift is not None:
            _validate_lift(d, defs_by_path)
        else:
            _validate_domain(d)
            _validate_prior(d)
            _validate_quantized(d)
            _validate_default(d)
        _validate_tags_meta(d)


def _validate_domain(d: ParamExpr) -> None:
    domain = d.domain
    if isinstance(domain, RealDomain | IntegerDomain):
        _check_bounds(d.path, domain.lo, domain.hi)
    elif isinstance(domain, CategoricalDomain):
        _check_distinct_values(d.path, domain.values, what="categorical values")
        _check_no_shared_string_image(d.path, domain.values)
    elif isinstance(domain, OrdinalDomain):
        _check_distinct_values(d.path, domain.values, what="ordinal values")
    elif isinstance(domain, BoolDomain):
        pass
    elif isinstance(domain, SubsetDomain):
        _check_distinct_values(d.path, domain.items, what="subset items")
        _check_subset_size_bounds(d.path, domain)
    elif isinstance(domain, PermutationDomain):
        _check_distinct_values(d.path, domain.items, what="permutation items")
    elif isinstance(domain, ChoiceDomain):
        _check_choice_variants(d.path, domain)
    elif isinstance(domain, StructDomain):
        pass
    elif isinstance(domain, CustomDomain):
        _check_custom_domain(d.path, domain)
    elif isinstance(domain, SymbolicDomain):
        _check_symbolic_domain(d.path, domain)
    elif isinstance(domain, CodeDomain):
        _check_code_domain(d.path, domain)


def _check_custom_domain(path: str, domain: CustomDomain) -> None:
    """A row-2-adjacent construction check, not a numbered error row.

    `FreshParamExpr.custom` in `builder/_views.py` already rejects a
    malformed `.custom()` call at the builder. This mirrors that check for a
    programmatically built `CustomDomain` reaching resolution another way,
    through `ds.param_from_def` or `space_from_ir`.
    """
    full = domain.param_type is not None
    shorthand = domain.sampler is not None or domain.validator is not None
    if full and shorthand:
        raise ResolutionError(
            f"param {path!r}: custom domain sets both param_type and "
            "sampler/validator; exactly one form is allowed"
        )
    if not full and not shorthand:
        raise ResolutionError(
            f"param {path!r}: custom domain must set param_type or (sampler, validator)"
        )
    if shorthand and (domain.sampler is None or domain.validator is None):
        raise ResolutionError(f"param {path!r}: custom(sampler, validator) shorthand requires both")


def _check_program_signature(path: str, signature: Any) -> None:
    for name in signature.args:
        if not name.isidentifier():
            raise ResolutionError(
                f"param {path!r}: symbolic()/code() signature arg name {name!r} "
                "is not a valid identifier"
            )


def _check_literal_bounds(path: str, lo: Any, hi: Any) -> None:
    if isinstance(lo, bool) or isinstance(hi, bool):
        raise ResolutionError(f"param {path!r}: literal bounds must be numeric, not bool")
    if isinstance(lo, float) and not math.isfinite(lo):
        raise ResolutionError(f"param {path!r}: literal lo={lo!r} must be finite")
    if isinstance(hi, float) and not math.isfinite(hi):
        raise ResolutionError(f"param {path!r}: literal hi={hi!r} must be finite")
    if lo > hi:
        raise ResolutionError(f"param {path!r}: literal lo={lo!r} > hi={hi!r}")


def _check_primitive_arity(path: str, prim: Primitive) -> None:
    arity = prim.arity
    if isinstance(arity, bool):
        raise ResolutionError(f"param {path!r}: Primitive {prim.name!r} arity must not be bool")
    if isinstance(arity, int):
        if arity < 0:
            raise ResolutionError(f"param {path!r}: Primitive {prim.name!r} arity must be >= 0")
        return
    valid_shape = (
        isinstance(arity, tuple)
        and len(arity) == 2
        and isinstance(arity[0], int)
        and not isinstance(arity[0], bool)
        and (arity[1] is None or (isinstance(arity[1], int) and not isinstance(arity[1], bool)))
    )
    if not valid_shape:
        raise ResolutionError(
            f"param {path!r}: Primitive {prim.name!r} arity must be an int or an (lo, hi) tuple"
        )
    lo, hi = arity
    if lo < 0:
        raise ResolutionError(f"param {path!r}: Primitive {prim.name!r} arity lo must be >= 0")
    if hi is not None and hi < lo:
        raise ResolutionError(
            f"param {path!r}: Primitive {prim.name!r} arity hi ({hi}) < lo ({lo})"
        )


def _check_program_primitives(path: str, primitives: Any) -> None:
    """Row 15's declaration checks over a primitive set.

    There is no fixed built-in vocabulary: any non-empty string names a
    primitive. The checks are therefore shape, duplicates and arity, never
    membership in a name set.
    """
    seen: set[str] = set()
    for prim in primitives:
        if isinstance(prim, str):
            if not prim:
                raise ResolutionError(f"param {path!r}: primitive name must not be empty")
            name = prim
        elif isinstance(prim, Primitive):
            if not prim.name:
                raise ResolutionError(f"param {path!r}: Primitive name must not be empty")
            _check_primitive_arity(path, prim)
            name = prim.name
        elif isinstance(prim, FloatLiteral | IntLiteral):
            _check_literal_bounds(path, prim.lo, prim.hi)
            continue
        else:
            raise ResolutionError(
                f"param {path!r}: symbolic() primitives entries must be a str, "
                f"Primitive, FloatLiteral, or IntLiteral, got {type(prim).__name__}"
            )
        if name in seen:
            raise ResolutionError(f"param {path!r}: duplicate primitive name {name!r}")
        seen.add(name)


def _check_program_max_depth(path: str, max_depth: Any) -> None:
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 1:
        raise ResolutionError(
            f"param {path!r}: symbolic() max_depth must be a positive int, got {max_depth!r}"
        )


def _check_symbolic_domain(path: str, domain: SymbolicDomain) -> None:
    """Row 15: declaration hygiene for a `.symbolic()` grammar.

    Core assigns no arity or meaning to a primitive name, so there is no
    fixed built-in primitive list to check against. What is checked is the
    signature's argument names, each primitives entry's shape, duplicates
    and arity, and `max_depth`.
    """
    _check_program_signature(path, domain.signature)
    _check_program_primitives(path, domain.primitives)
    _check_program_max_depth(path, domain.max_depth)


def _check_code_domain(path: str, domain: CodeDomain) -> None:
    _check_program_signature(path, domain.signature)
    if domain.examples is not None:
        check_meta_json_serializable(
            {"examples": list(domain.examples)}, what=f"param {path!r}: code() examples"
        )


def _check_subset_size_bounds(path: str, domain: SubsetDomain) -> None:
    if domain.min_size < 0:
        raise ResolutionError(f"param {path!r}: subset min_size must be >= 0")
    if domain.max_size is not None and domain.max_size < domain.min_size:
        raise ResolutionError(
            f"param {path!r}: subset max_size ({domain.max_size}) < min_size ({domain.min_size})"
        )
    if domain.min_size > len(domain.items):
        raise ResolutionError(
            f"param {path!r}: subset min_size ({domain.min_size}) exceeds the "
            f"item universe ({len(domain.items)} items)"
        )


def _check_choice_variants(path: str, domain: ChoiceDomain) -> None:
    if len(domain.variants) == 0:
        raise ResolutionError(f"param {path!r}: choice requires at least one variant")
    seen: set[str] = set()
    for name in domain.variants:
        check_name(name, what=f"variant name (param {path!r})")
        if name in seen:
            raise ResolutionError(f"param {path!r}: duplicate variant name {name!r}")
        seen.add(name)


def _check_bounds(path: str, lo: Any, hi: Any) -> None:
    if isinstance(lo, ArithExpr) or isinstance(hi, ArithExpr):
        # A top-level, non-lifted param's bounds are plain numbers by the
        # time this runs: `compute_bound_envelopes` (resolve/_bounds.py)
        # resolved any expression bound into a numeric envelope before
        # `_validate_declarations` was called. This branch therefore fires
        # only for a `.repeat()` element's own domain, where expression
        # bounds are unsupported. `_validate_lift` below reconstructs a
        # synthetic element view and validates it the same way.
        raise ResolutionError(
            f"param {path!r}: expression bounds on a repeated element are not "
            "yet supported; write literal numeric bounds for the element domain"
        )
    if isinstance(lo, bool) or isinstance(hi, bool):
        raise ResolutionError(f"param {path!r}: bounds must be numeric, not bool")
    if not math.isfinite(lo) or not math.isfinite(hi):
        raise ResolutionError(f"param {path!r}: bounds must be finite (got lo={lo!r}, hi={hi!r})")
    if lo > hi:
        raise ResolutionError(f"param {path!r}: lo={lo!r} > hi={hi!r}")


def _check_distinct_values(path: str, values: tuple[Any, ...], *, what: str) -> None:
    seen: list[Any] = []
    for v in values:
        for existing in seen:
            if type(existing) is type(v) and existing == v:
                raise ResolutionError(f"param {path!r}: duplicate {what}: {v!r}")
        seen.append(v)


def _check_no_shared_string_image(path: str, values: tuple[Any, ...]) -> None:
    seen_images: dict[str, Any] = {}
    for v in values:
        image = str(v)
        if image in seen_images and type(seen_images[image]) is not type(v):
            raise ResolutionError(
                f"param {path!r}: categorical values {seen_images[image]!r} and {v!r} "
                f"share the string image {image!r}"
            )
        seen_images.setdefault(image, v)


def _validate_prior(d: ParamExpr) -> None:
    if not isinstance(d.prior_spec, Weights):
        return
    weights = d.prior_spec.values
    domain = d.domain
    if d.type_kind == "subset":
        assert isinstance(domain, SubsetDomain)
        if len(weights) != len(domain.items):
            raise ResolutionError(
                f"param {d.path!r}: prior(weights=...) has {len(weights)} entries, "
                f"expected {len(domain.items)}"
            )
        if any(w < 0.0 or w > 1.0 for w in weights):
            raise ResolutionError(
                f"param {d.path!r}: prior(weights=...) inclusion probabilities "
                "must be within [0, 1]"
            )
        return
    if d.type_kind == "bool":
        expected_len = 2
    elif isinstance(domain, CategoricalDomain | OrdinalDomain):
        expected_len = len(domain.values)
    elif isinstance(domain, ChoiceDomain):
        expected_len = len(domain.variants)
    else:  # pragma: no cover - unreachable given _check_modifier_placement
        expected_len = len(weights)
    if len(weights) != expected_len:
        raise ResolutionError(
            f"param {d.path!r}: prior(weights=...) has {len(weights)} entries, "
            f"expected {expected_len}"
        )
    if any(w < 0 for w in weights):
        raise ResolutionError(f"param {d.path!r}: prior(weights=...) must be non-negative")
    if all(w == 0 for w in weights):
        raise ResolutionError(f"param {d.path!r}: prior(weights=...) must not be all-zero")


def _validate_quantized(d: ParamExpr) -> None:
    q = d.quantized_spec
    if q is None:
        return
    if (q.step is None) == (q.factor is None):
        raise ResolutionError(
            f"param {d.path!r}: quantized() requires exactly one of step or factor"
        )
    if q.step is not None and (not math.isfinite(q.step) or q.step <= 0):
        raise ResolutionError(f"param {d.path!r}: quantized(step=...) must be finite and > 0")
    if q.factor is not None and (not math.isfinite(q.factor) or q.factor <= 1):
        raise ResolutionError(f"param {d.path!r}: quantized(factor=...) must be finite and > 1")


def _strict_member(value: Any, values: tuple[Any, ...]) -> bool:
    return any(type(value) is type(v) and value == v for v in values)


def _default_is_valid_subset(value: Any, domain: SubsetDomain) -> bool:
    if not isinstance(value, list):
        return False
    seen: list[Any] = []
    for v in value:
        if any(type(existing) is type(v) and existing == v for existing in seen):
            return False  # duplicate item
        if not _strict_member(v, domain.items):
            return False
        seen.append(v)
    max_size = domain.max_size if domain.max_size is not None else len(domain.items)
    return domain.min_size <= len(value) <= max_size


def _default_is_valid_permutation(value: Any, domain: PermutationDomain) -> bool:
    if not isinstance(value, list) or len(value) != len(domain.items):
        return False
    seen: list[Any] = []
    for v in value:
        if any(type(existing) is type(v) and existing == v for existing in seen):
            return False
        if not _strict_member(v, domain.items):
            return False
        seen.append(v)
    return True


def _on_grid(lo: float, hi: float, quantized: QuantizedSpec, value: float) -> bool:
    """Grid membership for a real or integer default (row 21).

    A quantized scalar's domain is the grid rather than the raw `[lo, hi]`
    interval. This is the recovery `validate()` uses for a submitted value,
    so a filled default is never off-grid the moment `apply_defaults` emits
    it.
    """
    shape = build_grid_shape(lo, hi, quantized.step, quantized.factor, quantized.include_hi)
    return grid_membership(shape, value) is not None


def _validate_default(d: ParamExpr) -> None:
    if d.default_value is None:
        return
    value = d.default_value
    domain = d.domain
    if isinstance(domain, StructDomain):
        # Row 21: "no own value; completion is field-wise". A struct param,
        # top-level or a lift's own element, never has a default of its own,
        # whether written before or after `.repeat()`.
        raise ResolutionError(
            f"param {d.path!r}: .default() is not valid on a struct param"
            "; its members default individually, field-wise"
        )
    ok: bool
    if isinstance(domain, RealDomain):
        lo, hi = domain.lo, domain.hi
        # Bounds are already confirmed non-ArithExpr by _check_bounds, which
        # _validate_domain runs before this for the same param.
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        is_numeric = isinstance(value, int | float) and not isinstance(value, bool)
        # Periodic reals are half-open, `[lo, hi)` with `hi` itself invalid.
        # This is the rule validate() applies to a submitted value; row 21
        # makes a default a domain member like any other.
        in_bounds = is_numeric and (lo <= value < hi if d.periodic else lo <= value <= hi)
        ok = in_bounds
        if ok and d.quantized_spec is not None:
            ok = _on_grid(lo, hi, d.quantized_spec, float(value))
    elif isinstance(domain, IntegerDomain):
        int_lo, int_hi = domain.lo, domain.hi
        assert isinstance(int_lo, int) and isinstance(int_hi, int)
        is_numeric = isinstance(value, int) and not isinstance(value, bool)
        ok = is_numeric and int_lo <= value <= int_hi
        if ok and d.quantized_spec is not None:
            ok = _on_grid(float(int_lo), float(int_hi), d.quantized_spec, float(value))
    elif isinstance(domain, CategoricalDomain | OrdinalDomain):
        ok = any(type(value) is type(v) and value == v for v in domain.values)
    elif isinstance(domain, BoolDomain):
        ok = isinstance(value, bool)
    elif isinstance(domain, ChoiceDomain):
        ok = isinstance(value, str) and value in domain.variants
    elif isinstance(domain, SubsetDomain):
        ok = _default_is_valid_subset(value, domain)
    elif isinstance(domain, PermutationDomain):
        ok = _default_is_valid_permutation(value, domain)
    elif isinstance(domain, CustomDomain):
        # `value` is already phenotype form, matching every other public
        # config-dict-shaped surface. Bridge back to native only to call the
        # type's own validate().
        if domain.param_type is not None:
            ok = domain.param_type.validate(domain.param_type.from_json(value))
        else:
            assert domain.validator is not None
            ok = domain.validator(value)
    elif isinstance(domain, SymbolicDomain | CodeDomain):
        ok = program_value_error(domain, value) is None
    else:  # pragma: no cover - unreachable: every Domain variant handled above
        ok = True
    if not ok:
        raise ResolutionError(f"param {d.path!r}: default {value!r} is outside its domain")


def _validate_lift(d: ParamExpr, defs_by_path: dict[str, ParamExpr]) -> None:
    """Validate a `.repeat()`-closed param.

    Each level's count (row 12) and list default (row 21) are checked, then
    the innermost element's own domain, prior, quantized spec and default.
    The element checks reuse the scalar validators unchanged, against a
    synthetic element-scoped `ParamExpr` whose path is `f"{d.path}[]"`, with
    one `"[]"` per nesting level. That is the definition-path convention
    lift descendants use throughout.
    """
    assert d.lift is not None
    snap = d.lift
    depth = 0
    any_list_default = False
    while True:
        depth += 1
        assert snap.count is not None
        # A count up-referencing an enclosing scope is tolerated here and
        # re-checked at finalization, exactly like a condition. Unlike an
        # expression bound, nothing in this scope's resolution consumes a
        # count: lists are structure rather than charts.
        _check_count_type(d.path, snap.count, defs_by_path, tolerate_undeclared=True)
        _validate_list_default_shape(d.path, snap)
        any_list_default = any_list_default or snap.list_default is not None
        inner = snap.element
        assert inner is not None
        if inner.element_class is not ListParamExpr:
            break
        snap = inner
    if depth > 1 and inner.element_class in (StructParamExpr, ChoiceParamExpr):
        raise ResolutionError(
            f"param {d.path!r}: a struct/choice element nested under more than one "
            ".repeat() level is not supported; scalar/subset/permutation "
            "elements support arbitrary nesting"
        )
    # inner.element_class is the view class the element was declared with.
    # Reconstructing through it rather than through a bare ParamExpr is what
    # gives `element` a type_kind at all, since type_kind is a ClassVar
    # rather than a settable field.
    element = inner.element_class(
        path=d.path + "[]" * depth,
        domain=inner.domain,
        prior_spec=inner.prior_spec,
        quantized_spec=inner.quantized_spec,
        periodic=inner.periodic,
        default_value=inner.default_value,
        struct_space=inner.struct_space,
        choice_payloads=inner.choice_payloads,
    )
    _validate_domain(element)
    _validate_prior(element)
    _validate_quantized(element)
    _validate_default(element)
    if inner.default_value is not None and any_list_default:
        raise ResolutionError(
            f"param {d.path!r}: element default and list default are mutually exclusive"
        )


def _innermost_domain_element_kind(domain: Domain) -> str | None:
    """`_innermost_lift_element_kind`'s resolved-IR counterpart.

    The same descent one representation later, over the `ListDomain` chain
    the merged space holds instead of the builder's `.lift` snapshots. Used
    by the finalization re-check.
    """
    if not isinstance(domain, ListDomain):
        return None
    while isinstance(domain.element_domain, ListDomain):
        domain = domain.element_domain
    return domain.element_kind


def _innermost_lift_element_kind(pd: ParamExpr | ParamDef) -> str | None:
    """The leaf `type_kind` a `Sum`, `Min` or `Max` over `pd` flattens to.

    Read from the builder-time `_ElementSnapshot` chain on `.lift` rather
    than from `.domain`. `_check_count_type_node` runs before
    `_build_list_domains`, so a sibling param's `ListDomain` may not exist
    yet, whereas `.lift` is a build-time artifact populated the moment
    `.repeat()` was called, regardless of resolution order. This mirrors
    `_validate_lift`'s own descent through chained and nested repeat levels.

    `None` when `pd` is not `.repeat()`-closed, as for a plain scalar
    summed by mistake; row 12 covers that as "not integer-typed" either way.

    Also accepts a resolved `ParamDef`, for the finalization re-check, where
    the merged space holds `ListDomain` objects rather than the builder's
    `.lift` snapshots. The descent is the same, one representation later.
    """
    if isinstance(pd, ParamDef):
        return _innermost_domain_element_kind(pd.domain)
    if pd.lift is None:
        return None
    inner = pd.lift.element
    assert inner is not None
    while inner.element_class is ListParamExpr:
        inner = inner.element
        assert inner is not None
    return inner.element_class.type_kind


def _check_count_type_node(
    node: Expr,
    defs_by_path: Mapping[str, Any],
    context: str,
    *,
    tolerate_undeclared: bool = False,
) -> None:
    """The integer-valued calculus for `.repeat()` counts (row 12).

    The closed set is: int literals; integer params; `Count`, `Size`,
    `Length`, `PositionOf` and `CountOf`, which are int by construction; a
    declared-int `Prop` or a `returns=int` `ds.value`; `Sum` over an integer-
    or bool-leaved lift, since `sum([True, False])` is `int`; `Min` and `Max`
    over an integer-leaved lift only, since `min([True, False])` is `bool`
    rather than `int`, the one deliberate asymmetry; a literal-valued
    `SumOver` mapping; `+`, `-`, `*` and `%` over two int-valued operands;
    `**` with a non-negative literal integer exponent; and `IfInactive` when
    both branches are int-valued.

    Division and anything else outside the set is row 12. The set mirrors
    the bounds engine's own minimal computable op set (API.md, "Expression
    bounds are sugar").

    `tolerate_undeclared` skips a node whose references do not all bind
    locally, which means an enclosing-scope up-reference whose type is
    unknowable until every outer scope has contributed its params.
    `check_fully_resolved` re-runs this strictly over the merged space, so
    the row-12 check is deferred rather than dropped. This mirrors
    `check_expr_types`' own node-level skip.
    """
    tolerate = tolerate_undeclared
    if tolerate and any(not _is_declared(p, defs_by_path) for p in node.params):
        return
    if isinstance(node, Literal):
        if not isinstance(node.value, int) or isinstance(node.value, bool):
            raise ResolutionError(f"{context}: must be integer-typed, got literal {node.value!r}")
        return
    if isinstance(node, ParamExpr):
        kind = defs_by_path[node.path].type_kind
        if kind != "integer":
            raise ResolutionError(
                f"{context}: references {node.path!r}, which is {kind!r}, not integer"
            )
        return
    if isinstance(node, Prop):
        # A `.prop()`-driven count, as in API.md's
        # `.repeat(ds.param("g").prop("n_edges"))`. Check that the declared
        # property type is int, and deliberately do not descend into the
        # operand: the operand is the custom param itself, of type_kind
        # "custom", which is correctly not integer-typed. Only the extracted
        # property value needs to be.
        if prop_type(node, defs_by_path, context=context) is not int:
            raise ResolutionError(f"{context}: prop({node.name!r}) is not integer-typed")
        return
    if isinstance(node, Value):
        # A `ds.value(fn, ..., returns=int)`-driven count. Only the declared
        # result type must be integer, so this deliberately does not descend
        # into the operands, mirroring the `Prop` branch above.
        if node.returns is not int:
            raise ResolutionError(
                f"{context}: ds.value(returns={node.returns.__name__}) is not integer-typed"
            )
        return
    if isinstance(node, Count | Size | Length | PositionOf | CountOf):
        return  # always int-valued by construction; no leaf to check
    if isinstance(node, SumOver):
        if not all(isinstance(v, int) and not isinstance(v, bool) for v in node.mapping.values()):
            raise ResolutionError(f"{context}: sum_over() has a non-integer value")
        return
    if isinstance(node, Sum | Min | Max):
        if not isinstance(node.operand, ParamExpr):
            raise ResolutionError(
                f"{context}: {node.kind}() over a .field() projection is not "
                "supported as a repeat() count"
            )
        elem_kind = _innermost_lift_element_kind(defs_by_path[node.operand.path])
        allowed = ("integer", "bool") if isinstance(node, Sum) else ("integer",)
        if elem_kind not in allowed:
            raise ResolutionError(
                f"{context}: {node.kind}() over a {elem_kind!r}-leaved lift is not integer-typed"
            )
        return
    if isinstance(node, ArithOp):
        if node.op == "div":
            raise ResolutionError(f"{context}: division is not integer-typed")
        if node.op == "pow" and not (
            isinstance(node.right, Literal)
            and isinstance(node.right.value, int)
            and not isinstance(node.right.value, bool)
            and node.right.value >= 0
        ):
            raise ResolutionError(
                f"{context}: ** requires a non-negative literal integer exponent to "
                "stay integer-typed"
            )
        _check_count_type_node(node.left, defs_by_path, context, tolerate_undeclared=tolerate)
        _check_count_type_node(node.right, defs_by_path, context, tolerate_undeclared=tolerate)
        return
    if isinstance(node, IfInactive):
        _check_count_type_node(node.operand, defs_by_path, context, tolerate_undeclared=tolerate)
        _check_count_type_node(node.fallback, defs_by_path, context, tolerate_undeclared=tolerate)
        return
    raise ResolutionError(f"{context}: must be integer-typed")


def _check_count_type(
    path: str,
    count: int | ArithExpr,
    defs_by_path: Mapping[str, Any],
    *,
    tolerate_undeclared: bool = False,
) -> None:
    if isinstance(count, ArithExpr):
        context = f"param {path!r} repeat() count"
        check_refs_declared(
            count, defs_by_path, context=context, tolerate_undeclared=tolerate_undeclared
        )
        _check_count_type_node(
            count, defs_by_path, context, tolerate_undeclared=tolerate_undeclared
        )
        return
    if not isinstance(count, int) or isinstance(count, bool):
        raise ResolutionError(
            f"param {path!r}: repeat() count must be an int or an integer-typed "
            f"expression, got {count!r}"
        )
    if count < 0:
        raise ResolutionError(f"param {path!r}: repeat() count must be >= 0, got {count!r}")


def _validate_list_default_shape(path: str, snap: _ElementSnapshot) -> None:
    if snap.list_default is None:
        return
    if isinstance(snap.count, ArithExpr):
        raise ResolutionError(
            f"param {path!r}: list default requires a static (int) repeat count at this level"
        )
    if not isinstance(snap.list_default, list) or len(snap.list_default) != snap.count:
        raise ResolutionError(
            f"param {path!r}: list default length must match the static repeat count ({snap.count})"
        )


def _validate_list_defaults_deep(space: Space) -> None:
    """Row 21, continued: each item of a post-`.repeat()` list default.

    A `.repeat(n).default([...])` is a literal phenotype value per index, so
    each item must itself be a domain member, recursively for struct and
    choice elements: such a list default is shaped like
    `[{"width": 128}, ...]` rather than as a flat scalar.

    `_validate_list_default_shape` in step 7 checks length and static count
    only. This reuses `validate()`'s own per-instance domain checks, so it
    must run after `_emit` has built `space.params`: struct and choice lift
    descendants are relocated there under a `"[]"`-bracketed prefix and do
    not exist earlier in the pipeline.

    Recursing through `ListDomain.element_domain` deep-checks the
    `list_default` at every level of a chained lift, such as
    `.repeat(a).default([...]).repeat(b)` under API.md's "per-level list
    modifiers between lifts", rather than the outermost alone. A level below
    the outermost has no single real instance path to hang the check on,
    since the same literal default applies identically to every outer
    instance and `apply_defaults` fills it per outer row. A synthetic outer
    index of `[0]` is therefore used at each descent; any index works,
    because every row is identical. A struct or choice element cannot nest
    under more than one `.repeat()`, so a level below the outermost is
    always scalar, subset or permutation, with no descendant-template prefix
    to synthesize and only the index to supply. Each level builds its own
    `flat` dict, so simultaneous `list_default` values at different levels
    never collide.
    """
    for path, pd in space.params.items():
        if "[]" in path or pd.type_kind != "list":
            continue
        domain = pd.domain
        assert isinstance(domain, ListDomain)
        _validate_list_default_level(space, path, path, domain, depth=0)


def _validate_list_default_level(
    space: Space, param_path: str, concrete_prefix: str, domain: ListDomain, depth: int
) -> None:
    from designspace.config._flatten import _flatten_list_element
    from designspace.eval import compute_activity
    from designspace.validate._validate import _validate_lift_instances

    if domain.list_default is not None:
        assert isinstance(domain.count, int)
        flat: dict[str, Any] = {concrete_prefix: len(domain.list_default)}
        shape_errors: list[ParamError] = []
        for i, item in enumerate(domain.list_default):
            _flatten_list_element(
                item,
                domain,
                space,
                template_prefix=element_prefix(concrete_prefix),
                concrete_prefix=instance_prefix(concrete_prefix, i),
                out=flat,
                errors=shape_errors,
            )
        activity = compute_activity(space, flat)
        errors = shape_errors + _validate_lift_instances(
            space, concrete_prefix, domain, flat, activity
        )
        if errors:
            detail = "; ".join(f"{e.param!r}: {e.reason}={e.value!r}" for e in errors)
            level = "list default" if depth == 0 else f"nested list default (depth {depth})"
            raise ResolutionError(
                f"param {param_path!r}: {level} {domain.list_default!r} is outside "
                f"its domain ({detail})"
            )
    if domain.element_kind == "list":
        assert isinstance(domain.element_domain, ListDomain)
        _validate_list_default_level(
            space, param_path, f"{concrete_prefix}[0]", domain.element_domain, depth + 1
        )


def _validate_tags_meta(d: ParamExpr) -> None:
    if "" in d.tags:
        raise ResolutionError(f"param {d.path!r}: empty-string tags are not allowed")
    check_meta_json_serializable(dict(d.meta_map), what=f"param {d.path!r}")


# -- step 8: emit IR -----------------------------------------------------------


def _innermost_element(lift: _ElementSnapshot) -> _ElementSnapshot:
    while lift.element_class is ListParamExpr:
        assert lift.element is not None
        lift = lift.element
    return lift


def _relocate_choice_variants(
    discriminator_path: str,
    prefix: str,
    domain: ChoiceDomain,
    choice_payloads: Any,
    condition: Any,
) -> tuple[dict[str, ParamDef], list[Condition], list[Constraint]]:
    """The discriminator-equality condition folded into a variant payload.

    Shared by a plain top-level choice and a lifted choice element, the
    latter having `ListDomain.element_kind == "choice"`.
    `discriminator_path` may be an ordinary definition path such as `"algo"`
    or a `"[]"`-bracketed lift-element template such as `"pipeline[]"`.
    Either way it is another `ParamExpr` leaf reference to rewrite, which
    `instantiate_element`, `relocate_child`'s per-instance sibling,
    substitutes uniformly alongside the variant's own descendants.
    """
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    constraints: list[Constraint] = []
    for variant_name in domain.variants:
        payload = choice_payloads.get(variant_name)
        if payload is None:
            continue
        if not isinstance(payload, Space):
            # Row 29 (item 7): a payload that is not a Space. Without this
            # check a bare ParamExpr reaches `relocate_child` below and
            # raises an opaque AttributeError from `child.params`, whose
            # Mapping a Space has and an Expr's frozenset does not.
            raise ResolutionError(
                f"param {discriminator_path!r}: choice() payload for variant "
                f"{variant_name!r} must be a Space (from ds.space(...)), got "
                f"{type(payload).__name__}"
            )
        discriminator_eq = Compare("eq", ParamExpr(path=discriminator_path), Literal(variant_name))
        injected = and_(condition, discriminator_eq)
        child_params, child_conditions, child_constraints = relocate_child(
            payload, new_prefix=f"{prefix}{variant_name}.", injected_condition=injected
        )
        params.update(child_params)
        conditions.extend(child_conditions)
        constraints.extend(child_constraints)
    return params, conditions, constraints


def _emit(defs: tuple[ParamExpr, ...], charts: dict[str, Chart | None]) -> Space:
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    constraints: list[Constraint] = []
    for d in defs:
        assert d.type_kind is not None
        assert d.domain is not None
        params[d.path] = ParamDef(
            path=d.path,
            type_kind=d.type_kind,
            domain=d.domain,
            prior=d.prior_spec,
            periodic=d.periodic,
            default=d.default_value,
            condition=d.condition,
            tags=d.tags,
            meta=d.meta_map,
            chart=charts[d.path],
            quantized=d.quantized_spec,
        )
        if d.condition is not None:
            conditions.append(Condition(target=d.path, expr=d.condition, params=d.condition.params))

        if d.type_kind == "space" and d.struct_space is not None:
            child_params, child_conditions, child_constraints = relocate_child(
                d.struct_space, new_prefix=f"{d.path}.", injected_condition=d.condition
            )
            params.update(child_params)
            conditions.extend(child_conditions)
            constraints.extend(child_constraints)
        elif d.type_kind == "choice":
            assert isinstance(d.domain, ChoiceDomain)
            child_params, child_conditions, child_constraints = _relocate_choice_variants(
                d.path, f"{d.path}.", d.domain, d.choice_payloads, d.condition
            )
            params.update(child_params)
            conditions.extend(child_conditions)
            constraints.extend(child_constraints)
        elif d.type_kind == "list":
            assert isinstance(d.domain, ListDomain)
            assert d.lift is not None
            leaf = _innermost_element(d.lift)
            if leaf.element_class is StructParamExpr and leaf.struct_space is not None:
                child_params, child_conditions, child_constraints = relocate_child(
                    leaf.struct_space, new_prefix=element_prefix(d.path), injected_condition=None
                )
                params.update(child_params)
                conditions.extend(child_conditions)
                # Element-scoped constraints are per-instance templates,
                # carried on ListDomain and never flattened into
                # `space.constraints` directly.
                params[d.path] = replace(
                    params[d.path],
                    domain=replace(d.domain, element_constraints=tuple(child_constraints)),
                )
            elif leaf.element_class is ChoiceParamExpr:
                assert isinstance(leaf.domain, ChoiceDomain)
                variant_params, variant_conditions, variant_constraints = _relocate_choice_variants(
                    f"{d.path}[]",
                    element_prefix(d.path),
                    leaf.domain,
                    leaf.choice_payloads,
                    None,
                )
                params.update(variant_params)
                conditions.extend(variant_conditions)
                params[d.path] = replace(
                    params[d.path],
                    domain=replace(d.domain, element_constraints=tuple(variant_constraints)),
                )

    return Space(
        params=MappingProxyType(params),
        conditions=tuple(conditions),
        constraints=tuple(constraints),
    )
