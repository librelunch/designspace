# designspace-solvers

Search a [`designspace`](https://github.com/wurthjon/designspace) space with a
real optimizer. One module per solver, each taking a space as declared and
handing back ordinary configurations that the space itself validates.

```console
pip install designspace-solvers[optuna]
pip install designspace-solvers[cmaes]
```

Each backend imports its solver lazily, so installing one extra never drags in
another's dependencies. A backend used without its extra raises `ImportError`
naming the extra to install.

## The two backends

| Backend | Shape | Takes |
|---|---|---|
| `designspace_solvers.optuna` | define-by-run, one trial at a time | hierarchical and conditional spaces; every kind but `custom`, `symbolic` and `code` |
| `designspace_solvers.cmaes` | ask and tell, one generation at a time | flat spaces: every parameter always active, every list a fixed length |

**Optuna.** `suggest(trial, space)` builds one complete configuration inside an
objective, drawing each parameter as the trial runs. A parameter that is
inactive under the choices already drawn is never suggested, so it is absent
from the result rather than filled with a stand-in.
`set_constraints(trial, space, config)` scores the configuration against every
hard constraint and writes the scores onto the trial, at most zero where the
configuration is feasible. The sampler reads them from there and steers toward
feasibility. Each score is named for the constraint it measures, by that
constraint's tags where it carries any, so a trial reads back in the terms the
space was declared in. `constraint_values(space, config)` computes the same
scores without a trial.

```python
import optuna
import designspace as ds
from designspace_solvers.optuna import set_constraints, suggest

space = ds.space(
    ds.param("lr").real(1e-4, 1e-1).log_scale(),
    ds.param("use_warmup").bool(),
    ds.param("warmup_steps").integer(1, 100).when(ds.param("use_warmup")),
).forbid(ds.param("lr") * ds.param("warmup_steps") > 1.0, tags=("budget",))

def objective(trial):
    config = suggest(trial, space)      # `warmup_steps` is there only when it applies
    set_constraints(trial, space, config)   # scored under `forbid[budget]`
    return train(**config)

study = optuna.create_study()
study.optimize(objective, n_trials=50)
```

**CMA-ES.** `Optimizer.ask()` proposes a generation of configurations in domain
units and `Optimizer.tell()` reports what each one scored. `mean=` starts the
search at a configuration already known to be good, and `sigma=` sets the
initial step in unit coordinates, meaning the same thing for every parameter
whatever its domain.

```python
import designspace as ds
from designspace_solvers.cmaes import Optimizer

space = ds.space(
    ds.param("cutoff_hz").real(1.0, 1e4).log_scale(),
    ds.param("order").integer(1, 12),
    ds.param("window").categorical("hann", "hamming", "blackman"),
)

optimizer = Optimizer(space, seed=0)
for _ in range(30):
    proposals = optimizer.ask()
    optimizer.tell([(p, evaluate(p.config)) for p in proposals])

best, value = min(optimizer.history, key=lambda pair: pair[1])
```

## What a backend does with a declaration

A prior is a coordinate system rather than a hint, so it reaches the solver
instead of being applied afterwards. A real or integer parameter carries its
prior in its chart, so a log-scaled parameter is perturbed multiplicatively and
a quantized one lands on its grid, whichever backend is driving. A categorical,
bool or subset parameter declaring `.prior(weights=...)` starts CMA-ES's own
categorical distribution at those weights rather than uniform. An ordinal is
the exception under CMA-ES: it sits in the solver's integer block, which holds
no distribution over levels for weights to seed.

Nothing is padded, imputed, or relaxed. A backend accepts the spaces it can
represent and refuses the rest by name, reporting every offending parameter at
once with its path and kind:

```pycon
>>> from designspace_solvers import UnsupportedSpace
>>> try:
...     Optimizer(conditional_space)
... except UnsupportedSpace as refusal:
...     print(refusal)
the CMA-ES binding cannot search this space: level (integer): active only under
a condition, and this backend has no representation for an absent parameter
```

`profile`, `rejections` and `require` ask that question ahead of time, which is
how a caller picks a backend for a space it did not write.

## Examples

```console
uv run python packages/designspace-solvers/examples/optuna_hpo.py
uv run python packages/designspace-solvers/examples/cmaes_warm_start.py
```

`optuna_hpo.py` tunes a space with a variant choice, a conditional parameter
and a hard constraint, then reports the best feasible configuration and the
`(fingerprint, config_hash)` pair it should be stored under.
`cmaes_warm_start.py` draws an incumbent from the space, warm starts the
optimizer with it, runs thirty generations, and shows what a space with no
fixed layout is refused with.

## Status

Prototype. Nothing here is published, the version is `0.0.0`, and the surface
will change without notice. The package exists to prove that a real optimizer
can be driven from the public representation alone, and to find the places
where it cannot.
