"""designspace: declarative algorithm design spaces.

Public surface grows strictly with implemented milestones; see
IMPLEMENTATION_PLAN.md. Nothing speculative is exported.
"""

from designspace.build import ParamExpr, Space, param, space
from designspace.expr import ArithExpr, BoolExpr, all_, any_, count
from designspace.ir import Log, Logit, Power

__version__ = "0.0.0"

__all__ = [
    "ArithExpr",
    "BoolExpr",
    "Log",
    "Logit",
    "ParamExpr",
    "Power",
    "Space",
    "__version__",
    "all_",
    "any_",
    "count",
    "param",
    "space",
]
