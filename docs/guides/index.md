# Guides

Each guide takes one decision you will actually face and works through how the
library expects you to make it. They are meant to be read in any order, but the
first two are the ones that shape a space most.

```{toctree}
:maxdepth: 1

choosing-a-mechanism
structured-values
predicate-transparency
rejection
defaults-and-anchors
sampling-diagnostics
solver-integration
```

## A note on the word "tier"

It means three unrelated things across these pages, and they are easy to
confuse:

| "tier" | where | what it ranks |
|---|---|---|
| white / grey / black | [predicate transparency](predicate-transparency.md) | how much of a *predicate* the library can see into |
| 1 / 2 / 3 | [structured values](structured-values.md) | how much of a *structure* you hand to a custom type |
| derived / supplied | [solver integration](solver-integration.md) | where a `Representation` came from |

Nothing connects them. A tier-3 structured value can carry a white-box
predicate; a tier-1 family can carry a black-box one.
