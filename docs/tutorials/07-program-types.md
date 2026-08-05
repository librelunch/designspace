---
file_format: mystnb
---

# Program types

A tree or a source string is a genotype, and generating one is solver
territory. Core's job is narrower: **declare** the space through a signature, a
primitive vocabulary and a depth budget; **validate** submitted values against
that declaration; and carry them through every existing surface without ever
generating or evaluating one.

## Declaring a symbolic parameter

`.symbolic()` takes a `Signature`, a primitive vocabulary and a maximum depth.
Values have the shape `{"ast": <node>, "source": <str>}`, where `"source"` is
optional.

```{code-cell}
import designspace as ds

SIGNATURE = ds.Signature({"step": int, "total": int}, float)
PRIMITIVES = ["cos", "pi", "/", ds.Primitive("*", 2)]

SCHEDULE = {
    "ast": {
        "op": "cos",
        "args": [
            {
                "op": "*",
                "args": [
                    {"op": "pi", "args": []},
                    {"op": "/", "args": [{"var": "step"}, {"var": "total"}]},
                ],
            }
        ],
    },
    "source": "cos(pi * (step / total))",
}

space = ds.space(
    ds.param("schedule").symbolic(SIGNATURE, PRIMITIVES, max_depth=4).default(SCHEDULE),
    ds.param("acceptance")
    .code(
        ds.Signature({"delta": float}, bool),
        description="Metropolis acceptance criterion",
        examples=[{"delta": -1.0}],
    )
    .default({"source": "delta < 0"}),
)
space.params["schedule"].domain.max_depth
```

`.code()` declares freeform source with the shape `{"source": <str>}`. Its
`description`, `constraints` and `examples` are declared, serialized,
fingerprinted metadata for a consumer's own backend.

```{code-cell}
space.params["acceptance"].domain.description
```

## Structural validation

Core checks the tree's *structure*: the vocabulary this parameter declared,
arity where a `Primitive` declares one, variable names drawn from
`signature.args`, literal bounds, and depth within `max_depth`. It assigns no
meaning to a primitive name and ships no evaluator.

```{code-cell}
space.validate({"schedule": SCHEDULE, "acceptance": {"source": "delta < 0"}}).valid
```

An operator outside the declared vocabulary is rejected:

```{code-cell}
space.validate_param("schedule", {"ast": {"op": "sin", "args": []}}).param_errors
```

So is a tree past the depth budget:

```{code-cell}
deep = {"ast": {"op": "pi", "args": []}}
for _ in range(5):
    deep = {"ast": {"op": "cos", "args": [deep["ast"]]}}
space.validate_param("schedule", deep).param_errors
```

And a variable the signature does not declare:

```{code-cell}
space.validate_param("schedule", {"ast": {"var": "epoch"}}).param_errors
```

## Open vocabulary, checked arity

A bare string names a primitive with no arity attached, so it structurally
accepts any number of arguments. `ds.Primitive(name, arity)` pins one, as an
exact integer or a `(lo, hi)` range.

```{code-cell}
three_args = {"ast": {"op": "+", "args": [{"var": "step"}] * 3}}

open_arity = ds.space(ds.param("e").symbolic(SIGNATURE, ["+"], max_depth=2))
pinned = ds.space(
    ds.param("e").symbolic(SIGNATURE, [ds.Primitive("+", 2)], max_depth=2)
)
(
    open_arity.validate_param("e", three_args).valid,
    pinned.validate_param("e", three_args).valid,
)
```

```{code-cell}
:tags: [remove-output]

assert open_arity.validate_param("e", three_args).valid
assert not pinned.validate_param("e", three_args).valid
```

## Generativity

`.code()` is always non-generative, since no `sampler=` form exists.
`.symbolic()` is non-generative unless `sampler=` is given.

```{code-cell}
bare = ds.space(ds.param("e").symbolic(SIGNATURE, ["cos"], max_depth=2))
bare.has_nongenerative_params
```

```{code-cell}
try:
    bare.sample_one(seed=0)
except ds.SamplingError as exc:
    print(exc)
```

A `.default()` satisfies that obligation, and so does `freeze`:

```{code-cell}
bare.freeze(e={"ast": {"op": "cos", "args": []}}).sample_one(seed=0)
```

Supplying a `sampler=` makes the parameter generative:

```{code-cell}
generative = ds.space(
    ds.param("e").symbolic(
        SIGNATURE,
        ["cos"],
        max_depth=2,
        sampler=lambda rng: {"ast": {"op": "cos", "args": []}},
    )
)
generative.has_nongenerative_params, generative.sample_one(seed=0)
```

Unlike a `.custom()` parameter, a program parameter can be removed outright by
`.slice()`:

```{code-cell}
sliced = ds.space(
    ds.param("e").symbolic(SIGNATURE, ["cos"], max_depth=2),
    ds.param("x").real(0.0, 1.0),
).slice(e={"ast": {"op": "cos", "args": []}})
list(sliced.params)
```

## Per-field opacity

Core never calls `Primitive.fn`. Like `validators` and `.symbolic()`'s
`sampler`, it rides the non-serializable set: `to_json` raises by default, and
`on_unserializable="mark"` degrades just that one field in place rather than the
whole parameter.

```{code-cell}
opaque = ds.space(
    ds.param("e").symbolic(
        SIGNATURE, ["cos"], max_depth=2, validators=[lambda ast: True]
    )
)
try:
    opaque.to_json()
except ds.SerializationError as exc:
    print(exc)
```

```{code-cell}
opaque.to_json(on_unserializable="mark")["params"][0]["domain"]["validators"]
```

## Where to go next

[Structural operations](08-structural-operations.md) reshapes a space after it
has been built.
