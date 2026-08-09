---
file_format: mystnb
---

# Constraints and feasibility

Four verbs attach rules to a space. Two are hard and define feasibility; two are
declared, reported and never enforced. This page uses a continuous-flow
chemistry rig, whose reagent set, step order and process conditions give each
verb something real to say.

## The four verbs

`.forbid(e)` and `.discourage(e)` name an **undesirable** state. `.require(e)`
and `.encourage(e)` name a **desired** one. Within each pair the polarity is the
same and only the hardness differs.

```{code-cell}
import designspace as ds

REAGENTS = ("acid", "base", "catalyst", "solvent")
COST = {"acid": 3.0, "base": 1.5, "catalyst": 12.0, "solvent": 0.5}

space = (
    ds.space(
        ds.param("reagents").subset(REAGENTS, min_size=1),
        ds.param("order").permutation(("charge", "heat", "quench", "wash")),
        ds.param("temp_c").real(20.0, 200.0),
        ds.param("mode").categorical("batch", "flow", "semi-batch"),
    )
    .require(
        ds.param("order").position_of("charge") < ds.param("order").position_of("heat"),
    )
    .forbid(
        ds.param("reagents").contains("catalyst") & (ds.param("temp_c") > 150.0),
    )
    .require(ds.param("reagents").sum_over(COST) <= 15.0)
    .encourage(ds.param("reagents").size() <= 3, tags=("lean-process",))
    .discourage(ds.param("temp_c") > 180.0, tags=("thermal-load",))
)
print(space)
```

The expression vocabulary here is worth naming. `.contains(item)`, `.size()` and
`.sum_over(mapping)` query a subset; `.position_of(item)` queries a permutation,
so an ordering rule compares two positions directly.

## Hard constraints shape what is drawn

The sampler rejects any draw that trips a hard constraint, so a sampled
configuration satisfies them by construction.

```{code-cell}
config = space.sample_one(seed=0)
print(ds.pretty(config, space))
```

```{code-cell}
:tags: [remove-output]

for c in space.sample_dicts(100, seed=1):
    charge = c["order"].index("charge")
    heat = c["order"].index("heat")
    assert charge < heat
    assert sum(COST[r] for r in c["reagents"]) <= 15.0
```

Declared constraints do not shape the draw at all. They are reported and
nothing more.

## Reading a constraint report

`evaluate_constraints` returns one `ConstraintEval` per constraint.

```{code-cell}
for ce in space.evaluate_constraints(config):
    tags = ", ".join(sorted(ce.constraint.tags)) or "-"
    print(f"{ce.constraint.kind:11} [{tags:14}] "
          f"applicable={ce.applicable!s:5} satisfied={ce.satisfied!s:5} "
          f"margin={ce.margin}")
```

Two fields need care. `satisfied` is the raw truth of the predicate, so it means
opposite things for opposite verbs: a `forbid` whose predicate is satisfied is
the *bad* case. `violated` folds the polarity in and always means unhealthy:

```{code-cell}
[(ce.constraint.kind, ce.satisfied, ce.violated)
 for ce in space.evaluate_constraints(config)]
```

Building a display on `kind` and `violated` keeps it correct whichever verb
produced the row. Swapping a `forbid` for a `require` and flipping the condition
leaves such a display unchanged.

## Margins

A margin says *how far* from the boundary a configuration sits, not merely
whether it is legal. That is the signal a solver follows downhill.

```{code-cell}
[(ce.constraint.kind, round(ce.margin, 3))
 for ce in space.evaluate_constraints(config)
 if ce.margin is not None]
```

The cost rule's margin is the unspent budget in the units of the rule itself,
so it shrinks as a configuration approaches the cap.

A predicate with no numeric boundary has nothing to measure against, and its
margin is `None`. The catalyst forbid is a conjunction of a membership test and
a comparison, which is boolean throughout:

```{code-cell}
catalyst_rule = space.evaluate_constraints(config)[1]
catalyst_rule.constraint.kind, catalyst_rule.satisfied, catalyst_rule.margin
```

## Infeasibility

```{code-cell}
hot = dict(config, reagents=["catalyst", "solvent"], temp_c=175.0)
space.is_feasible(hot)
```

```{code-cell}
space.infeasibility_reasons(hot)
```

Note that `validate` still passes: every value is inside its declared domain,
and it is the combination that is forbidden.

```{code-cell}
space.validate(hot).valid
```

## Combining conditions

`ds.all_` and `ds.any_` fold a variadic AND and OR. `ds.count(*conditions)`
reports how many hold, as an arithmetic value, which is what lets a cardinality
rule range over parameters that are separate by construction.

```{code-cell}
space = ds.space(
    ds.param("use_l1").bool(),
    ds.param("use_l2").bool(),
    ds.param("l1_weight").real(1e-5, 1e-1).when(ds.param("use_l1")),
    ds.param("l2_weight").real(1e-5, 1e-1).when(ds.param("use_l2")),
).require(ds.count(ds.param("use_l1"), ds.param("use_l2")) >= 1)
[(c["use_l1"], c["use_l2"]) for c in space.sample_dicts(6, seed=0)]
```

```{code-cell}
:tags: [remove-output]

assert all(c["use_l1"] or c["use_l2"] for c in space.sample_dicts(200, seed=1))
```

## Where to go next

[Lifts and aggregates](05-lifts-and-aggregates.md) applies constraints across a
list of elements.
