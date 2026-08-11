"""ir: resolved intermediate representation (API.md, "IR").

Mostly internal: a user sees this shape through introspection, as through
`Space.params`, rather than by importing these classes.

The representation layer is the exception. `Encoding.target()`, `.decode()`
and `.encode()` all take or return a `ParamDef`, so `ParamDef`, `Chart`,
`Domain` and its member classes, `QuantizedSpec`, and the two
`RepresentationCheck` result types are exported from `designspace`. That
makes annotatable the surface `map_params`, `param_from_def` and
`space_from_ir` already expose. Every other name here stays unexported.
"""

from designspace.ir._chart import Chart
from designspace.ir._domain import (
    BoolDomain,
    CategoricalDomain,
    ChoiceDomain,
    CodeDomain,
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
    SymbolicDomain,
    TypeKind,
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
    RepresentationCheck,
    RepresentationCheckFailure,
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
    "CodeDomain",
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
    "RepresentationCheck",
    "RepresentationCheckFailure",
    "SamplingReport",
    "StructDomain",
    "SubsetDomain",
    "SubsetRemaining",
    "SubspaceInfo",
    "SymbolicDomain",
    "TypeKind",
    "ValidationResult",
    "ValueRemaining",
    "Weights",
]
