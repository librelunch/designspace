"""Solver bindings for `designspace`.

A space says which configurations are valid; a solver looks for one that
scores well. This package joins the two, one module per solver. Every binding
hands back an ordinary configuration, ready to validate, hash, or pass to the
code being tuned.

Backends
--------
`designspace_solvers.optuna`: https://optuna.org/
    Suggests a trial's parameters as the objective runs. A conditional space
    is searched as declared: a parameter inactive under the choices already
    made is never suggested and is absent from the result.
`designspace_solvers.cmaes`: https://github.com/CyberAgentAILab/cmaes
    Proposes a generation at a time over a layout fixed before the run
    starts, so it takes flat spaces only and refuses the rest by path.
`designspace_solvers.configspace`: https://automl.github.io/ConfigSpace/
    Converts a space into a `ConfigurationSpace`, the socket any
    ConfigSpace-based tool reads.
`designspace_solvers.smac`: https://automl.github.io/SMAC3/
    Drives SMAC3's Bayesian-optimization facade, ask and tell, over that
    same translation.
`designspace_solvers.irace`: https://mlopez-ibanez.github.io/irace/
    Races configurations against each other, keeping the ones that keep
    winning. irace owns its loop, so it is handed a function to score a
    configuration rather than asked for one.

Notes
-----
Each backend installs from an extra of its own, `designspace-solvers[optuna]`
through `designspace-solvers[irace]`, and imports its solver lazily, so one
extra never installs another's dependencies and a backend used without its
extra raises `ImportError` naming the extra. The irace backend needs R and
the R package irace as well, and says so where either is absent.

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
