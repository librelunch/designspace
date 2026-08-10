"""Declarative design spaces with a polars-like expression API.

A design space is the set of configurations a system can take: an
algorithm, a model, a process, or a physical assembly. A space is declared
once, giving the parameters, their domains, the condition under which each
is active, and the combinations that are legal.

Spaces are built from `space` and `param`. `param` names a parameter and
gives it a type, and the chainable modifiers that follow set its prior, the
condition under which it is active, and its default. Every `Space` is
immutable, so each operation on one returns a new space.

A declared space can be sampled, validated against, serialized, or compared
with another space by fingerprint. Sampling interprets the priors that were
declared. It is not an optimizer. The library declares spaces and does not
search them, and ships no search operators, distances, or neighborhoods.

Examples
--------
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("optimizer").categorical("adam", "sgd"),
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("momentum").real(0.0, 0.99).when(ds.param("optimizer") == "sgd"),
... )
>>> sgd = space.sample_one(seed=0)
>>> sgd["optimizer"]
'sgd'

A parameter whose condition does not hold is absent from the configuration
rather than present and null.

>>> adam = space.sample_one(seed=3)
>>> "momentum" in adam
False
"""

from designspace.builder import (
    BoolParamExpr,
    CategoricalParamExpr,
    ChoiceParamExpr,
    CodeParamExpr,
    CustomParamExpr,
    FreshParamExpr,
    IntegerParamExpr,
    ListParamExpr,
    OrdinalParamExpr,
    ParamExpr,
    PermutationParamExpr,
    RealParamExpr,
    Seed,
    Space,
    StructParamExpr,
    SubsetParamExpr,
    SymbolicParamExpr,
    TypedParamExpr,
    param,
    space,
)
from designspace.config import (
    config_diff,
    destructure,
    flatten,
    is_flat,
    payload,
    unflatten,
    variant,
)
from designspace.custom import ParamType
from designspace.display import pretty
from designspace.errors import DesignSpaceError, ResolutionError, SamplingError, SerializationError
from designspace.expr import ArithExpr, BoolExpr, Expr, Prop, Value, all_, any_, count, value
from designspace.identity import (
    FingerprintScope,
    FingerprintUnserializable,
    OnUnserializable,
    config_hash,
)
from designspace.ir import (
    BoolDomain,
    CategoricalDomain,
    Chart,
    ChoiceDomain,
    CodeDomain,
    Condition,
    Constraint,
    ConstraintEval,
    ConstraintReport,
    CustomDomain,
    Domain,
    IntegerDomain,
    IntegerRemaining,
    ListDomain,
    Log,
    Logit,
    OrdinalDomain,
    ParamDef,
    ParamDiff,
    ParamError,
    PartialEval,
    PermutationDomain,
    PermutationRemaining,
    Power,
    Prior,
    PriorSpec,
    QuantizedSpec,
    RealDomain,
    RealRemaining,
    RemainingDomain,
    RepresentationCheck,
    RepresentationCheckFailure,
    SamplingReport,
    StructDomain,
    SubsetDomain,
    SubsetRemaining,
    SubspaceInfo,
    SymbolicDomain,
    ValidationResult,
    ValueRemaining,
    Weights,
)
from designspace.meta import param_from_def, space_from_ir
from designspace.program import FloatLiteral, IntLiteral, Primitive, Signature
from designspace.represent import Config, Encoding, EncodingRule, Representation

__version__ = "0.0.0"

__all__ = [
    "ArithExpr",
    "BoolDomain",
    "BoolExpr",
    "BoolParamExpr",
    "CategoricalDomain",
    "CategoricalParamExpr",
    "Chart",
    "ChoiceDomain",
    "ChoiceParamExpr",
    "CodeDomain",
    "CodeParamExpr",
    "Condition",
    "Config",
    "Constraint",
    "ConstraintEval",
    "ConstraintReport",
    "CustomDomain",
    "CustomParamExpr",
    "DesignSpaceError",
    "Domain",
    "Encoding",
    "EncodingRule",
    "Expr",
    "FingerprintScope",
    "FingerprintUnserializable",
    "FloatLiteral",
    "FreshParamExpr",
    "IntLiteral",
    "IntegerDomain",
    "IntegerParamExpr",
    "IntegerRemaining",
    "ListDomain",
    "ListParamExpr",
    "Log",
    "Logit",
    "OnUnserializable",
    "OrdinalDomain",
    "OrdinalParamExpr",
    "ParamDef",
    "ParamDiff",
    "ParamError",
    "ParamExpr",
    "ParamType",
    "PartialEval",
    "PermutationDomain",
    "PermutationParamExpr",
    "PermutationRemaining",
    "Power",
    "Primitive",
    "Prior",
    "PriorSpec",
    "Prop",
    "QuantizedSpec",
    "RealDomain",
    "RealParamExpr",
    "RealRemaining",
    "RemainingDomain",
    "Representation",
    "RepresentationCheck",
    "RepresentationCheckFailure",
    "ResolutionError",
    "SamplingError",
    "SamplingReport",
    "Seed",
    "SerializationError",
    "Signature",
    "Space",
    "StructDomain",
    "StructParamExpr",
    "SubsetDomain",
    "SubsetParamExpr",
    "SubsetRemaining",
    "SubspaceInfo",
    "SymbolicDomain",
    "SymbolicParamExpr",
    "TypedParamExpr",
    "ValidationResult",
    "Value",
    "ValueRemaining",
    "Weights",
    "__version__",
    "all_",
    "any_",
    "config_diff",
    "config_hash",
    "count",
    "destructure",
    "flatten",
    "is_flat",
    "param",
    "param_from_def",
    "payload",
    "pretty",
    "space",
    "space_from_ir",
    "unflatten",
    "value",
    "variant",
]
