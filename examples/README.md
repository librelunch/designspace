# Examples

Ten runnable scripts, each self-contained:

```console
uv run python examples/01_simulated_annealing.py
```

Examples 01 to 04 grow the *shape* of a space, from flat through hierarchical,
variable-length and custom-typed. Examples 05 to 10 hold the shape plain and
grow what is *done* with a space instead.

The documentation site walks through every script and carries the
`API.md`-section to example index. Build it with:

```console
uv sync --extra docs
uv run sphinx-build -b html docs docs/_build
```

then open `docs/_build/examples/index.html`.

`tests/test_examples.py` runs all ten to completion, so a milestone that
changes the public surface is caught here rather than letting these rot
silently.
