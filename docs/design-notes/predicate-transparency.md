# Predicate transparency

The way a predicate is *written* decides how much of the library's machinery can
act on it. All three forms below are one line and all three are enforced
correctly, so the cost is invisible at the call site.

| transparency | form | margins | `remaining_domain` narrowing | tighten-not-reject |
|---|---|---|---|---|
| white box | an expression over parameter values | yes | yes | yes (bound-origin) |
| grey box | opaque scalar under a structural comparison | yes | no | no |
| black box | an opaque predicate | no | no | no |

## White box

The predicate is an expression the library can read, and every facility applies.

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("a").integer(0, 10),
...     ds.param("b").integer(0, 10),
... ).require(ds.param("b") <= ds.param("a"))
>>> [e.margin for e in space.evaluate_constraints({"a": 7, "b": 2})]
[5.0]

```

A margin reports *how far* from the boundary a configuration sits, rather than
only whether it is legal, which is the signal a solver follows downhill.
Because the structure is visible, the space can also report what remains
available for one parameter given the others:

```pycon
>>> space.remaining_domain("b", {"a": 4})
IntegerRemaining(lo=0, hi=4, grid=None)

```

## Grey box

The value is opaque but arrives as a **number**, and the comparison against it
is structural. The comparison stays visible even though the computation does
not.

```pycon
>>> cost = ds.value(lambda x: x * 2.0, ds.param("x"), returns=float)
>>> space = ds.space(ds.param("x").integer(0, 10)).require(cost <= 8.0)
>>> [e.margin for e in space.evaluate_constraints({"x": 3})]
[2.0]

```

The margin survives because subtracting `6.0` from `8.0` requires no
understanding of `lambda x: x * 2.0`. Narrowing a domain does require it, since
that would mean inverting the opaque part:

```pycon
>>> space.remaining_domain("x", {})
IntegerRemaining(lo=0, hi=10, grid=None)

```

## Black box

The predicate itself is opaque. The library can only call it and take the
answer.

```pycon
>>> is_even = ds.value(lambda x: x % 2 == 0, ds.param("x"), returns=bool)
>>> space = ds.space(ds.param("x").integer(0, 10)).require(is_even)
>>> [e.margin for e in space.evaluate_constraints({"x": 3})]
[None]

```

`margin` is `None` because there is no boundary to measure a distance to. The
constraint is still enforced; it behaves as a wall rather than a slope.

## Tightening instead of rejecting

A grey predicate is usually within reach where a black one gets written out of
habit, because anything physical has a numeric value:

```pycon
>>> black = ds.value(lambda w: w <= 5.0, ds.param("weight_g"), returns=bool)
>>> grey = ds.value(lambda w: w, ds.param("weight_g"), returns=float) <= 5.0

```

The two accept identical configurations. The second keeps the margin the first
discards, at the cost of one line of rewriting, done once, at declaration time.
