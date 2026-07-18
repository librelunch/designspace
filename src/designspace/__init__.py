"""designspace: declarative algorithm design spaces.

Public surface grows strictly with implemented milestones; see
IMPLEMENTATION_PLAN.md. Nothing speculative is exported.
"""

from designspace.build import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    FreshParamExpr,
    IntegerParamExpr,
    ListParamExpr,
    OrdinalParamExpr,
    ParamExpr,
    PermutationParamExpr,
    RealParamExpr,
    Space,
    StructParamExpr,
    SubsetParamExpr,
    param,
    space,
)
from designspace.config import destructure, flatten, payload, unflatten, variant
from designspace.errors import DesignSpaceError, ResolutionError, SamplingError
from designspace.expr import ArithExpr, BoolExpr, all_, any_, count
from designspace.ir import Log, Logit, Power

__version__ = "0.0.0"

__all__ = [
    "ArithExpr",
    "BoolExpr",
    "BoolParamExpr",
    "CategoricalParamExpr",
    "ChoiceParamExpr",
    "DesignSpaceError",
    "FreshParamExpr",
    "IntegerParamExpr",
    "ListParamExpr",
    "Log",
    "Logit",
    "OrdinalParamExpr",
    "ParamExpr",
    "PermutationParamExpr",
    "Power",
    "RealParamExpr",
    "ResolutionError",
    "SamplingError",
    "Space",
    "StructParamExpr",
    "SubsetParamExpr",
    "__version__",
    "all_",
    "any_",
    "count",
    "destructure",
    "flatten",
    "param",
    "payload",
    "space",
    "unflatten",
    "variant",
]
