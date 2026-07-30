"""The resolve pass pipeline (API.md, "Resolution").

Covers steps 1-8: collect, type-check, desugar (`implies`; `log_scale`
already resolved eagerly at the builder, D-2), resolve references,
cycle-check, compute bound envelopes (M5, resolve/_bounds.py), validate
declarations, build charts, emit IR. M3 adds choice/struct/subset/permutation;
lifts are M4's work.

Each numbered step is a plain function over the previous step's output,
per PLAN.md.md's "each pass a function over an explicit
intermediate."

Structural expansion (choice/struct) happens in step 8 (`_emit`), not
earlier: a choice/struct param's own condition is resolved and cycle-
checked exactly like any other param's `.when()` at *this* level (steps
4-5 already handle it uniformly, since it's just an ordinary ParamExpr
entry in `defs`); its payload's *descendant* params were already fully
resolved (by their own, earlier `resolve_space` call — see
build/_paramexpr.py's `.space()`/`.choice()`) and only need reprefixing
plus one folded-in activation condition (resolve/_relocate.py), never
re-validation.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any

from designspace.build._names import check_meta_json_serializable, check_name
from designspace.build._paramexpr import ParamExpr, _ElementSnapshot
from designspace.build._space import Space
from designspace.build._views import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    CustomParamExpr,
    IntegerParamExpr,
    ListParamExpr,
    OrdinalParamExpr,
    PermutationParamExpr,
    RealParamExpr,
    StructParamExpr,
    SubsetParamExpr,
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
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    Chart,
    ChoiceDomain,
    Condition,
    Constraint,
    CustomDomain,
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
    Weights,
)
from designspace.resolve._bounds import bound_deps, check_bound_refs, compute_bound_envelopes
from designspace.resolve._desugar import desugar_bool
from designspace.resolve._expr_checks import check_expr_types, check_refs_declared, prop_type
from designspace.resolve._relocate import and_, relocate_child

_NON_CHART_KINDS = ("subset", "permutation", "choice", "space", "custom", "list")


def resolve_space(exprs: tuple[ParamExpr, ...]) -> Space:
    defs = _collect(exprs)  # step 1
    _check_types_and_names(defs)  # step 2
    defs = _desugar(defs)  # step 3: implies -> ~left | right (D-1); log_scale
    # already resolves eagerly at the builder. Lift ("repeat") layer folding
    # already happened at the builder (`.repeat()`, build/_paramexpr.py) —
    # this step only rewrites `.when()` conditions.
    defs_by_path = {d.path: d for d in defs}
    _resolve_condition_refs(defs, defs_by_path)  # step 4
    check_bound_refs(defs, defs_by_path)  # step 4, bound side (row 6/14; eager
    # — no up-reference tolerance, DECISIONS.md D-29)
    _check_condition_cycles(defs)  # step 5 (condition/bound/repeat-count DAG)
    defs, bound_constraints = compute_bound_envelopes(defs, defs_by_path)  # step 6
    defs_by_path = {d.path: d for d in defs}  # bounds are now plain numbers
    _validate_declarations(defs, defs_by_path)  # step 7 (bounds/weights/etc —
    # must precede chart-building, which assumes sane bounds)
    defs = _build_list_domains(defs)  # M4: fold each lift's `_ElementSnapshot`
    # chain into a resolved, chart-carrying `ListDomain` (DECISIONS.md D-18).
    charts = _build_charts(defs)  # step 6, chart side
    space = _emit(defs, charts)  # step 8
    if bound_constraints:
        space = replace(space, constraints=space.constraints + tuple(bound_constraints))
    _validate_list_defaults_deep(space)  # row 21, continued — needs space.params
    return space


def check_fully_resolved(space: Space) -> None:
    """Re-run the deferred row-6/7/14 condition checks over the fully-merged
    space (DECISIONS.md D-26, superseding D-12).

    A `.when()` condition may reference a param bound in an *enclosing* scope
    (API.md's sole scoping rule — resolve the first segment by walking up).
    Such an up-reference cannot be resolved while its payload is resolved
    standalone, so per-scope resolution *tolerates* it (skipping it in
    `check_refs_declared`/`check_expr_types`/cycle detection). Here — at every
    terminal entry point (sample/validate/…), once every enclosing scope has
    contributed its params — the checks re-run strictly over the merged graph:

    - row 6: an up-reference that binds nowhere is a genuine typo and raises;
    - row 14: a comparison/arithmetic over a now-visible up-referenced param
      is type-checked (it was skipped standalone);
    - row 7: a *cross-scope* cycle (only formable through an up-reference plus
      a matching down-reference) is caught here — per-scope cycle detection
      never sees both edges.

    Also re-checks `space.constraints` (M10.5 — the metaprogramming hole):
    a builder-built space's constraints are already strict at
    `add_constraints`, so this is a confirming no-op for it, but a raw-IR
    constraint arriving through `meta/_meta.py::space_from_ir` was never
    expression-checked at all otherwise — which would let a row-6/12/14/18/29
    violation (an out-of-range static index, a lift-valued boolean operand,
    …) reach `sample`/`validate`/`fingerprint` silently through that path.

    A space with only local references reaches this function already fully
    checked; every clause below is then a confirming no-op.
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
    _check_merged_cycles(space)


def _check_merged_cycles(space: Space) -> None:
    deps: dict[str, frozenset[str]] = {c.target: c.params for c in space.conditions}
    for target, target_deps in deps.items():
        if target in target_deps:
            raise ResolutionError(f"param {target!r}: condition references itself")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(path: str) -> None:
        if path in done:
            return
        if path in visiting:
            raise ResolutionError(
                f"cycle detected in condition dependencies involving {path!r}"
            )
        visiting.add(path)
        for dep in deps.get(path, frozenset()):
            visit(dep)
        visiting.discard(path)
        done.add(path)

    for target in deps:
        visit(target)


# -- M8: ParamDef <-> ParamExpr view inversion, and re-validation of a -------
# hand-assembled or rewritten flat IR (API.md, "Space — Metaprogramming":
# "the IR is bidirectional"; "resolution re-validates whatever comes in").
# Shared by `meta/_meta.py` (`param_from_def`, `space_from_ir`) and
# `serialize/_fromjson.py` (chart rebuilding on load) — kept here, next to
# `_build_list_domain`/`_validate_declarations`, whose exact inverse and
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
}


