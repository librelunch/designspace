# Examples

One task-shaped script, meant to be copied and adapted:

```console
uv run python examples/tuning_loop.py
```

`tuning_loop.py` declares a space, draws candidates from it, scores each against
a stub objective, keeps the incumbent, and reports the best configuration
together with the `(fingerprint, config_hash)` pair it should be stored under.
Replacing the objective with a real evaluation, and random search with a real
optimizer, leaves the rest of the file unchanged.

`tests/test_examples.py` runs every script here to completion, so a milestone
that changes the public surface is caught rather than letting these rot
silently.

## Learning the API

The documentation site is where the surface is covered, one topic at a time,
across eleven tutorial pages. Every code block on them is executed when the site
is built, so the outputs shown are real. Build it with:

```console
uv sync --extra docs
uv run --extra docs sphinx-build -b html docs docs/_build
```

then open `docs/_build/tutorials/index.html`.
