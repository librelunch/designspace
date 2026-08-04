# Predicate transparency

How you *write* a predicate decides how much of the library's machinery can act
on it. All three forms below are one line, and all three are enforced
correctly, so the cost is invisible at the call site. That is why it is worth
naming.

| tier | form | margins | `remaining_domain` narrowing | tighten-not-reject |
|---|---|---|---|---|
| white | an expression over parameter values | yes | yes | yes (bound-origin) |
| grey | opaque scalar under a structural comparison | yes | no | no |
| black | an opaque predicate | no | no | no |

```{note}
Unrelated to the tier 1/2/3 of [structured values](structured-values.md). This
ranks predicates; that ranks structures.
```

## White box

The predicate is an expression the library can read. Everything works.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("a").integer(0, 10),
...     ds.param("b").integer(0, 10),
... ).require(ds.param("b") <= ds.param("a"))
>>> [e.margin for e in space.evaluate_constraints({"a": 7, "b": 2})]
[5.0]

```

A margin says *how far* from the boundary a configuration sits, not merely
whether it is legal. That is what a solver follows downhill. And because the
structure is visible, the space can answer what is still available for one
parameter given the others:

```pycon
>>> space.remaining_domain("b", {"a": 4})
IntegerRemaining(lo=0, hi=4, grid=None)

```

## Grey box

The value is opaque, but it comes out as a **number** and you compare it
structurally. The comparison stays visible even though the computation does not.

```pycon
>>> cost = ds.value(lambda x: x * 2.0, ds.param("x"), returns=float)
>>> space = ds.space(ds.param("x").integer(0, 10)).require(cost <= 8.0)
>>> [e.margin for e in space.evaluate_constraints({"x": 3})]
[2.0]

```

The margin survives, because the library did not need to understand
`lambda x: x * 2.0` to subtract `6.0` from `8.0`. What it cannot do is narrow a
domain, since that would mean inverting the opaque part:

```pycon
>>> space.remaining_domain("x", {})
IntegerRemaining(lo=0, hi=10, grid=None)

```

## Black box

The predicate itself is opaque. The library can only call it and believe the
answer.

```pycon
>>> is_even = ds.value(lambda x: x % 2 == 0, ds.param("x"), returns=bool)
>>> space = ds.space(ds.param("x").integer(0, 10)).require(is_even)
>>> [e.margin for e in space.evaluate_constraints({"x": 3})]
[None]

```

`margin` is `None`, because there is no boundary to measure a distance to. The
constraint still works. It is a wall rather than a slope.

## Why prefer transparency

Not for solver consumption. A solver facing a black-box objective is not handing
your constraints to a MIP or CP solver anyway.

The argument is that margins, `evaluate_partial`, `remaining_domain`, and
bound-origin tightening are all **designspace's own machinery**, and all of them
run on structure. Write a black-box predicate and you switch them off for that
constraint, inside a library you are otherwise paying for.

## The move that is almost always available

A grey predicate is usually within reach where a black one gets written out of
habit. Anything physical has a numeric value:

```pycon
>>> black = ds.value(lambda w: w <= 5.0, ds.param("weight_g"), returns=bool)
>>> grey = ds.value(lambda w: w, ds.param("weight_g"), returns=float) <= 5.0

```

The two accept identical configurations. The second keeps the margin that the
first throws away, and it costs one line of rewriting, done once, at
declaration time.
