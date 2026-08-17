"""Solver bindings for `designspace`.

A space says which configurations are valid; a solver looks for one that
scores well. This package joins the two, one module per solver. Every binding
hands back an ordinary configuration, ready to validate, hash, or pass to the
code being tuned.

`designspace_solvers.optuna` suggests a trial's parameters as the objective
runs, following what the space reports as assignable. A conditional or
hierarchical space is searched as declared: a parameter that is inactive under
the choices already made is never suggested and is absent from the result.

`designspace_solvers.cmaes` proposes a generation at a time over a layout
fixed before the run starts. It searches a flat space, meaning every parameter
always active and every list a fixed length, and refuses anything else by
path rather than padding or imputing a value.

`designspace_solvers.configspace` converts a space into a `ConfigurationSpace`
instead of interpreting it directly, the socket any ConfigSpace-based tool
reads. A conditional space translates exactly, a parameter whose condition has
no ConfigSpace counterpart being refused by path rather than placed
unconditionally, and a hard constraint translates into a forbidden clause
where one exists, the rest reported rather than raised.

`designspace_solvers.smac` drives SMAC3's Bayesian-optimization facade, ask
and tell, over that same translation. It places exactly what the ConfigSpace
binding places and refuses exactly what that binding refuses.

Install one extra per backend: `designspace-solvers[optuna]`,
`designspace-solvers[cmaes]`, `designspace-solvers[configspace]`, or
`designspace-solvers[smac]`. Each backend imports its solver lazily, so one
extra never installs the other's dependencies, and a backend used without its
extra raises `ImportError` naming the extra to install.

A backend states the parameter kinds it places in its own `KINDS` and checks
the space it is given, raising `UnsupportedSpace` with every offending
parameter at once. `profile`, `rejections` and `require` ask that question
ahead of time, which is how a caller picks a backend for a space it did not
write.

Examples
--------
Optuna, over a space whose warmup steps exist only when warmup is on:

>>> import optuna
>>> import designspace as ds
>>> from designspace_solvers.optuna import suggest
>>> optuna.logging.set_verbosity(optuna.logging.WARNING)
>>> space = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("use_warmup").bool(),
...     ds.param("warmup_steps").integer(1, 100).when(ds.param("use_warmup")),
... )
>>> tried = {}
>>> def objective(trial):
...     config = suggest(trial, space)
...     tried[trial.number] = config
...     return abs(config["lr"] - 0.01) + config.get("warmup_steps", 0) / 100
>>> study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
>>> study.optimize(objective, n_trials=20)
>>> all(space.is_feasible(config) for config in tried.values())
True

A trial that turned warmup off carries no step count at all.

>>> sorted({"warmup_steps" in config for config in tried.values()})
[False, True]

CMA-ES, over the flat part of the same problem, a generation at a time:

>>> from designspace_solvers.cmaes import Optimizer
>>> flat = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("depth").integer(1, 8),
... )
>>> def loss(config):
...     return abs(config["lr"] - 0.01) + abs(config["depth"] - 5)
>>> optimizer = Optimizer(flat, seed=0)
>>> for _ in range(20):
...     proposals = optimizer.ask()
...     optimizer.tell([(p, loss(p.config)) for p in proposals])
>>> config, value = min(optimizer.history, key=lambda pair: pair[1])
>>> config["depth"], value < 0.01
(5, True)

Whether a backend can take a space at all, asked before starting one:

>>> from designspace_solvers import rejections
>>> from designspace_solvers.cmaes import KINDS
>>> found = rejections(space, kinds=KINDS, conditional=False, variable_length=False)
>>> [(r.path, r.reason) for r in found]
[('warmup_steps', 'active only under a condition, and this backend has no
representation for an absent parameter')]
"""

from __future__ import annotations

from designspace_solvers._profile import (
    ParamProfile,
    Rejection,
    SpaceProfile,
    UnsupportedSpace,
    profile,
    rejections,
    require,
)

__version__ = "0.0.0"

__all__ = [
    "ParamProfile",
    "Rejection",
    "SpaceProfile",
    "UnsupportedSpace",
    "__version__",
    "profile",
    "rejections",
    "require",
]