def param_def_to_view(pd: ParamDef) -> ParamExpr:
    """Invert a resolved `ParamDef` back into the `ParamExpr` view the
    fluent builder would have produced for it — the reverse of `_emit`'s
    per-definition half. Structural relocation (the *other* half of `_emit`,
    folding a struct/choice payload's descendants into the flat space) has
    no single-`ParamDef` inverse: a struct/choice view built here is always
    payload-less (`struct_space=None` / empty `choice_payloads`), since its
    descendants are separate `ParamDef` entries this function never sees.
    That is fine for every caller: `validate_param_defs` (below) only needs
    each definition's *own* declaration, and the public, single-`ParamDef`
    `meta/_meta.py::param_from_def` rejects the two container kinds before
    ever reaching this function (DECISIONS.md D-41) rather than returning
    one silently short of its descendants.
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
    """Inverse of `_build_list_domain`: rebuild the `_ElementSnapshot` chain
    `.repeat()` would have produced for this resolved `ListDomain`,
    recursing once per chained lift level exactly as `_build_list_domain`
    does in the other direction. A struct/choice element's snapshot is
    payload-less (see `param_def_to_view`)."""
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
    """Re-validate a flat mapping of already-resolved `ParamDef`s: each
    one's own domain/prior/quantized/default/tags/meta, plus — for a
    `.repeat()`-closed ("list") kind — its element and (for a dynamic
    count) the type of the param the count references. The same
    per-definition checks `_validate_declarations` runs during ordinary
    builder resolution (row 2's "more than one type" cannot recur here —
    a `ParamDef.type_kind` string always names exactly one kind by
    construction, unlike a hand-built `ParamExpr`). Conditions/cycles are
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
    """Charts are always derived, never trusted from input — rebuild fresh
    from domain/prior/quantized, discarding whatever `pd.chart` already
    holds. Shared by `serialize/_fromjson.py` (loading a `to_json`
    document) and `meta/_meta.py::space_from_ir` (assembling a `Space` from
    raw `ParamDef`s), both of which start from a chartless or
    not-to-be-trusted `pd.chart`.
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
            path, domain.element_kind, domain.element_domain, domain.element_prior,
            domain.element_quantized,
        )
        if domain.element_kind in ("real", "integer")
        else None
    )
    return replace(domain, element_chart=element_chart)


def revalidate_space(space: Space) -> Space:
    """Re-run every per-definition and cross-definition check ordinary
    builder resolution performs, over an already-flat `Space` assembled
    from raw IR rather than produced by `resolve_space`'s own pipeline
    (`meta/_meta.py::space_from_ir`). "Resolution re-validates whatever
    comes in" (API.md, "Space — Metaprogramming"): a `ParamDef` reaching
    `space_from_ir` may have come from anywhere — a coarsening
    `map_params` rewrite, a hand-built registry, a foreign document — so it
    is held to the same standard as one the fluent builder produced.
    Returns `space` for convenient chaining.
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
    """Fold each `.repeat()`-closed param's `_ElementSnapshot` chain into a
    resolved `ListDomain` (DECISIONS.md D-18), building the innermost
    element's chart along the way (`build_chart` is oblivious to lifts —
    it just needs a path/type_kind/domain/prior/quantized, which the
    snapshot already carries). Runs after `_validate_lift` has confirmed
    the element's bounds/priors are sane, mirroring the ordering already
    used for scalar params (validate before chart-building)."""
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

        # "More than one type" (row 2's other half) is now structurally
        # impossible to reach here (DECISIONS.md D-28): type_kind is a
        # ClassVar fixed by whichever view class built `d`, so there is no
        # runtime state left to misrepresent it, fluent or hand-built alike
        # — ParamExpr(type_kind=...) is a TypeError before this function
        # would ever see the object. Only "no type chosen" (a bare
        # FreshParamExpr/ParamExpr reaching resolution) remains checkable.
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
                "to the list, not the element — call it before .repeat() (row 11)"
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
                "list, not the element — call it before .repeat() (row 11)"
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
        # Condition up-references to an enclosing scope's params (API.md's
        # sole scoping rule) are tolerated here and re-checked at finalization
        # over the merged space, once every enclosing scope has contributed
        # its params (DECISIONS.md D-26, superseding D-12's eager rejection).
        check_refs_declared(d.condition, defs_by_path, context=context, tolerate_undeclared=True)
        check_expr_types(d.condition, defs_by_path, context=context, tolerate_undeclared=True)


