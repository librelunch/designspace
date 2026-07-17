"""Building a `ConstraintEval` from a `Constraint` (shared by validate/ and
sample/): Kleene-evaluate the expression, and if it isn't Unknown, attach
its margin (API_v3.md, "Expressions" rule 4; "Constraints and Feasibility").

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

from typing import Any

from designspace.build._space import Space
from designspace.eval._kleene import Unknown, evaluate_bool
from designspace.eval._margins import margin
from designspace.ir import Constraint, ConstraintEval


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


def is_violated(ce: ConstraintEval) -> bool:
    """Whether this evaluation counts against feasibility (forbids) or is
    flagged as a violation (declared constraints).

    Inapplicable (`None`) is never a violation (rule 4). A forbid's stored
    expr names the forbidden state, so it's violated when `satisfied is
    True`; a declared constraint's expr names the desired state, so it's
    violated when `satisfied is False`. Both collapse to one identity:
    `satisfied == hard`.
    """
    return ce.applicable and ce.satisfied == ce.constraint.hard
