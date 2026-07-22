"""`compiler_pipeline` corpus fixture (PLAN.md M8 corpus table).

Exercises: **registry-driven generation** — a catalog of optimization
passes, each with declared prerequisite passes, turned into `.bool()`
params and `require(pass.implies(all_(*prereqs)))` constraints by looping
over the registry rather than hand-typing each one; **`ds.all_()`** — both
as a genuine multi-operand fold (`register_allocation`'s two prerequisites)
and its zero-operand identity (a prerequisite-free pass's `all_(*())`
folds to the literal `True`, so its `.implies()` is trivially satisfied —
**degenerate arities**, Degeneracy Table: "`ds.all_()` | Literal `True`").
`.map_params()` (M8) is exercised in `test_compiler_pipeline.py`, not here
— a coarsening rewrite over these registry-generated params.
"""

from __future__ import annotations

import designspace as ds
from designspace.build._space import Space

# pass name -> prerequisite pass names (all must be enabled if this pass is).
PASS_REGISTRY: dict[str, tuple[str, ...]] = {
    "constant_folding": (),
    "inlining": (),
    "dead_code_elimination": ("constant_folding",),
    "loop_invariant_motion": ("constant_folding",),
    "vectorization": ("loop_invariant_motion",),
    "register_allocation": ("dead_code_elimination", "inlining"),
}


def build_space() -> Space:
    flags = {name: ds.param(f"enable_{name}").bool() for name in PASS_REGISTRY}
    space = ds.space(*flags.values())
    for name, prereqs in PASS_REGISTRY.items():
        prereq_exprs = tuple(flags[p] for p in prereqs)
        space = space.require(flags[name].implies(ds.all_(*prereq_exprs)))
    return space
