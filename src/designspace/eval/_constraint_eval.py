"""Building a `ConstraintEval` from a `Constraint`.

Shared by `validate/` and `sample/`. The expression is Kleene-evaluated,
and its margin attached when the result is not Unknown. See API.md,
"Expressions" rule 4 and "Constraints and Feasibility".

`Constraint.expr` is stored exactly as the author wrote it, for `.forbid()`
and `.encourage()` alike, because introspection and the fingerprint's
structural-identity model both need the literal predicate rather than a
silently negated one.

`satisfied` and `margin` are therefore structural properties of the
expression; the composition-invariant conformance law builds raw `BoolExpr`
trees with no hard or soft framing at all. `.forbid()` and `.encourage()`
consequently disagree about which value of `satisfied` is good. A forbid's
expression names the forbidden state, so `lr > 0.1` is bad when true, while
a declared constraint's expression names the desired state, so `sum <= 4096`
is good when true. `is_violated` below is where that polarity distinction is
resolved.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from designspace.builder._space import Space
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
    """`instance_constraint_evals`'s walk, tagged by owning lift and template.

    Each eval carries `(owning list path, template index)`: the owning
    lift's definition path, and the position within
    `domain.element_constraints` of the template `Constraint` this eval
    instantiates. `instance_constraint_evals` is a thin projection that
    drops the tag.

    `sample/_diagnostics.py` needs the tag to fold per-instance evals back
    onto one `ConstraintReport` row per template, grouping across instances
    and across draws without re-walking `element_constraints` or depending
    on flat-list ordering.
    """
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
    """Instantiate a lift element's own constraints, once per active instance.

    Constraints declared on a `.space(prebuilt)` lift element are carried as
    templates on `ListDomain.element_constraints` rather than in
    `space.constraints`. API.md, "Modifiers and Layering" requires that
    "evaluation reports one `ConstraintEval` per instance path".
    """
    return [ce for _path, _idx, ce in instance_evals_indexed(space, config, activity)]


def is_violated(ce: ConstraintEval) -> bool:
    """Whether this evaluation counts against feasibility (a hard
    forbid/require) or is flagged as a violation (a soft encourage/discourage).

    A thin alias for `ConstraintEval.violated` in `ir/_results.py`, kept
    under the name `validate/` and `sample/` already import.

    `Constraint.feasible_when_satisfied` centralizes the polarity: `forbid`
    and `discourage` name the forbidden state and are violated when
    satisfied, while the other verbs name the desired state and are violated
    when not satisfied. A bound sugar and a `require`, both storing the
    desired predicate, therefore get the right Kleene behaviour for free.
    Each is violated exactly when its predicate is definitely False; an
    Unknown or True predicate is feasible, Unknown being inapplicable under
    rule 4.
    """
    return ce.violated
