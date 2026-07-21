"""partial: Space — Partial Configs (API.md).

Internal machinery invoked by `build/_space.py`'s partial-config methods —
not part of the public surface (the public result types, `PartialEval`/
`RemainingDomain`, live in `ir`).
"""

from designspace.partial._partial import (
    evaluate_partial,
    is_complete,
    missing_params,
    next_assignable,
    param_activity,
    remaining_domain,
    topological_order,
)

__all__ = [
    "evaluate_partial",
    "is_complete",
    "missing_params",
    "next_assignable",
    "param_activity",
    "remaining_domain",
    "topological_order",
]
