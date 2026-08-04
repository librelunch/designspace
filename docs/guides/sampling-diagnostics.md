# Sampling diagnostics

`space.sampling_report()` draws configurations from the **unconditioned**
measure — before any rejection — and aggregates what happened. It reports. It
never repairs, reweights, or suggests a fix.

Drawing unconditioned is the entire point, and it is the part worth
understanding before reading a report.

## Why unconditioned

`sample()` gives you the post-rejection distribution. Two pathologies are
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

An 82% acceptance rate looks healthy. But the budget is only *enforced* on the
draws where `c` exists at all:

```pycon
>>> budget = report.constraints[0]
>>> round(budget.applicable, 2)
0.45

```

Less than half. Wherever `use_c` is false the constraint quietly stops
enforcing, and nothing in `sample()`'s output would ever tell you. `applicable`
is the only signal.

The fix is usually `.if_inactive()` — deciding explicitly what an absent `c`
should contribute — but nothing prompts you to reach for it, which is why this
surface exists.

### Funnels

A constraint that is inapplicable on part of the space biases the conditioned
measure *toward* that part, since rejection accepts those draws unconditionally.

This is not a bug — `require` conditions the declared measure, and that is what
it is for. It is simply not visible from the resulting sample.

## Reading `satisfied` correctly

`satisfied` is conditioned on **applicability**, not on all draws:

```pycon
>>> round(budget.satisfied, 2)
0.6

```

A constraint applicable in 1% of draws and always satisfied there reports
`1.0` — not `0.01`. Collapsing the two would erase exactly the distinction this
surface exists to draw, so read the pair together: `applicable` says how often
the question was asked, `satisfied` how often the answer was yes.

When `applicable` is `0.0` — never Kleene-defined across any draw — `satisfied`
reports `0.0` by convention rather than `NaN`, so a frozen report always equals
itself. It carries no information in that case; `applicable` is the number to
read.

## Tightening is opt-in

The reference sampler has a best-effort optimization: fold an already-assigned
bound-origin coupling into the draw instead of drawing and rejecting. For
`sample()` this is unobservable — truncation and conditioning agree.

For a *report* it is not unobservable at all, which is why it defaults to off:

```pycon
>>> honest = space.sampling_report(n=200, seed=0)
>>> tightened = space.sampling_report(n=200, seed=0, tighten_bounds=True)

```

Drawn unconditioned, tightening would launder the report's own subject — on a
bound-coupled space it collapses precisely the rows most likely to carry a
pathology to `satisfied ≈ 1.0`.

So the two flags answer different questions:

- `tighten_bounds=False` (the default) — "how much of the declared measure do my
  hard constraints cut away?" Bound-origin rows show their real satisfaction
  fractions.
- `tighten_bounds=True` — "how much does tightening save me?"

The three sampling entry points (`sample`, `sample_one`, `sample_dicts`) take no
such flag, deliberately: tightening cannot change the distribution they return,
so a flag there would be a performance knob wearing a semantic one's signature.
