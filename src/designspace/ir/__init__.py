"""ir: resolved intermediate representation (API_v3.md, "IR").

Internal to the library — users see this shape through introspection
(`Space.params`, etc.), not by importing these classes directly, so nothing
here is re-exported from the top-level `designspace` package.
"""

from designspace.ir._chart import Chart
from designspace.ir._domain import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    Domain,
    IntegerDomain,
    OrdinalDomain,
    PermutationDomain,
    RealDomain,
    StructDomain,
    SubsetDomain,
)
from designspace.ir._param import Condition, Constraint, ParamDef, QuantizedSpec
from designspace.ir._priors import Log, Logit, Power, Prior, PriorSpec, Weights
from designspace.ir._results import ConstraintEval, ParamError, ValidationResult

__all__ = [
    "BoolDomain",
    "CategoricalDomain",
    "Chart",
    "ChoiceDomain",
    "Condition",
    "Constraint",
    "ConstraintEval",
    "Domain",
    "IntegerDomain",
    "Log",
    "Logit",
    "OrdinalDomain",
    "ParamDef",
    "ParamError",
    "PermutationDomain",
    "Power",
    "Prior",
    "PriorSpec",
    "QuantizedSpec",
    "RealDomain",
    "StructDomain",
    "SubsetDomain",
    "ValidationResult",
    "Weights",
]
