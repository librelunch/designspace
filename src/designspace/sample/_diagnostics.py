"""`.sampling_report()` (API.md, "Sampling diagnostics"; M10.6, PLAN.md).

Aggregation only, over the sampler's **unconditioned** measure — every draw
made from `_draw_config` directly, bypassing `_draw_one`'s retry/rejection
loop entirely, so both pathologies rejection hides (Unknown-swallowing,
funnel bias) are visible. No new evaluation semantics: every value reported
here is an existing `ConstraintEval`/activity fact, folded and divided by
`n`. It reports; it never repairs, reweights, or suggests.
"""

from __future__ import annotations

from types import MappingProxyType

from designspace.build._space import Space
from designspace.eval import evaluate_constraint, instance_evals_indexed, is_violated
from designspace.ir import Constraint, ConstraintEval, ConstraintReport, ListDomain, SamplingReport
from designspace.paths import definition_form
from designspace.resolve._bounds import bound_origin_targets
from designspace.resolve._pipeline import check_fully_resolved
from designspace.sample._sample import BoundTargets, Seed, _draw_config, _rng_from_seed

ElementKey = tuple[str, int]  # (owning list's definition path, template index)


def _element_constraint_templates(space: Space) -> dict[ElementKey, Constraint]:
    """Every `ListDomain.element_constraints` template, keyed by (owning
    list path, position within that lift's own template tuple) — walked in
    `space.params`' declaration order, so a lift that is *never* active
    across all `n` draws still contributes a row (`applicable == 0.0`),
    rather than the row silently vanishing because no instance was ever
    observed."""
    templates: dict[ElementKey, Constraint] = {}
    for path, pd in space.params.items():
        if pd.type_kind != "list":
            continue
        domain = pd.domain
        assert isinstance(domain, ListDomain)
        for idx, c in enumerate(domain.element_constraints):
            templates[(path, idx)] = c
    return templates


def sampling_report(
    space: Space, n: int = 1000, seed: Seed = None, tighten_bounds: bool = False
) -> SamplingReport:
    check_fully_resolved(space)
    if n < 1:
        raise TypeError(f"sampling_report: n must be >= 1 (got {n!r})")
    rng = _rng_from_seed(seed)
    # Best-effort bound-origin tightening is off by default (D-74): drawing
    # from `bound_targets={}` matches `_draw_config`'s own untightened path
    # and keeps the unconditioned measure blind to the sampler's own
    # optimization, which would otherwise launder exactly the rows this
    # report exists to show honestly.
    bound_targets: BoundTargets = bound_origin_targets(space) if tighten_bounds else {}

    element_templates = _element_constraint_templates(space)
    scalar_applicable = [0] * len(space.constraints)
    scalar_satisfied = [0] * len(space.constraints)
    element_applicable = dict.fromkeys(element_templates, 0)
    element_satisfied = dict.fromkeys(element_templates, 0)
    activity_counts = dict.fromkeys(space.params, 0)
    accepted = 0

    for _ in range(n):
        config, activity = _draw_config(space, rng, bound_targets)
        draw_ok = True

        for i, c in enumerate(space.constraints):
            ce = evaluate_constraint(c, config, activity, space)
            if ce.applicable:
                scalar_applicable[i] += 1
                if ce.satisfied:
                    scalar_satisfied[i] += 1
            if c.hard and is_violated(ce):
                draw_ok = False

        # Per-draw fold (D-73): group this draw's instance evals back onto
        # their template key, then applicable/satisfied are decided once
        # per (draw, template) rather than once per (draw, instance) — but
        # the accept/reject decision below still checks every individual
        # instance eval, exactly mirroring `_draw_one`'s own rejection rule.
        by_template: dict[ElementKey, list[ConstraintEval]] = {}
        for path, idx, ce in instance_evals_indexed(space, config, activity):
            key = (path, idx)
            by_template.setdefault(key, []).append(ce)
            if element_templates[key].hard and is_violated(ce):
                draw_ok = False
        for key, evals in by_template.items():
            applicable_evals = [ce for ce in evals if ce.applicable]
            if applicable_evals:
                element_applicable[key] += 1
                if all(ce.satisfied for ce in applicable_evals):
                    element_satisfied[key] += 1

        # Same fold for activity: a definition-path key with no brackets is
        # its own sole "instance," active iff `activity[path]` says so; a
        # `"[]"`-templated key (a lifted struct/choice field) is active this
        # draw iff at least one concrete instance folded to it was active.
        # `definition_form` of a plain scalar lift's own element path
        # (`"bufs[0]"` -> `"bufs[]"`) never matches a `space.params` key —
        # such lifts publish no separate element `ParamDef` — so it drops
        # out of `activity_counts` harmlessly.
        active_templates: set[str] = set()
        for path, active in activity.items():
            if active:
                active_templates.add(definition_form(path))
        for template_path in active_templates:
            if template_path in activity_counts:
                activity_counts[template_path] += 1

        if draw_ok:
            accepted += 1

    rows: list[ConstraintReport] = [
        ConstraintReport(
            constraint=c,
            applicable=scalar_applicable[i] / n,
            satisfied=(scalar_satisfied[i] / scalar_applicable[i] if scalar_applicable[i] else 0.0),
        )
        for i, c in enumerate(space.constraints)
    ]
    rows.extend(
        ConstraintReport(
            constraint=element_templates[key],
            applicable=element_applicable[key] / n,
            satisfied=(
                element_satisfied[key] / element_applicable[key] if element_applicable[key] else 0.0
            ),
        )
        for key in element_templates
    )

    activity_fractions: dict[str, float] = {p: activity_counts[p] / n for p in space.params}
    return SamplingReport(
        n=n,
        acceptance_rate=accepted / n,
        constraints=tuple(rows),
        activity=MappingProxyType(activity_fractions),
    )
