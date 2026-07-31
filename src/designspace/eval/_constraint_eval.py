"""Building a `ConstraintEval` from a `Constraint` (shared by validate/ and
sample/): Kleene-evaluate the expression, and if it isn't Unknown, attach
its margin (API.md, "Expressions" rule 4; "Constraints and Feasibility").

`Constraint.expr` is stored exactly as the author wrote it, for both
`.forbid()` and `.encourage()` — introspection and the fingerprint's
structural-identity model both need the literal predicate, not a silently
negated one. `satisfied`/`margin` are therefore a *structural* property of
the expression (the composition-invariant conformance test builds raw
`BoolExpr` trees with no hard/soft framing at all), which means `.forbid()`
and `.encourage()` disagree about which value of `satisfied` is "good":
a forbid's expr names the *forbidden* state (`lr > 0.1` — bad when true),
while a declared constraint's expr names the *desired* state (`sum <= 4096`
— good when true). `is_violated` below is the one place that polarity
distinction is resolved — see DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from designspace.build._space import Space
from designspace.eval._kleene import Unknown, evaluate_bool
from designspace.eval._margins import margin
from designspace.expr import Value
from designspace.ir import Constraint, ConstraintEval, ListDomain
from designspace.paths._grammar import element_prefix, instance_prefix


def evaluate_constraint(
    constraint: Constraint, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> ConstraintEval:
    # Shared across both the satisfaction walk (evaluate_bool) and the
    # margin walk (margin(), which independently re-evaluates the same
    # Compare leaves) so a ds.value node's fn is called once per
    # evaluate_constraint(), not twice.
    value_cache: dict[Value, Any] = {}
    value = evaluate_bool(constraint.expr, config, activity, space, value_cache=value_cache)
    if isinstance(value, Unknown):
        return ConstraintEval(
            constraint=constraint, instance_path=None, applicable=False, satisfied=None, margin=None
        )
    return ConstraintEval(
        constraint=constraint,
        instance_path=None,
        applicable=True,
        satisfied=bool(value),
        margin=margin(constraint.expr, config, activity, space, value_cache=value_cache),
    )


def instance_evals_indexed(
    space: Space, config: dict[str, Any], activity: dict[str, bool]
) -> list[tuple[str, int, ConstraintEval]]:
    """`instance_constraint_evals`'s underlying walk, additionally tagged
    with `(owning list path, template index)` per eval — the owning lift's
    definition path and the position of the *template* `Constraint` within
    `domain.element_constraints`, i.e. which declared per-element
    constraint this eval instantiates. `instance_constraint_evals` is a
    thin projection of this (drops the tag); `sample/_diagnostics.py`
    needs the tag to fold per-instance evals back onto one
    `ConstraintReport` row per template (D-73), grouping across instances
    and across draws without re-walking `element_constraints` itself or
    depending on flat-list ordering."""
    from designspace.resolve._relocate import instantiate_constraints

    result: list[tuple[str, int, ConstraintEval]] = []
    for path, pd in space.params.items():
        if pd.type_kind != "list":
            continue
        domain = pd.domain
        assert isinstance(domain, ListDomain)
        if not domain.element_constraints or not activity.get(path, True):
            continue
        n = config.get(path, 0)
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            continue
        template_prefix = element_prefix(path)
        for i in range(n):
            concrete_prefix = instance_prefix(path, i)
            instantiated = instantiate_constraints(
                domain.element_constraints, template_prefix, concrete_prefix
            )
            for template_idx, c in enumerate(instantiated):
                ce = evaluate_constraint(c, config, activity, space)
                result.append((path, template_idx, replace(ce, instance_path=f"{path}[{i}]")))
    return result


def instance_constraint_evals(
    space: Space, config: dict[str, Any], activity: dict[str, bool]
) -> list[ConstraintEval]:
    """Constraints declared on a `.space(prebuilt)` lift element
    (DECISIONS.md D-20) — carried as templates on `ListDomain.
    element_constraints`, never in `space.constraints` — instantiated
    once per active instance ("evaluation reports one `ConstraintEval`
    per instance path," API.md "Modifiers and Layering")."""
    return [ce for _path, _idx, ce in instance_evals_indexed(space, config, activity)]


def is_violated(ce: ConstraintEval) -> bool:
    """Whether this evaluation counts against feasibility (a hard
    forbid/require) or is flagged as a violation (a soft encourage/discourage).

    Thin alias for `ConstraintEval.violated` (ir/_results.py), kept as the
    name validate/ and sample/ already import. The polarity — a `forbid`/
    `discourage` names the *forbidden* state (violated when satisfied), the
    other verbs name the *desired* state (violated when not satisfied) — is
    centralized in `Constraint.feasible_when_satisfied`, so a bound sugar and a
    `require` (both storing the desired predicate) get the right Kleene
    behavior for free: violated iff the predicate is definitely False; an
    Unknown or True predicate is feasible (Unknown ⇒ inapplicable, rule 4).
    """
    return ce.violated
