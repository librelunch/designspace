# API reference

Every name `designspace` exports, grouped by what you reach for it to do.
The pages are generated from the docstrings themselves, so they are the same
text `help()` shows.

## Building a space

The entry points, and the builder view a parameter takes on once its type is chosen.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.BoolParamExpr
   designspace.CategoricalParamExpr
   designspace.ChoiceParamExpr
   designspace.CodeParamExpr
   designspace.CustomParamExpr
   designspace.FreshParamExpr
   designspace.IntegerParamExpr
   designspace.ListParamExpr
   designspace.OrdinalParamExpr
   designspace.ParamExpr
   designspace.PermutationParamExpr
   designspace.RealParamExpr
   designspace.Space
   designspace.StructParamExpr
   designspace.SubsetParamExpr
   designspace.SymbolicParamExpr
   designspace.TypedParamExpr
   designspace.param
   designspace.space
```

## Expressions

Conditions, constraints, and derived quantities. Expressions are values: build them, pass them around, walk them with `.kind`/`.children`.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.ArithExpr
   designspace.BoolExpr
   designspace.Expr
   designspace.Prop
   designspace.Value
   designspace.all_
   designspace.any_
   designspace.count
   designspace.value
```

## Working with configs

Reshaping a config without going through a space.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.config_diff
   designspace.destructure
   designspace.flatten
   designspace.payload
   designspace.unflatten
   designspace.variant
```

## Sampling and validation results

What the sampling and checking surfaces hand back.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.ConstraintEval
   designspace.ConstraintReport
   designspace.ParamDiff
   designspace.ParamError
   designspace.PartialEval
   designspace.SamplingReport
   designspace.SubspaceInfo
   designspace.ValidationResult
```

## Identity and serialization

Fingerprints identify spaces; config hashes identify points in one.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.config_hash
```

## The representation layer

A `Representation` is the `Space` to `Space` morphism between a genotype and its phenotype.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.Encoding
   designspace.EncodingRule
   designspace.Representation
   designspace.RepresentationCheck
   designspace.RepresentationCheckFailure
```

## The IR

The resolved form. Every introspection surface hands back these types, and they are what a solver walks.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.BoolDomain
   designspace.CategoricalDomain
   designspace.Chart
   designspace.ChoiceDomain
   designspace.CodeDomain
   designspace.Condition
   designspace.Constraint
   designspace.CustomDomain
   designspace.Domain
   designspace.IntegerDomain
   designspace.IntegerRemaining
   designspace.ListDomain
   designspace.OrdinalDomain
   designspace.ParamDef
   designspace.PermutationDomain
   designspace.PermutationRemaining
   designspace.QuantizedSpec
   designspace.RealDomain
   designspace.RealRemaining
   designspace.RemainingDomain
   designspace.StructDomain
   designspace.SubsetDomain
   designspace.SubsetRemaining
   designspace.SymbolicDomain
   designspace.ValueRemaining
   designspace.param_from_def
   designspace.space_from_ir
```

## Support types

Priors, program-parameter vocabulary, and the custom-type protocols.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.FloatLiteral
   designspace.IntLiteral
   designspace.Log
   designspace.Logit
   designspace.ParamType
   designspace.Power
   designspace.Primitive
   designspace.Prior
   designspace.PriorSpec
   designspace.Signature
   designspace.Weights
```

## Errors

Every error designspace raises names the offending definition path.

```{eval-rst}
.. autosummary::
   :toctree: api

   designspace.DesignSpaceError
   designspace.ResolutionError
   designspace.SamplingError
   designspace.SerializationError
```

## Type aliases

The names the public signatures are written in. Each is exactly the spelling
shown -- they carry no behaviour, and exist so a signature can be followed to
a definition instead of guessed at.

```{eval-rst}

.. py:data:: designspace.Config
   :value: dict[str, Any]

   A configuration: one point of a space, keyed by instance path. Values are in phenotype form; inactive parameters are absent rather than null.

.. py:data:: designspace.Seed
   :value: int | numpy.random.Generator | None

   What every sampling surface accepts as its source of randomness. An `int` seeds reproducibly, a `Generator` is used as given, `None` draws fresh entropy.

.. py:data:: designspace.OnUnserializable
   :value: Literal["raise", "mark", "drop"]

   What `to_json` does with something it cannot serialize.

.. py:data:: designspace.FingerprintScope
   :value: Literal["full", "sampling"]

   Which facts a fingerprint covers: document identity, or what fixes the feasible set and the sampling measure.

.. py:data:: designspace.FingerprintUnserializable
   :value: Literal["raise", "mark"]

   As `OnUnserializable`, minus `drop` -- dropping a site would change what is being identified.
```
