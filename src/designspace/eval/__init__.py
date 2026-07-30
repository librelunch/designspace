"""eval: Kleene evaluation, activity, and margins (API.md, "Expressions" >
"Three-valued semantics"; "Constraints and Feasibility" > "Margins").

Internal machinery consumed by validate/ and sample/ — not part of the
public surface (the public result types, `ConstraintEval`/`ValidationResult`,
live in ir/).
"""

from designspace.eval._constraint_eval import (
    evaluate_constraint,
    instance_constraint_evals,
    instance_evals_indexed,
    is_violated,
)
from designspace.eval._kleene import (
    UNKNOWN,
    UNKNOWN_INACTIVE,
    UNKNOWN_PENDING,
    UNKNOWN_PERMANENT,
    Kleene,
    PartialActivity,
    Unknown,
    classify_condition,
    compute_activity,
    compute_activity_partial,
    evaluate_arith,
    evaluate_bool,
    local_topological_order,
    status_activity_view,
    topological_order,
)
from designspace.eval._margins import margin

__all__ = [
    "UNKNOWN",
    "UNKNOWN_INACTIVE",
    "UNKNOWN_PENDING",
    "UNKNOWN_PERMANENT",
    "Kleene",
    "PartialActivity",
    "Unknown",
    "classify_condition",
    "compute_activity",
    "compute_activity_partial",
    "evaluate_arith",
    "evaluate_bool",
    "evaluate_constraint",
    "instance_constraint_evals",
    "instance_evals_indexed",
    "is_violated",
    "local_topological_order",
    "margin",
    "status_activity_view",
    "topological_order",
]
