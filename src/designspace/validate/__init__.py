"""validate: `.validate()` / `.is_feasible()` / etc. (API.md, "Space — Validation")."""

from designspace.validate._validate import (
    evaluate_constraints,
    infeasibility_reasons,
    is_feasible,
    validate,
    validate_param,
)

__all__ = [
    "evaluate_constraints",
    "infeasibility_reasons",
    "is_feasible",
    "validate",
    "validate_param",
]
