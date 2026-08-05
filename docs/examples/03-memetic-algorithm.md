# Memetic algorithm

The most expressive shape a space takes. The configuration is not a fixed
record but a sequence of operators of runtime-determined length, plus a
schedule that is itself a small vector.

Source: `examples/03_memetic_algorithm.py`. Run it with
`uv run python examples/03_memetic_algorithm.py`.

## Declaring the space

`.repeat(count)` lifts an element definition into a list. When the count
references another parameter the list is *variable-length*, and its length
becomes part of the config. Lifting a choice gives a heterogeneous list whose
elements are different operator variants.

The aggregates operate on the lift as a whole. `.count_of(variant)` counts
matching variants, and `.length()`, `.distinct()`, `.sum()`, `.min()`, `.max()`
and `.is_sorted()` apply to a scalar lift. `restart_intensity[-1]` is a
negative instance index, resolved against the realized length.

All four constraint verbs appear. `forbid` and `require` are hard and define
feasibility; `discourage` and `encourage` are declared, reported and never
enforced. Each pair differs in polarity: `forbid` and `discourage` name the
undesirable state, `require` and `encourage` the desired one.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: build_space
```

## Batch sampling

Every config drawn is feasible by construction, because the sampler rejects any
pipeline lacking a local-search step.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_batch_sampling
```

## One pipeline, and the flat round-trip

`ds.flatten` keys a nested config by instance path and `ds.unflatten` rebuilds
it. The round-trip is exact.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_one_pipeline
```

## Reading constraints without re-deriving polarity

`constraint.kind` labels the verb and `ConstraintEval.violated` folds in that
verb's polarity, so a display built on the two is correct whichever verb
produced the row. Swapping a `forbid` for a `require`, or an `encourage` for a
`discourage`, and flipping the condition leaves this block unchanged.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_constraint_polarity
```

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_infeasible_pipeline
```

## Rewriting every parameter

`.map_params(fn)` rewrites every `ParamDef` in the space through a function. It
reaches parameters wherever they live, including inside a lifted choice's
variant payloads, so the caller does not need to know each one's path in
advance.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_map_params
```

`.without_constraints(tags=)` drops declared constraints by tag.

```{literalinclude} ../../examples/03_memetic_algorithm.py
:pyobject: show_without_constraints
```
