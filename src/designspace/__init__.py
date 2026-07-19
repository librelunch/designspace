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
from designspace.ir import (
    IntegerRemaining,
    Log,
    Logit,
    PartialEval,
    PermutationRemaining,
    Power,
    RealRemaining,
    RemainingDomain,
    SubsetRemaining,
    ValueRemaining,
)

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
    "IntegerRemaining",
    "ListParamExpr",
    "Log",
    "Logit",
    "OrdinalParamExpr",
    "ParamExpr",
    "PartialEval",
    "PermutationParamExpr",
    "PermutationRemaining",
    "Power",
    "RealParamExpr",
    "RealRemaining",
    "RemainingDomain",
    "ResolutionError",
    "SamplingError",
    "Space",
    "StructParamExpr",
    "SubsetParamExpr",
    "SubsetRemaining",
    "ValueRemaining",
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
