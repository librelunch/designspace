# Rejection sampling

The reference sampler draws from the declared measure and rejects whatever
violates a hard constraint. For most spaces this is both correct and fast. Its
failure mode is abrupt, and its cause is specific: **dense combinatorial
constraints collapse the acceptance rate**. Pairwise distinctness, conflict sets
near a packing limit, and anything else where the legal region is a vanishing
fraction of the declared one.

## Acceptance rate under dense constraints

Six slots drawn independently, required to be pairwise distinct:

```pycon
>>> import itertools
>>> import designspace as ds
>>> names = [f"slot{i}" for i in range(6)]
>>> space = ds.space(*[ds.param(n).integer(0, 5) for n in names])
>>> for a, b in itertools.combinations(names, 2):
...     space = space.forbid(ds.param(a) == ds.param(b))
>>> round(space.sampling_report(n=300, seed=0).acceptance_rate, 3)
0.013

```

Around one draw in seventy-five survives. Nothing is malfunctioning: 6! legal
assignments out of 6⁶ is 1.5%, and rejection is finding exactly that.

Two more slots make it substantially worse:

```pycon
>>> names = [f"s{i}" for i in range(8)]
>>> space = ds.space(*[ds.param(n).integer(0, 7) for n in names])
>>> for a, b in itertools.combinations(names, 2):
...     space = space.forbid(ds.param(a) == ds.param(b))
>>> round(space.sampling_report(n=300, seed=0).acceptance_rate, 4)
0.0033

```

Beyond the retry limit, sampling raises `SamplingError` rather than hanging. The
default limit is 10,000 draws, and the error names the constraints that
dominated the rejections:

```text
SamplingError: sample_one: no feasible draw found after 10000 retries;
dominant constraint(s): ["'eq' (887/10000 draws)", "'eq' (885/10000 draws)", ...]
```

That list is the diagnostic, and the constraints dominating rejection are the
ones to restructure.

## Remedies

There is no tuning parameter for this. Raising the retry limit buys a linear
factor against a combinatorial problem. Two remedies apply.

### Reparameterize

The first question is whether the constraint is a constraint at all, or a
structure spelled as one. "All distinct" over *n* slots with *n* values is a
permutation:

```pycon
>>> space = ds.space(ds.param("order").permutation(list(range(8))))
>>> space.sample_one(seed=0)
{'order': [2, 4, 3, 6, 5, 0, 1, 7]}

```

Every draw is valid by construction. Acceptance is 100%, the parameter keeps a
proper chart and prior, and the fifteen forbids are gone.

This case is the one to look for first, and it is more common than it appears.
Simplexes, orderings, partitions and assignments all have primitive spellings
that make the measure-zero constraint disappear.

### Enforce inside a custom sampler

Where the invariant is global and has no primitive spelling, covering
connectivity, minimum pairwise spacing, or a packing that must fit, construction
moves inside a `.custom()` type whose sampler cannot produce an invalid value.
That is tier 3 in [structured values](structured-values.md), and hostility to
rejection is the main reason to reach for it.

## Softening hard constraints

Softening a hard constraint to `.encourage()` is not a remedy for slow sampling.
`.encourage()` does not affect feasibility, so the space starts producing
configurations that violate the rule the author meant, quickly and without
complaint. Softening changes what the space *means*, and it is not a performance
adjustment.