# -- step 5: cycle detection ---------------------------------------------------


def _count_deps(lift: _ElementSnapshot | None) -> frozenset[str]:
    """Repeat-count references, across a (possibly chained) lift, join the
    same dependency graph as conditions (DECISIONS.md D-21): a count must
    be known before this param's instances can be materialized, exactly
    like a condition must be known before activity can be decided."""
    deps: frozenset[str] = frozenset()
    while lift is not None and lift.element_class is ListParamExpr:
        if isinstance(lift.count, ArithExpr):
            deps = deps | lift.count.params
        lift = lift.element
    return deps


def _check_condition_cycles(defs: tuple[ParamExpr, ...]) -> None:
    """Row 7: cycle in the condition/bound/repeat-count dependency graph, or
    a param's condition, bounds, or repeat count referencing itself. Runs
    before bound envelopes are computed (`compute_bound_envelopes`'s
    `envelope_of` is a memoized recursion that assumes this already holds)."""
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
            # A non-local dep is an up-reference into an enclosing scope
            # (D-26): it has no node here, so skip it — a cross-scope cycle
            # through it is caught at finalization over the merged graph.
            if dep in deps:
                visit(dep)
        visiting.discard(path)
        done.add(path)

    for d in defs:
        visit(d.path)


# -- step 7: validate declarations --------------------------------------------


