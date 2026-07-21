"""designspace: declarative algorithm design spaces.

Public surface grows strictly with implemented milestones; see
PLAN.md.md. Nothing speculative is exported.
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
from designspace.config import config_diff, destructure, flatten, payload, unflatten, variant
from designspace.errors import DesignSpaceError, ResolutionError, SamplingError, SerializationError
from designspace.expr import ArithExpr, BoolExpr, all_, any_, count
from designspace.identity import config_hash
from designspace.ir import (
    IntegerRemaining,
    Log,
    Logit,
    ParamDiff,
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
    "ParamDiff",
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
    "SerializationError",
    "Space",
    "StructParamExpr",
    "SubsetParamExpr",
    "SubsetRemaining",
    "ValueRemaining",
    "__version__",
    "all_",
    "any_",
    "config_diff",
    "config_hash",
    "count",
    "destructure",
    "flatten",
    "param",
    "payload",
    "space",
    "unflatten",
    "variant",
]
