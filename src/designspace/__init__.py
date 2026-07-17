"""designspace: declarative algorithm design spaces.

Public surface grows strictly with implemented milestones; see
IMPLEMENTATION_PLAN.md. Nothing speculative is exported.
"""

from designspace.expr import ArithExpr, BoolExpr, all_, any_, count

__version__ = "0.0.0"

__all__ = ["ArithExpr", "BoolExpr", "__version__", "all_", "any_", "count"]