def _validate_declarations(
    defs: tuple[ParamExpr, ...], defs_by_path: dict[str, ParamExpr]
) -> None:
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


def _check_custom_domain(path: str, domain: CustomDomain) -> None:
    """Row 2-adjacent construction check, not a numbered error row: the
    `.custom()` two-form overload itself already rejects a malformed call
    at the builder (`build/_views.py::FreshParamExpr.custom`) — this is a
    final sanity check for a programmatically-built `CustomDomain` reaching
    resolution some other way (`ds.param_from_def`, `space_from_ir`),
    mirroring that same check exactly."""
    full = domain.param_type is not None
    shorthand = domain.sampler is not None or domain.validator is not None
    if full and shorthand:
        raise ResolutionError(
            f"param {path!r}: custom domain sets both param_type and "
            "sampler/validator — exactly one form is allowed"
        )
    if not full and not shorthand:
        raise ResolutionError(
            f"param {path!r}: custom domain must set param_type or "
            "(sampler, validator)"
        )
    if shorthand and (domain.sampler is None or domain.validator is None):
        raise ResolutionError(
            f"param {path!r}: custom(sampler, validator) shorthand requires both"
        )


def _check_subset_size_bounds(path: str, domain: SubsetDomain) -> None:
    if domain.min_size < 0:
        raise ResolutionError(f"param {path!r}: subset min_size must be >= 0")
    if domain.max_size is not None and domain.max_size < domain.min_size:
        raise ResolutionError(
            f"param {path!r}: subset max_size ({domain.max_size}) < "
            f"min_size ({domain.min_size})"
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
        # A top-level (non-lifted) param's bounds are always plain numbers by
        # the time this runs — `compute_bound_envelopes` (M5, resolve/_bounds.py)
        # already resolved any expression bound into a numeric envelope before
        # `_validate_declarations` is called. This branch therefore only ever
        # fires for a `.repeat()` element's own domain (`_validate_lift` below
        # reconstructs a synthetic element view and validates it the same way)
        # — expression bounds there are not yet supported (DECISIONS.md D-29).
        raise ResolutionError(
            f"param {path!r}: expression bounds on a repeated element are not "
            "yet supported — write literal numeric bounds for the element domain"
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
    """Grid membership for a real/integer default (row 21: a quantized
    scalar's *domain* is the grid, not the raw `[lo, hi]` interval — the
    same recovery `validate()` uses for a submitted value, so a filled
    default is never off-grid the moment `apply_defaults` emits it)."""
    shape = build_grid_shape(lo, hi, quantized.step, quantized.factor, quantized.include_hi)
    return grid_membership(shape, value) is not None


def _validate_default(d: ParamExpr) -> None:
    if d.default_value is None:
        return
    value = d.default_value
    domain = d.domain
    if isinstance(domain, StructDomain):
        # Row 21: "no own value — completion is field-wise" — a struct
        # param (top-level or a lift's own element) never has a default of
        # its own, whether written before or after `.repeat()`.
        raise ResolutionError(
            f"param {d.path!r}: .default() is not valid on a struct param "
            "(row 21) — its members default individually, field-wise"
        )
    ok: bool
    if isinstance(domain, RealDomain):
        lo, hi = domain.lo, domain.hi
        # Bounds are already confirmed non-ArithExpr by _check_bounds, which
        # _validate_domain runs before this for the same param.
        assert isinstance(lo, int | float) and isinstance(hi, int | float)
        is_numeric = isinstance(value, int | float) and not isinstance(value, bool)
        # Periodic reals are half-open ([lo, hi), hi itself invalid) — the
        # same rule validate() applies to a submitted value (row 21: a
        # default is a domain member like any other).
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
        # `value` is already phenotype form (DECISIONS.md D-46), matching
        # every other public config-dict-shaped surface; bridge back to
        # native only to call the type's own validate().
        if domain.param_type is not None:
            ok = domain.param_type.validate(domain.param_type.from_json(value))
        else:
            assert domain.validator is not None
            ok = domain.validator(value)
    else:  # pragma: no cover - unreachable: every Domain variant handled above
        ok = True
    if not ok:
        raise ResolutionError(f"param {d.path!r}: default {value!r} is outside its domain")


def _validate_lift(d: ParamExpr, defs_by_path: dict[str, ParamExpr]) -> None:
    """Validates a `.repeat()`-closed param (DECISIONS.md D-18): each
    level's count (row 12) and list default (row 21), then the innermost
    element's own domain/prior/quantized/default via the *existing* scalar
    validators — reused unchanged against a synthetic element-scoped
    `ParamExpr` (path `f"{d.path}[]"`, one `"[]"` per nesting level),
    exactly the definition-path convention the rest of M4 uses for lift
    descendants.
    """
    assert d.lift is not None
    snap = d.lift
    depth = 0
    any_list_default = False
    while True:
        depth += 1
        assert snap.count is not None
        _check_count_type(d.path, snap.count, defs_by_path)
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
            ".repeat() level is not yet supported (M4 scope boundary, DECISIONS.md "
            "D-24) — scalar/subset/permutation elements support arbitrary nesting"
        )
    # inner.element_class (DECISIONS.md D-28) is the actual view the element
    # was declared with — reconstructing via that class, not a bare
    # ParamExpr, is what gives `element` a real (ClassVar-derived) type_kind
    # at all, since type_kind is no longer a settable field.
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
            f"param {d.path!r}: element default and list default are mutually "
            "exclusive (row 21)"
        )


