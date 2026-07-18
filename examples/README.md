# Examples

Runnable, self-contained tours of the `designspace` API, built around a single
theme — **configuring a metaheuristic** — in increasing complexity. Each file
has a `build_space()` you can import and a `main()` that narrates what it built
and sampled.

Run any of them with:

```
uv run python examples/01_simulated_annealing.py
```

| # | File | Metaheuristic | Shape | Features |
|---|------|---------------|-------|----------|
| 1 | `01_simulated_annealing.py` | Simulated Annealing | Flat scalar space | `real`/`integer`/`categorical`/`ordinal`/`bool`, `log_scale`, `quantized`, one `.when()`, `forbid` vs. `constrain` |
| 2 | `02_genetic_algorithm.py` | Genetic Algorithm | Conditional / hierarchical | `.choice()` variants + payloads, `.prior(weights=)`, cross-parameter `forbid`, `ds.variant`/`ds.payload`/`ds.destructure`, `infeasibility_reasons` |
| 3 | `03_memetic_algorithm.py` | Memetic Algorithm | Variable-length + aggregates | the `.repeat()` lift, lifted choice, `.subset()`, vector aggregates (`count_of`, `is_sorted`), `flatten`/`unflatten` round-trip |

These use only the public surface implemented so far (through the current
milestone — see `PROGRESS.md`): space definition, sampling
(`sample_one`/`sample_dicts`), validation, constraint evaluation, and the
config utilities. Serialization, structural operations, and the DataFrame
sampler arrive in later milestones and are intentionally not used here.

Two ideas recur across all three, worth keeping in mind:

- **Inactive means absent.** A parameter whose `.when(...)` is false does not
  appear in the config dict — never `None`, never `NaN`.
- **`forbid` defines feasibility; `constrain` only annotates.** The reference
  sampler rejects configs that trip a `forbid`, but it never enforces a
  `constrain` — declared constraints ride along in `evaluate_constraints` with
  a signed margin for a consumer to weigh. Example 3's restart-schedule
  constraint is deliberately left unenforced to show exactly this.
