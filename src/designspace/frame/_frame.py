"""`Space.sample()`'s implementation (API.md, "Sampling and Generativity",
`.sample(n, seed=None, reject_soft=False) -> pl.DataFrame`).

This is the only module in `frame/` that touches polars at runtime. `polars`
is an optional extra, `designspace[polars]` rather than core, so the import
is lazy and guarded here alone. `sample_dicts()` and `sample_one()`, in
`designspace.sample`, need no polars.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from designspace.builder._space import Seed, Space
from designspace.frame._rows import build_row
from designspace.frame._schema import build_schema
from designspace.sample import sample_flat

if TYPE_CHECKING:
    import polars as pl


def sample_frame(
    space: Space, n: int, seed: Seed = None, reject_soft: bool = False
) -> pl.DataFrame:
    try:
        import polars as pl
    except ImportError as exc:
        raise ImportError(
            "space.sample() requires polars; install with `pip install designspace[polars]` "
            "(sample_dicts()/sample_one() work without it)"
        ) from exc
    schema = build_schema(space, pl)
    draws: list[tuple[dict[str, Any], dict[str, bool]]] = sample_flat(
        space, n, seed=seed, reject_soft=reject_soft
    )
    rows = [build_row(space, config, activity) for config, activity in draws]
    return pl.DataFrame(rows, schema=schema, orient="row")
