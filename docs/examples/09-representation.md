# The representation layer

A genotype is a `Space` too. A NAS-shaped hyperparameter space is handed to a
solver that only understands continuous unit coordinates, first through the
induced chart representation and then through a supplied morphism written
entirely against the public surface.

Source: `examples/09_representation.py`. Run it with
`uv run python examples/09_representation.py`.

## Declaring the space

```{literalinclude} ../../examples/09_representation.py
:pyobject: build_space
```

## The induced representation

`space.represent()` with no rules builds the one representation core ships. It
is derived mechanically from the charts already on the declaration and never
chosen.

It touches every parameter carrying a chart at its own level or at any element
level of its `ListDomain` chain, since a scalar lift's chart lives in
`ListDomain.element_chart` and not `ParamDef.chart`. A `.repeat()` count is
excluded and reported in `excluded_by_prop`, because transport rewrites
conditions and constraints but never a count.

`rep.target` is an ordinary `Space` of `real(0, 1)` coordinates and samples
like any other. Decoding is guaranteed **total**: every genotype the target
calls valid decodes to a phenotype the source calls valid. The reverse
round-trip is not a law, because an integer chart is many-to-one.

```{literalinclude} ../../examples/09_representation.py
:pyobject: show_induced_representation
```

## The conformance laws as a tool

`rep.check(n, seed)` covers decode totality, feasibility agreement, and, where
invertible, the one-directional round-trip. It returns a report and never
raises.

```{literalinclude} ../../examples/09_representation.py
:pyobject: show_check
```

## Mixed genotypes

Representing with an explicit rule means the rule chooses what changes.
Anything it does not match passes through in its original phenotype units.

The encoding below is most of what the induced representation does per
parameter, spelled out by hand. `param` is the *source*'s own `ParamDef`, so
its already-built `.chart` does the real work.

```{literalinclude} ../../examples/09_representation.py
:pyobject: UnitEncoding
```

```{literalinclude} ../../examples/09_representation.py
:pyobject: show_mixed_genotype
```

## A supplied morphism

Constructing `Representation(source=, target=, decode=, encode=)` directly is
the escape hatch for a bridge the derived tier cannot express. Flattening a
hierarchy erases a struct param's namespace entirely, which the derived tier
could never do, since it must preserve the source's key set exactly.

```{literalinclude} ../../examples/09_representation.py
:pyobject: show_supplied_morphism
```
