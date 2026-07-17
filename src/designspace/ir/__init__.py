"""ir: resolved intermediate representation (API_v3.md, "IR").

Internal to the library — users see this shape through introspection
(`Space.params`, etc.), not by importing these classes directly, so nothing
here is re-exported from the top-level `designspace` package.
"""

from designspace.ir._domain import (
    BoolDomain,
    CategoricalDomain,
    Domain,
    IntegerDomain,
    OrdinalDomain,
    RealDomain,
)
from designspace.ir._param import Condition, Constraint, ParamDef, QuantizedSpec
from designspace.ir._priors import Log, Logit, Power, Prior, PriorSpec, Weights

__all__ = [
    "BoolDomain",
    "CategoricalDomain",
    "Condition",
    "Constraint",
    "Domain",
    "IntegerDomain",
    "Log",
    "Logit",
    "OrdinalDomain",
    "ParamDef",
    "Power",
    "Prior",
    "PriorSpec",
    "QuantizedSpec",
    "RealDomain",
    "Weights",
]