def _innermost_lift_element_kind(pd: ParamExpr) -> str | None:
    """The leaf `type_kind` a `Sum`/`Min`/`Max` over `pd` flattens to,
    read from the builder-time `_ElementSnapshot` chain (`.lift`) rather
    than `.domain` — `_check_count_type_node` runs before
    `_build_list_domains` (a later pipeline step), so a sibling param's
    `ListDomain` may not exist yet, but `.lift` is a build-time artifact,
    populated the moment `.repeat()` was called, regardless of resolution
    order. Mirrors `_validate_lift`'s own descent through chained/nested
    repeat levels. `None` if `pd` is not `.repeat()`-closed at all (a
    plain scalar `.sum()`'d by mistake — row 12 covers it as "not
    integer-typed" either way)."""
    if pd.lift is None:
        return None
    inner = pd.lift.element
    assert inner is not None
    while inner.element_class is ListParamExpr:
        inner = inner.element
        assert inner is not None
    return inner.element_class.type_kind


def _check_count_type_node(node: Expr, defs_by_path: dict[str, ParamExpr], context: str) -> None:
    """The M10.5/D-72 integer-valued calculus for repeat() counts (row
    12): int literals, integer params, `Count`/`Size`/`Length`/
    `PositionOf`/`CountOf` (always int by construction), a declared-int
    `Prop`, `Sum` over an integer- *or* bool-leaved lift
    (`sum([True, False])` is `int`), `Min`/`Max` over an *integer*-leaved
    lift only (`min([True, False])` is `bool`, not `int` — the one
    deliberate asymmetry), a literal-valued `SumOver` mapping, `+ - * %`
    over two int-valued operands, `**` with a non-negative literal
    integer exponent, and `IfInactive` when both branches are int-valued.
    Division and anything else outside this closed set is row 12 —
    mirrors the bounds engine's own minimal computable op set (API.md,
    "Expression bounds are sugar")."""
    if isinstance(node, Literal):
        if not isinstance(node.value, int) or isinstance(node.value, bool):
            raise ResolutionError(
                f"{context}: must be integer-typed, got literal {node.value!r} (row 12)"
            )
        return
    if isinstance(node, ParamExpr):
        kind = defs_by_path[node.path].type_kind
        if kind != "integer":
            raise ResolutionError(
                f"{context}: references {node.path!r}, which is {kind!r}, "
                "not integer (row 12)"
            )
        return
    if isinstance(node, Prop):
        # A `.prop()`-driven count (API.md: `.repeat(ds.param("g").prop("n_edges"))`)
        # — check the *declared property type* is int, and deliberately do
        # NOT descend into its operand: the operand is the custom param
        # itself (type_kind "custom"), which is correctly not integer-typed
        # — only the extracted prop value needs to be.
        if prop_type(node, defs_by_path, context=context) is not int:
            raise ResolutionError(
                f"{context}: prop({node.name!r}) is not integer-typed (row 12)"
            )
        return
    if isinstance(node, Count | Size | Length | PositionOf | CountOf):
        return  # always int-valued by construction -- no leaf to check
    if isinstance(node, SumOver):
        if not all(
            isinstance(v, int) and not isinstance(v, bool) for v in node.mapping.values()
        ):
            raise ResolutionError(f"{context}: sum_over() has a non-integer value (row 12)")
        return
    if isinstance(node, Sum | Min | Max):
        if not isinstance(node.operand, ParamExpr):
            raise ResolutionError(
                f"{context}: {node.kind}() over a .field() projection is not "
                "supported as a repeat() count (row 12)"
            )
        elem_kind = _innermost_lift_element_kind(defs_by_path[node.operand.path])
        allowed = ("integer", "bool") if isinstance(node, Sum) else ("integer",)
        if elem_kind not in allowed:
            raise ResolutionError(
                f"{context}: {node.kind}() over a {elem_kind!r}-leaved lift is not "
                "integer-typed (row 12)"
            )
        return
    if isinstance(node, ArithOp):
        if node.op == "div":
            raise ResolutionError(f"{context}: division is not integer-typed (row 12)")
        if node.op == "pow" and not (
            isinstance(node.right, Literal)
            and isinstance(node.right.value, int)
            and not isinstance(node.right.value, bool)
            and node.right.value >= 0
        ):
            raise ResolutionError(
                f"{context}: ** requires a non-negative literal integer exponent to "
                "stay integer-typed (row 12)"
            )
        _check_count_type_node(node.left, defs_by_path, context)
        _check_count_type_node(node.right, defs_by_path, context)
        return
    if isinstance(node, IfInactive):
        _check_count_type_node(node.operand, defs_by_path, context)
        _check_count_type_node(node.fallback, defs_by_path, context)
        return
    raise ResolutionError(f"{context}: must be integer-typed (row 12)")


