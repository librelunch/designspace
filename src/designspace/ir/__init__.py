"""ir: resolved intermediate representation (API.md, "IR").

Mostly internal — users see this shape through introspection
(`Space.params`, etc.), not by importing these classes directly. M11 is the
one exception (DECISIONS.md D-52): `Encoding.target()`/`decode()`/`encode()`
all take or return a `ParamDef`, so `ParamDef`, `Chart`, `Domain` and its
member classes, `QuantizedSpec`, and the two `RepresentationCheck*` result
types join `designspace`'s top-level exports — not new surface so much as
an acknowledgement of surface `map_params`/`param_from_def`/`space_from_ir`
have exposed since M8 with no way to type-annotate it. Every other name
here stays unexported.
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
    "ValidationResult",
    "ValueRemaining",
    "Weights",
]
