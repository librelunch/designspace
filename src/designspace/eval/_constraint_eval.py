"""Building a `ConstraintEval` from a `Constraint` (shared by validate/ and
sample/): Kleene-evaluate the expression, and if it isn't Unknown, attach
its margin (API.md, "Expressions" rule 4; "Constraints and Feasibility").

`Constraint.expr` is stored exactly as the author wrote it, for both
`.forbid()` and `.constrain()` — introspection and the fingerprint's
structural-identity model both need the literal predicate, not a silently
negated one. `satisfied`/`margin` are therefore a *structural* property of
the expression (the composition-invariant conformance test builds raw
`BoolExpr` trees with no hard/soft framing at all), which means `.forbid()`
and `.constrain()` disagree about which value of `satisfied` is "good":
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
from designspace.ir import Constraint, ConstraintEval, ListDomain


def evaluate_constraint(
    constraint: Constraint, config: dict[str, Any], activity: dict[str, bool], space: Space
) -> ConstraintEval:
    value = evaluate_bool(constraint.expr, config, activity, space)
    if isinstance(value, Unknown):
        return ConstraintEval(
            constraint=constraint, instance_path=None, applicable=False, satisfied=None, margin=None
        )
    return ConstraintEval(
        constraint=constraint,
        instance_path=None,
        applicable=True,
        satisfied=bool(value),
        margin=margin(constraint.expr, config, activity, space),
    )


def instance_constraint_evals(
    space: Space, config: dict[str, Any], activity: dict[str, bool]
) -> list[ConstraintEval]:
    """Constraints declared on a `.space(prebuilt)` lift element
    (DECISIONS.md D-20) — carried as templates on `ListDomain.
    element_constraints`, never in `space.constraints` — instantiated
    once per active instance ("evaluation reports one `ConstraintEval`
    per instance path," API.md "Modifiers and Layering")."""
    from designspace.resolve._relocate import instantiate_constraints

    result: list[ConstraintEval] = []
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
        template_prefix = f"{path}[]."
        for i in range(n):
            concrete_prefix = f"{path}[{i}]."
            for c in instantiate_constraints(
                domain.element_constraints, template_prefix, concrete_prefix
            ):
                ce = evaluate_constraint(c, config, activity, space)
                result.append(replace(ce, instance_path=f"{path}[{i}]"))
    return result


def is_violated(ce: ConstraintEval) -> bool:
    """Whether this evaluation counts against feasibility (forbids) or is
    flagged as a violation (declared constraints).

    Inapplicable (`None`) is never a violation (rule 4). A forbid's stored
    expr names the forbidden state, so it's violated when `satisfied is
    True`; a declared constraint's expr names the desired state, so it's
    violated when `satisfied is False`. Both collapse to one identity:
    `satisfied == hard`.

    A **feasible-predicate** constraint — `origin` `"bound"` (M5,
    resolve/_bounds.py) or `"require"` (M7.5, `space.require`) — is the
    exception: it is always `hard=True` (it must affect feasibility, exactly
    like a forbid) but stores the *desired* predicate verbatim —
    `ds.param("x") <= ds.param("y")`, matching API.md's sugar description and
    yielding the spec's stated `y - x` margin, neither of which the
    forbidden-state form (`x > y`) could give at once (its margin would be
    `x - y`). So its `hard`/polarity pairing is `constrain`-shaped (violated
    iff not satisfied) even though its feasibility impact is `forbid`-shaped —
    `origin` (already provenance, already excluded from the fingerprint
    preimage) is what the two conventions key off instead of `hard` alone.
    This gives `require(e)` its Kleene polarity: violated iff `e` is definitely
    False; an Unknown or True `e` is feasible (Unknown ⇒ inapplicable).
    """
    if ce.constraint.origin in ("bound", "require"):
        return ce.applicable and ce.satisfied is False
    return ce.applicable and ce.satisfied == ce.constraint.hard
