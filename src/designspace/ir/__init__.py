"""ir: resolved intermediate representation (API.md, "IR").

Internal to the library — users see this shape through introspection
(`Space.params`, etc.), not by importing these classes directly, so nothing
here is re-exported from the top-level `designspace` package.
"""

from designspace.ir._chart import Chart
from designspace.ir._domain import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CustomDomain,
    Domain,
    IntegerDomain,
    ListDomain,
    OrdinalDomain,
    PermutationDomain,
    QuantizedSpec,
    RealDomain,
    StructDomain,
    SubsetDomain,
)
from designspace.ir._param import Condition, Constraint, ParamDef
from designspace.ir._priors import Log, Logit, Power, Prior, PriorSpec, Weights
from designspace.ir._results import (
    ConstraintEval,
    ConstraintReport,
    IntegerRemaining,
    ParamDiff,
    ParamError,
    PartialEval,
    PermutationRemaining,
    RealRemaining,
    RemainingDomain,
    SamplingReport,
    SubsetRemaining,
    SubspaceInfo,
    ValidationResult,
    ValueRemaining,
)

__all__ = [
    "BoolDomain",
    "CategoricalDomain",
    "Chart",
    "ChoiceDomain",
    "Condition",
    "Constraint",
    "ConstraintEval",
    "ConstraintReport",
    "CustomDomain",
    "Domain",
    "IntegerDomain",
    "IntegerRemaining",
    "ListDomain",
    "Log",
    "Logit",
    "OrdinalDomain",
    "ParamDef",
    "ParamDiff",
    "ParamError",
    "PartialEval",
    "PermutationDomain",
    "PermutationRemaining",
    "Power",
    "Prior",
    "PriorSpec",
    "QuantizedSpec",
    "RealDomain",
    "RealRemaining",
    "RemainingDomain",
    "SamplingReport",
    "StructDomain",
    "SubsetDomain",
    "SubsetRemaining",
    "SubspaceInfo",
    "ValidationResult",
    "ValueRemaining",
    "Weights",
]
