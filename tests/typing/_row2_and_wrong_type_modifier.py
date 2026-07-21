"""Static-typing fixture for the M4.6 gate (API.md, "Builder view types").

Not collected by pytest as a test module — it is fed to `mypy --strict` by
test_static_typing.py. Each `# type: ignore[attr-defined]` below is only
valid if the named method is genuinely absent from that view's static type;
`mypy --strict` bundles `--warn-unused-ignores`, so an unused (i.e. no
longer load-bearing) ignore comment fails the check on its own.
"""

import designspace as ds

# Row 2: a second type method is a static error once the first type method
# has narrowed the builder to RealParamExpr, which has no `.bool()`.
ds.param("x").real(0.0, 1.0).bool()  # type: ignore[attr-defined]

# Row 11: `.log_scale()` is Real/Integer-only; CategoricalParamExpr has no
# `.log_scale()` attribute at all.
ds.param("y").categorical("a", "b").log_scale()  # type: ignore[attr-defined]

# Positive control: a legitimate chain interleaving a universal modifier
# (`.tag()`) between numeric-only ones must still type-check as
# RealParamExpr — the whole point of `_as()`/`Self` is that this stays
# valid and narrowed, not merely that the wrong chains get rejected above.
_ok: ds.RealParamExpr = ds.param("z").real(0.0, 1.0).log_scale().tag("t").quantized(step=0.1)
