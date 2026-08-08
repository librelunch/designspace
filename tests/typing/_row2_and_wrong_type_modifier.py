"""The static-typing fixture (API.md, "Builder view types").

Not collected by pytest as a test module; `test_static_typing.py` feeds it
to `mypy --strict`. Each `# type: ignore[attr-defined]` below is valid only
if the named method is genuinely absent from that view's static type.
`mypy --strict` bundles `--warn-unused-ignores`, so an ignore comment that
has stopped being load-bearing fails the check on its own.
"""

import designspace as ds

# Row 2: a second type method is a static error once the first type method
# has narrowed the builder to RealParamExpr, which has no `.bool()`.
ds.param("x").real(0.0, 1.0).bool()  # type: ignore[attr-defined]

# Row 11: `.log_scale()` is Real/Integer-only; CategoricalParamExpr has no
# `.log_scale()` attribute at all.
ds.param("y").categorical("a", "b").log_scale()  # type: ignore[attr-defined]

# Row 2: `.custom()` narrows to CustomParamExpr, which has no `.real()`
# (or any other type method) either.
_w = ds.param("w").custom(sampler=lambda rng: 0.5, validator=lambda v: True)
_w.real(0.0, 1.0)  # type: ignore[attr-defined]

# Positive control: a legitimate chain interleaving a universal modifier
# (`.tag()`) between numeric-only ones must still type-check as
# RealParamExpr. `_as()` and `Self` exist so that this stays valid and
# narrowed, not merely so that the wrong chains above get rejected.
_ok: ds.RealParamExpr = ds.param("z").real(0.0, 1.0).log_scale().tag("t").quantized(step=0.1)
