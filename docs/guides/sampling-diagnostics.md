# Sampling diagnostics

`space.sampling_report()` draws configurations from the **unconditioned**
measure, before any rejection, and aggregates what happened. It reports only,
and never repairs, reweights, or suggests a fix.

Drawing unconditioned is the design decision that makes the report useful, and
it is the part to understand before reading one.

## The unconditioned measure

`sample()` returns the post-rejection distribution. Two pathologies are
invisible in it, because rejection has already hidden them.

### Unknown-swallowing

A constraint that cannot be evaluated is *inapplicable*, and inapplicable means
**accepted**. That is the permissive direction, and it is silent.

Consider a budget over a parameter that is not always active:

```pycon
>>> import designspace as ds
>>> space = ds.space(
...     ds.param("use_c").bool(),
...     ds.param("a").integer(0, 5),
...     ds.param("c").integer(0, 5).when(ds.param("use_c")),
... ).require(ds.param("a") + ds.param("c") <= 6)
>>> report = space.sampling_report(n=200, seed=0)
>>> round(report.acceptance_rate, 2)
0.82

```

An 82% acceptance rate looks healthy. The budget, however, is *enforced* only on
the draws where `c` exists at all:

```pycon
>>> budget = report.constraints[0]
>>> round(budget.applicable, 2)
0.45

```

Less than half. Wherever `use_c` is false the constraint stops enforcing, and
nothing in `sample()`'s output reports that. `applicable` is the only signal.

The usual fix is `.if_inactive()`, which states explicitly what an absent `c`
should contribute. Nothing else prompts an author to reach for it, which is why
this surface exists.

### Funnels

A constraint that is inapplicable on part of the space biases the conditioned
measure *toward* that part, since rejection accepts those draws
unconditionally.

This is what `require` is defined to do: it conditions the declared measure. The
effect is not visible from the resulting sample.

## Interpreting `satisfied`

`satisfied` is conditioned on **applicability**, not on all draws:

```pycon
>>> round(budget.satisfied, 2)
0.6

```

A constraint applicable in 1% of draws and always satisfied there reports `1.0`,
not `0.01`. Collapsing the two would erase the distinction this surface exists
to draw, so the pair is read together: `applicable` says how often the question
was asked, and `satisfied` how often the answer was yes.

Where `applicable` is `0.0`, meaning the constraint was never Kleene-defined
across any draw, `satisfied` reports `0.0` by convention rather than `NaN`, so a
frozen report always equals itself. It carries no information in that case, and
`applicable` is the number to read.

## Bound tightening

The reference sampler has a best-effort optimization: fold an already-assigned
bound-origin coupling into the draw instead of drawing and rejecting. For
`sample()` this is unobservable, since truncation and conditioning agree.

For a *report* it is observable, which is why it defaults to off:

```pycon
>>> honest = space.sampling_report(n=200, seed=0)
>>> tightened = space.sampling_report(n=200, seed=0, tighten_bounds=True)

```

Drawn unconditioned, tightening would launder the report's own subject. On a
bound-coupled space it collapses the rows most likely to carry a pathology to
`satisfied ≈ 1.0`.

The two settings therefore answer different questions:

- `tighten_bounds=False`, the default, answers "how much of the declared measure
  do the hard constraints cut away?" Bound-origin rows show their real
  satisfaction fractions.
- `tighten_bounds=True` answers "how much does tightening save?"

The three sampling entry points, `sample`, `sample_one` and `sample_dicts`, take
no such flag. Tightening cannot change the distribution they return, so a flag
there would be a performance control wearing a semantic one's signature.
