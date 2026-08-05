# Guides

Each guide covers one decision a space declaration involves. They can be read
in any order; the first two have the largest effect on the resulting space.

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} Choosing a mechanism
:link: choosing-a-mechanism
:link-type: doc

Which of `bool` + `.when()`, `.choice()`, `.space()` and a bool-per-item
subset describes the situation.
:::

:::{grid-item-card} Structured values
:link: structured-values
:link-type: doc

Declaring a value whose content is a structure, and where the invariant
lives across the three tiers.
:::

:::{grid-item-card} Predicate transparency
:link: predicate-transparency
:link-type: doc

What margins, `remaining_domain` narrowing and bound-origin tightening cost
as a predicate becomes opaque.
:::

:::{grid-item-card} Rejection sampling
:link: rejection
:link-type: doc

Why dense combinatorial constraints collapse the acceptance rate, and the
two remedies that apply.
:::

:::{grid-item-card} Defaults and anchors
:link: defaults-and-anchors
:link-type: doc

Per-parameter fill values against named whole configurations, and why
`apply_defaults` is constraint-blind.
:::

:::{grid-item-card} Sampling diagnostics
:link: sampling-diagnostics
:link-type: doc

Reading `sampling_report()`, the pathologies `sample()` hides, and why bound
tightening is opt-in.
:::

:::{grid-item-card} Integrating a solver
:link: solver-integration
:link-type: doc

The three shapes a solver hand-off takes, charts as the perturbation
surface, and observation identity.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

choosing-a-mechanism
structured-values
predicate-transparency
rejection
defaults-and-anchors
sampling-diagnostics
solver-integration
```

## Terminology

The word *tier* names three unrelated scales across these pages:

| "tier" | where | what it ranks |
|---|---|---|
| white / grey / black | [predicate transparency](predicate-transparency.md) | how much of a *predicate* the library can see into |
| 1 / 2 / 3 | [structured values](structured-values.md) | how much of a *structure* is handed to a custom type |
| derived / supplied | [solver integration](solver-integration.md) | where a `Representation` came from |

The three scales are independent. A tier-3 structured value can carry a
white-box predicate, and a tier-1 family can carry a black-box one.
