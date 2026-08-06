# Examples

```console
uv run python examples/tuning_loop.py
```

`tuning_loop.py` declares a space, draws candidates from it, scores each against
a stub objective, keeps the incumbent, and reports the best configuration
together with the `(fingerprint, config_hash)` pair it should be stored under.

For more information, take a look at the docs.