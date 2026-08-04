# When rejection stops working

The reference sampler draws from the declared measure and rejects whatever
violates a hard constraint. That is correct, and for most spaces it is also
fast. Then it isn't — and the failure is abrupt rather than gradual.

**Dense combinatorial constraints collapse the acceptance rate.** Pairwise
distinctness, conflict sets near a packing limit, anything where the legal
region is a vanishing fraction of the declared one.

## Watching it collapse

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

Around one draw in seventy-five survives. Nothing is wrong: 6! legal
assignments out of 6⁶ is 1.5%, and rejection is finding exactly that.

Add two more slots and it gets worse fast:

```pycon
>>> names = [f"s{i}" for i in range(8)]
>>> space = ds.space(*[ds.param(n).integer(0, 7) for n in names])
>>> for a, b in itertools.combinations(names, 2):
...     space = space.forbid(ds.param(a) == ds.param(b))
>>> round(space.sampling_report(n=300, seed=0).acceptance_rate, 4)
0.0033

```

Push it far enough and sampling gives up rather than hanging. The default is
10,000 retries, and the error names the constraints that dominated the
rejections:

```text
SamplingError: sample_one: no feasible draw found after 10000 retries;
dominant constraint(s): ["'eq' (887/10000 draws)", "'eq' (885/10000 draws)", ...]
```

That list is the diagnostic. Constraints that dominate rejection are the ones to
restructure.

## The remedy is constructive, not numerical

There is no tuning knob here. Raising the retry limit buys a linear factor
against a combinatorial problem, which is not a trade worth making. Two real
options:

### Reparameterize

Ask whether the constraint is really a constraint, or a structure you spelled as
one. "All distinct" over *n* slots with *n* values is not a constraint at all —
it is a permutation:

```pycon
>>> space = ds.space(ds.param("order").permutation(list(range(8))))
>>> space.sample_one(seed=0)
{'order': [2, 4, 3, 6, 5, 0, 1, 7]}

```

Every draw is valid by construction. Acceptance is 100%, the parameter keeps a
proper chart and prior, and the fifteen forbids are gone.

This is the case worth looking for first, and it is more common than it seems —
simplexes, orderings, partitions and assignments all have primitive spellings
that make the measure-zero constraint disappear.

### Enforce inside a custom sampler

When the invariant is genuinely global and has no primitive spelling —
connectivity, minimum pairwise spacing, a packing that must fit — move
construction inside a `.custom()` type whose sampler cannot produce an invalid
value. That is tier 3 in [structured values](structured-values.md), and
rejection hostility is the main reason to reach for it.

## The thing not to do

Do not soften a hard constraint to `.encourage()` to make sampling succeed.
`.encourage()` does not affect feasibility, so the space will start producing
configurations that violate the rule you actually meant — quickly, and without
complaint. Softening changes what the space *means*; it is not a performance
fix.
