# designspace-solvers

Search a [`designspace`](https://github.com/librelunch/designspace) space with a
real optimizer. One module per solver, each taking a space as declared and
handing back ordinary configurations that the space itself validates.

This package is not published to an index yet. Install it from the repository,
choosing a backend:

```console
pip install "designspace-solvers[optuna] @ git+https://github.com/librelunch/designspace.git#subdirectory=packages/designspace-solvers"
pip install "designspace-solvers[cmaes] @ git+https://github.com/librelunch/designspace.git#subdirectory=packages/designspace-solvers"
pip install "designspace-solvers[configspace] @ git+https://github.com/librelunch/designspace.git#subdirectory=packages/designspace-solvers"
pip install "designspace-solvers[smac] @ git+https://github.com/librelunch/designspace.git#subdirectory=packages/designspace-solvers"
```

Each backend imports its solver lazily, so installing one extra never drags in
another's dependencies. A backend used without its extra raises `ImportError`
naming the extra to install.

## The four backends

| Backend | Shape | Takes |
|---|---|---|
| `designspace_solvers.optuna` | define-by-run, one trial at a time | hierarchical and conditional spaces; every kind but `custom`, `symbolic` and `code` |
| `designspace_solvers.cmaes` | ask and tell, one generation at a time | flat spaces: every parameter always active, every list a fixed length |
| `designspace_solvers.configspace` | converts to a `ConfigurationSpace` | conditional spaces whose conditions and hard constraints have a ConfigSpace form; a static-count `list`, over a scalar, subset, permutation, struct, or choice element, or a nested lift |
| `designspace_solvers.smac` | ask and tell, over the ConfigSpace translation | exactly what `configspace` takes |

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

**ConfigSpace.** `translate(space)` returns a `Translation`: a
`ConfigurationSpace` any ConfigSpace-based tool can search, `translation.decode`
to read a sampled `Configuration` back into domain units, and
`translation.encode` for the inverse. A `.when()` condition translates exactly
where every parameter it references sits as one hyperparameter and the
comparison has a ConfigSpace counterpart; a parameter whose condition does not
is refused by path, the same way a kind outside the envelope is. A hard
constraint becomes a forbidden clause where one exists; the rest are listed on
`translation.untranslated_constraints` rather than raised, `space.is_feasible`
still catching them. A listed constraint is always a relaxation and never a
restriction: the search may propose a configuration the space calls infeasible,
and never loses one the space calls feasible.

```python
import designspace as ds
from designspace_solvers.configspace import translate

space = ds.space(
    ds.param("lr").real(1e-4, 1e-1).log_scale(),
    ds.param("use_warmup").bool(),
    ds.param("warmup_steps").integer(1, 100).when(ds.param("use_warmup")),
).forbid(ds.param("lr") > 0.05)

translation = translate(space)
translation.config_space.seed(0)
configuration = translation.config_space.sample_configuration()
config = translation.decode(configuration)      # `warmup_steps` is there only when it applies
```

**SMAC.** `Optimizer` drives SMAC3's Bayesian-optimization facade, ask and
tell, over exactly the translation above: it places what `configspace` places
and refuses what `configspace` refuses. `ask()` proposes one configuration and
`tell()` reports what it scored; `observe()` reports a configuration the
optimizer never proposed, which is how a run is warm started.

```python
import designspace as ds
from designspace_solvers.smac import Optimizer

space = ds.space(
    ds.param("cutoff_hz").real(1.0, 1e4).log_scale(),
    ds.param("order").integer(1, 12),
    ds.param("window").categorical("hann", "hamming", "blackman"),
)

optimizer = Optimizer(space, seed=0, n_trials=50)
for _ in range(50):
    proposal = optimizer.ask()
    optimizer.tell(proposal, evaluate(proposal.config))

best, value = min(optimizer.history, key=lambda pair: pair[1])
```

## What a backend does with a declaration

A prior is a coordinate system rather than a hint, so it reaches the solver
instead of being applied afterwards. A real or integer parameter carries its
prior in its chart, so a log-scaled parameter is perturbed multiplicatively and
a quantized one lands on its grid, whichever backend is driving. A categorical,
bool or subset parameter declaring `.prior(weights=...)` starts CMA-ES's own
categorical distribution, or ConfigSpace's, at those weights rather than
uniform. An ordinal is the exception under either: it sits in a block that
holds no distribution over levels for weights to seed, CMA-ES's integer block
and ConfigSpace's `OrdinalHyperparameter` alike.

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
uv run python packages/designspace-solvers/examples/smac_conditional.py
```

`optuna_hpo.py` tunes a space with a variant choice, a conditional parameter
and a hard constraint, then reports the best feasible configuration and the
`(fingerprint, config_hash)` pair it should be stored under.
`cmaes_warm_start.py` draws an incumbent from the space, warm starts the
optimizer with it, runs thirty generations, and shows what a space with no
fixed layout is refused with. `smac_conditional.py` searches the same space as
`optuna_hpo.py` with SMAC3 instead, and shows what its step-budget constraint
looks like once translated: reported rather than raised, since it multiplies
two parameters together, which is outside what a forbidden clause expresses.

## Status

Prototype. Nothing here is published, the version is `0.0.0`, and the surface
will change without notice. The package exists to prove that a real optimizer
can be driven from the public representation alone, and to find the places
where it cannot.
