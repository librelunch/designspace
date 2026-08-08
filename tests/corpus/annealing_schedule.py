"""`annealing_schedule` corpus fixture.

Exercises `.symbolic()` and `.code()` definitions, which core validates
without generating: tree and program generation are out of scope.

A simulated-annealing configurator with the usual scalar knobs, an optional
custom cooling curve, and an acceptance predicate. The cooling curve is a
`.symbolic()` expression tree, active only when `use_custom_schedule` is
set, under Kleene rule 3. The acceptance predicate is freeform source, a
`.code()` param, always active. Both program params are non-generative and
carry a `.default()`, so they resolve, sample and round-trip cleanly with no
sampler.
"""

from __future__ import annotations

import designspace as ds
from designspace import Space

SCHEDULE_SIGNATURE = ds.Signature({"step": int, "total": int}, float)

# Bare strings, `cos`, `exp`, `pi` and `/`, whose arity is unchecked, mixed
# with pinned `Primitive` objects. Each carries `fn=None`, so the fixture
# stays fully serializable, `Primitive.fn` belonging to the closed
# non-serializable set.
SCHEDULE_PRIMITIVES: list[str | ds.Primitive | ds.FloatLiteral] = [
    "cos",
    "exp",
    "pi",
    "/",
    ds.Primitive("*", 2),
    ds.Primitive("+", (2, None)),
    ds.FloatLiteral(0.0, 1.0),
]
SCHEDULE_MAX_DEPTH = 4

# cos(pi * (step / total)) -- a cosine cooling curve.
DEFAULT_SCHEDULE_AST = {
    "op": "cos",
    "args": [
        {
            "op": "*",
            "args": [
                {"op": "pi", "args": []},
                {"op": "/", "args": [{"var": "step"}, {"var": "total"}]},
            ],
        }
    ],
}
DEFAULT_SCHEDULE = {"ast": DEFAULT_SCHEDULE_AST, "source": "cos(pi * (step / total))"}

ACCEPTANCE_SIGNATURE = ds.Signature({"delta": float, "temperature": float}, bool)
DEFAULT_ACCEPTANCE = {"source": "delta < 0 or random() < exp(-delta / temperature)"}


def build_space() -> Space:
    return (
        ds.space(
            ds.param("initial_temp").real(1.0, 1000.0).log_scale(),
            ds.param("min_temp").real(0.001, 1.0),
            ds.param("total_steps").integer(10, 1000),
            ds.param("use_custom_schedule").bool(),
            ds.param("schedule")
            .symbolic(SCHEDULE_SIGNATURE, SCHEDULE_PRIMITIVES, SCHEDULE_MAX_DEPTH)
            .default(DEFAULT_SCHEDULE)
            .when(ds.param("use_custom_schedule") == True),  # noqa: E712
            ds.param("acceptance_predicate")
            .code(
                ACCEPTANCE_SIGNATURE,
                description="Metropolis acceptance criterion",
                constraints=["must be a pure function of delta and temperature"],
                examples=[{"delta": -1.0, "temperature": 0.5, "accept": True}],
            )
            .default(DEFAULT_ACCEPTANCE),
        )
        .require(ds.param("min_temp") < ds.param("initial_temp"))
        .encourage(ds.param("total_steps") >= 100, tags=("convergence",))
    )