def _check_count_type(
    path: str, count: int | ArithExpr, defs_by_path: dict[str, ParamExpr]
) -> None:
    if isinstance(count, ArithExpr):
        context = f"param {path!r} repeat() count"
        check_refs_declared(count, defs_by_path, context=context)
        _check_count_type_node(count, defs_by_path, context)
        return
    if not isinstance(count, int) or isinstance(count, bool):
        raise ResolutionError(
            f"param {path!r}: repeat() count must be an int or an integer-typed "
            f"expression, got {count!r} (row 12)"
        )
    if count < 0:
        raise ResolutionError(f"param {path!r}: repeat() count must be >= 0, got {count!r}")


def _validate_list_default_shape(path: str, snap: _ElementSnapshot) -> None:
    if snap.list_default is None:
        return
    if isinstance(snap.count, ArithExpr):
        raise ResolutionError(
            f"param {path!r}: list default requires a static (int) repeat count "
            "at this level (row 21)"
        )
    if not isinstance(snap.list_default, list) or len(snap.list_default) != snap.count:
        raise ResolutionError(
            f"param {path!r}: list default length must match the static repeat "
            f"count ({snap.count}) (row 21)"
        )


def _validate_list_defaults_deep(space: Space) -> None:
    """Row 21, continued: a post-`.repeat()` list default (`.repeat(n)
    .default([...])`) is a literal phenotype value per index — each item
    must itself be a domain member, recursively for struct/choice elements
    (a struct/choice list default is `[{"width": 128}, ...]`-shaped, not a
    flat scalar). `_validate_list_default_shape` (step 7) only checks
    length/static-count; this reuses `validate()`'s own per-instance domain
    checks, so it must run here, *after* `_emit` has built `space.params`
    (struct/choice lift descendants are relocated there under a
    `"[]"`-bracketed prefix and don't exist any earlier in the pipeline).

    Recurses through `ListDomain.element_domain` so every level of a chained
    lift (`.repeat(a).default([...]).repeat(b)`, API.md's "per-level list
    modifiers between lifts") gets its own `list_default` deep-checked, not
    just the outermost. A level below the outermost has no single real
    instance path to hang the check on (the same literal default applies
    identically to every outer instance — confirmed: `apply_defaults` already
    fills it correctly per outer row), so a synthetic placeholder outer index
    (`[0]`) is used at each descent; any index works since every row is
    identical. D-24 forbids struct/choice elements nested under more than one
    `.repeat()`, so a level below the outermost is always scalar/subset/
    permutation — no descendant-template prefix to synthesize, only the
    index. Each level builds its own independent `flat` dict, so multiple
    simultaneous `list_default`s at different levels never collide.
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
                template_prefix=f"{concrete_prefix}[].",
                concrete_prefix=f"{concrete_prefix}[{i}].",
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
                f"its domain ({detail}) (row 21)"
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
    """Shared by a plain top-level choice and a lifted choice element
    (`ListDomain.element_kind == "choice"`, DECISIONS.md D-18/D-20):
    reference `discriminator_path` may be an ordinary definition path
    (`"algo"`) or a `"[]"`-bracketed lift-element template (`"pipeline[]"`)
    — either way it is just another `ParamExpr` leaf reference to rewrite,
    which `relocate_child`'s per-instance sibling (`instantiate_element`)
    already substitutes uniformly alongside the variant's own descendants.
    """
    params: dict[str, ParamDef] = {}
    conditions: list[Condition] = []
    constraints: list[Constraint] = []
    for variant_name in domain.variants:
        payload = choice_payloads.get(variant_name)
        if payload is None:
            continue
        if not isinstance(payload, Space):
            # Row 29 (M10.5 item 7): a bare ParamExpr (or anything else that
            # isn't a Space) as a payload used to reach `relocate_child`
            # below and raise an opaque AttributeError from `child.params`
            # (a Space's Mapping vs. an Expr's frozenset).
            raise ResolutionError(
                f"param {discriminator_path!r}: choice() payload for variant "
                f"{variant_name!r} must be a Space (from ds.space(...)), got "
                f"{type(payload).__name__} (row 29)"
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
                    leaf.struct_space, new_prefix=f"{d.path}[].", injected_condition=None
                )
                params.update(child_params)
                conditions.extend(child_conditions)
                # Element-scoped constraints are per-instance templates
                # (DECISIONS.md D-20) — carried on ListDomain, never
                # flattened into `space.constraints` directly.
                params[d.path] = replace(
                    params[d.path],
                    domain=replace(d.domain, element_constraints=tuple(child_constraints)),
                )
            elif leaf.element_class is ChoiceParamExpr:
                assert isinstance(leaf.domain, ChoiceDomain)
                variant_params, variant_conditions, variant_constraints = (
                    _relocate_choice_variants(
                        f"{d.path}[]", f"{d.path}[].", leaf.domain, leaf.choice_payloads, None
                    )
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
