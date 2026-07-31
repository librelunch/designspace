"""designspace: declarative algorithm design spaces.

Public surface grows strictly with implemented milestones; see
PLAN.md.md. Nothing speculative is exported.
"""

from designspace.build import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    CustomParamExpr,
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
    TypedParamExpr,
    param,
    space,
)
from designspace.config import config_diff, destructure, flatten, payload, unflatten, variant
from designspace.custom import ParamType
from designspace.errors import DesignSpaceError, ResolutionError, SamplingError, SerializationError
from designspace.expr import ArithExpr, BoolExpr, all_, any_, count, value
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
    SubspaceInfo,
    ValueRemaining,
)
from designspace.meta import param_from_def, space_from_ir

__version__ = "0.0.0"

__all__ = [
    "ArithExpr",
    "BoolExpr",
    "BoolParamExpr",
    "CategoricalParamExpr",
    "ChoiceParamExpr",
    "CustomParamExpr",
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
    "ParamType",
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
    "SubspaceInfo",
    "TypedParamExpr",
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
    "param_from_def",
    "payload",
    "space",
    "space_from_ir",
    "unflatten",
    "value",
    "variant",
]
