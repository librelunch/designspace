"""`compiler_pipeline` corpus fixture.

Exercises registry-driven generation, `ds.all_()` and degenerate arities.

A catalogue of optimization passes, each with declared prerequisites, is
turned into `.bool()` params and `require(pass.implies(all_(*prereqs)))`
constraints by looping over the registry rather than by hand-typing each
one.

`ds.all_()` appears both as a genuine multi-operand fold, over
`register_allocation`'s two prerequisites, and at its zero-operand identity:
a prerequisite-free pass's `all_(*())` folds to the literal `True`, so its
`.implies()` is trivially satisfied. The Degeneracy Table gives that as
"`ds.all_()` | Literal `True`".

`test_compiler_pipeline.py` exercises `.map_params()` over these
registry-generated params, as a coarsening rewrite.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

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
