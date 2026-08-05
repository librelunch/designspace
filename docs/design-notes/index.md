# Design notes

Five pages on decisions a space declaration forces, and what each option costs.
The [tutorials](../tutorials/index.md) show the mechanisms running; these pages
are about choosing between them.

They can be read in any order. The first two have the largest effect on the
resulting space.

::::{grid} 1 2 2 2
:gutter: 2

:::{grid-item-card} Choosing a mechanism
:link: choosing-a-mechanism
:link-type: doc

Which of `bool` + `.when()`, `.choice()`, `.space()` and a bool-per-item subset
describes the situation, and why the choice is permanent.
:::

:::{grid-item-card} Structured values
:link: structured-values
:link-type: doc

Declaring a value whose content is a structure, where the invariant lives, and
what moving it inside a custom type costs.
:::

:::{grid-item-card} Predicate transparency
:link: predicate-transparency
:link-type: doc

What margins, `remaining_domain` narrowing and bound-origin tightening cost as
a predicate becomes opaque.
:::

:::{grid-item-card} Rejection sampling
:link: rejection
:link-type: doc

Why dense combinatorial constraints collapse the acceptance rate, the two
remedies that apply, and the one that does not.
:::

:::{grid-item-card} Anchors
:link: anchors
:link-type: doc

Named whole configurations against per-parameter defaults, and why deriving one
from the other beats restating it.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

choosing-a-mechanism
structured-values
predicate-transparency
rejection
anchors
```

## Terminology

The word *tier* names three unrelated scales across the documentation:

| "tier" | where | what it ranks |
|---|---|---|
| white / grey / black | [predicate transparency](predicate-transparency.md) | how much of a *predicate* the library can see into |
| 1 / 2 / 3 | [structured values](structured-values.md) | how much of a *structure* is handed to a custom type |
| derived / supplied | [identity and solver hand-off](../tutorials/11-identity-and-solvers.md) | where a `Representation` came from |

The three scales are independent. A tier-3 structured value can carry a
white-box predicate, and a tier-1 family can carry a black-box one.
