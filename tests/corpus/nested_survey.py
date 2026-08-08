"""`nested_survey` corpus fixture.

Exercises a param-driven `.repeat()` count inside a relocated scope. Every
other fixture's param-driven count sits at root scope, which is why a count
expression keeping its pre-relocation path, so that the list silently
materializes `[]` whatever the count param's value, is invisible to them.

The shape is a survey instrument. Each section is a struct with its own item
count and its own per-item constraints, and one section is gated behind a
choice variant. The count reference therefore relocates through a struct
body, through a choice variant payload, and, through the enclosing-scope
reference `n_repeats`, across scopes.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

MAX_ITEMS = 6
MAX_TOTAL_MINUTES = 45


def build_space() -> Space:
    item = ds.space(
        ds.param("difficulty").integer(1, 5),
        ds.param("minutes").integer(1, 8),
    ).forbid(
        # A hard per-item rule: the easiest items may not be the longest.
        (ds.param("difficulty") == 1) & (ds.param("minutes") > 4),
    )

    core = ds.space(
        # The count and the lift it sizes are siblings inside a struct,
        # which is the relocation route this fixture covers.
        ds.param("n_items").integer(1, MAX_ITEMS),
        ds.param("items").space(item).repeat(ds.param("n_items")),
    )

    followup = ds.space(
        ds.param("n_probes").integer(1, 3),
        ds.param("probes").real(0.0, 1.0).repeat(ds.param("n_probes")),
        # An enclosing-scope up-reference from inside a choice variant
        # It is deferred to finalization, exactly as a condition is.
        ds.param("reps").integer(1, 3).repeat(ds.param("n_repeats")),
    )

    return ds.space(
        ds.param("n_repeats").integer(1, 2),
        ds.param("core").space(core),
        ds.param("mode").choice("screening", deep=followup),
    ).encourage(
        ds.param("core.items").field("minutes").sum() <= MAX_TOTAL_MINUTES,
        tags=("budget",),
    )
