"""Optuna binding.

`suggest(trial, space)` builds one complete configuration inside an objective
function. It draws every parameter the space reports as assignable, in
dependency order, and returns the configuration in nested form. A parameter
that is inactive under the choices already drawn is never suggested, so it is
absent from the result, and the result is always a configuration the space
calls complete.

`set_constraints(trial, space, config)` scores a configuration against every
hard constraint and writes the scores onto the trial, each under a name
derived from the declaration it came from. A sampler reads them from there
and steers toward feasibility. `constraint_values(space, config)` computes
the same scores without a trial.

Priors reach Optuna two ways. A real or integer parameter with no
quantization and either no prior or a log scale is drawn from Optuna's own
distribution, so a log-scaled one carries `log=True` and the sampler perturbs
it multiplicatively. Any other prior, and any quantized parameter, is drawn
in unit coordinates and decoded through the parameter's chart, which
reproduces the declared shape and lands on the declared grid without Optuna
representing either. An ordinal is drawn as an index, keeping its order
visible to the sampler, and a categorical as an unordered choice.

`KINDS` holds the parameter kinds this binding places. A space carrying any
other kind raises `UnsupportedSpace` naming the parameter.

Examples
--------
A conditional space, searched as declared:

>>> import optuna
>>> import designspace as ds
>>> from designspace_solvers.optuna import suggest
>>> optuna.logging.set_verbosity(optuna.logging.WARNING)
>>> space = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("use_warmup").bool(),
...     ds.param("warmup_steps").integer(1, 100).when(ds.param("use_warmup")),
... )
>>> seen = []
>>> def objective(trial):
...     config = suggest(trial, space)
...     seen.append(config)
...     return config["lr"] * 100 + config.get("warmup_steps", 0)
>>> study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
>>> study.optimize(objective, n_trials=5)
>>> all(space.is_complete(config) for config in seen)
True

An inactive parameter is absent rather than filled, so a trial that turned
warmup off carries no step count at all.

>>> sorted({"warmup_steps" in config for config in seen})
[False, True]

A constrained space, where the sampler reads the margin rather than a verdict.
Score the configuration in the objective and the sampler picks the scores up
from the trial:

>>> from designspace_solvers.optuna import set_constraints
>>> budget = ds.space(
...     ds.param("workers").integer(1, 16),
...     ds.param("memory_gb").integer(1, 64),
... ).forbid(ds.param("workers") * ds.param("memory_gb") > 64, tags=("budget",))
>>> def throughput(trial):
...     config = suggest(trial, budget)
...     set_constraints(trial, budget, config)
...     return -float(config["workers"])
>>> study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=0))
>>> study.optimize(throughput, n_trials=30)

A constraint informs the sampler; it does not filter the study. Each trial
carries its own scores, named for the constraint they measure, and a trial is
feasible when none of them is above zero:

>>> best = min(
...     (t for t in study.trials if all(v <= 0.0 for v in t.constraints.values())),
...     key=lambda t: t.value,
... )
>>> sorted(best.constraints)
['forbid[budget]']
>>> best.params["workers"] * best.params["memory_gb"] <= 64
True
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

import designspace as ds
from designspace_solvers._profile import Rejection, UnsupportedSpace, require

if TYPE_CHECKING:
    import optuna

__all__ = ["KINDS", "constraint_values", "set_constraints", "suggest"]

#: The parameter kinds this binding places. Absent are the program kinds, a
#: symbolic or code parameter having no Optuna counterpart, and the custom
#: kind, whose genotype its type author supplies. Generating either is a
#: strategy the library leaves to its consumer.
KINDS = frozenset(
    {
        "real",
        "integer",
        "bool",
        "categorical",
        "ordinal",
        "subset",
        "permutation",
        "choice",
        "space",
        "list",
    }
)


def _require_optuna() -> None:
    try:
        import optuna  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by the core install path
        raise ImportError(
            "the Optuna binding needs Optuna, which is an optional dependency. "
            "Install it with `pip install designspace-solvers[optuna]`."
        ) from exc


def _suggest_scalar(trial: optuna.Trial, name: str, defn: ds.ParamDef) -> Any:
    """Suggest a real or integer value.

    Optuna's own distributions are used only where they reproduce the declared
    chart exactly, which is when the parameter is not quantized and its prior
    is either absent or a log scale. Everything else is suggested in unit
    coordinates and decoded through the chart. Reading the domain's ends and
    suggesting between them would ignore a grid or a shaped prior, and produce
    values the space rejects.
    """
    chart = defn.chart
    assert chart is not None, f"{name}: a real or integer parameter always carries a chart"
    log = isinstance(defn.prior, ds.Log)
    native = defn.quantized is None and (defn.prior is None or log)
    if not native:
        return chart.from_unit(trial.suggest_float(name, 0.0, 1.0))
    # The chart's ends are the envelope bounds already resolved to numbers. The
    # domain's own `lo` and `hi` may be expressions, so reading them here would
    # mean re-deriving an envelope the library has derived.
    lo = chart.from_unit(0.0)
    hi = chart.from_unit(1.0)
    if defn.type_kind == "integer":
        return trial.suggest_int(name, int(lo), int(hi), log=log)
    return trial.suggest_float(name, float(lo), float(hi), log=log)


def _suggest_one(trial: optuna.Trial, space: ds.Space, path: str) -> Any:
    defn = space.param_def(path)
    kind = defn.type_kind
    domain = defn.domain

    if kind in ("real", "integer"):
        return _suggest_scalar(trial, path, defn)

    if kind == "list":
        # A lift is assignable only when its count is zero, every other count
        # being assigned through its elements. In the flat form a list is
        # written as its length, and zero is what marks it active and empty
        # rather than inactive.
        return 0

    if kind == "bool":
        return trial.suggest_categorical(path, [False, True])

    if kind in ("categorical", "ordinal"):
        assert isinstance(domain, ds.CategoricalDomain | ds.OrdinalDomain)
        values = domain.values
        # Optuna restricts a categorical's choices to its own scalar types,
        # while a domain here holds arbitrary objects. The index carries the
        # choice instead. An ordinal suggests an integer rather than a
        # category, which is what keeps its order visible to the sampler.
        if kind == "ordinal":
            return values[trial.suggest_int(path, 0, len(values) - 1)]
        return values[trial.suggest_categorical(path, list(range(len(values))))]

    if kind == "choice":
        assert isinstance(domain, ds.ChoiceDomain)
        return trial.suggest_categorical(path, list(domain.variants))

    if kind == "subset":
        assert isinstance(domain, ds.SubsetDomain)
        # One inclusion flag per item. The size bounds are left to validation
        # rather than repaired here: a repair would silently move the proposal
        # Optuna is trying to learn from.
        return [
            item
            for index, item in enumerate(domain.items)
            if trial.suggest_categorical(f"{path}[{index}]", [False, True])
        ]

    if kind == "permutation":
        assert isinstance(domain, ds.PermutationDomain)
        # Random keys: a real coordinate per item, ordered by value. Every
        # draw is a valid permutation, so there is nothing to reject.
        keys = [trial.suggest_float(f"{path}[{i}]", 0.0, 1.0) for i in range(len(domain.items))]
        return [item for _, item in sorted(zip(keys, domain.items, strict=True))]

    raise UnsupportedSpace(
        "the Optuna binding",
        [Rejection(path=path, kind=kind, reason="no suggestion is defined for this kind")],
    )


def suggest(trial: optuna.Trial, space: ds.Space) -> dict[str, Any]:
    """Build one complete configuration by suggesting each active parameter.

    Parameters
    ----------
    trial : optuna.Trial
        The trial to draw suggestions from.
    space : designspace.Space
        The space to configure.

    Returns
    -------
    dict[str, Any]
        A complete configuration. An inactive parameter is absent rather than
        filled, which is what the space means by inactive.

    Raises
    ------
    UnsupportedSpace
        When the space holds a parameter kind this binding cannot place.

    Examples
    --------
    >>> import optuna
    >>> import designspace as ds
    >>> from designspace_solvers.optuna import suggest
    >>> optuna.logging.set_verbosity(optuna.logging.WARNING)
    >>> space = ds.space(ds.param("n").integer(1, 4))
    >>> study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    >>> trial = study.ask()
    >>> config = suggest(trial, space)
    >>> space.is_complete(config)
    True
    """
    _require_optuna()
    require(space, backend="the Optuna binding", kinds=KINDS)

    # Built in the flat form, which is the vocabulary `next_assignable`
    # reports in, so a suggestion is written at the path it named.
    config: dict[str, Any] = {}
    while True:
        assignable = space.next_assignable(config)
        if not assignable:
            return ds.unflatten(config, space)
        for path in assignable:
            config[path] = _suggest_one(trial, space, path)


#: A hard constraint's name before collisions are resolved: its kind, the
#: label read off its tags or its position, and the element it belongs to.
_Name = tuple[str, str, str | None]


def _names(space: ds.Space, config: dict[str, Any]) -> list[tuple[_Name, ds.ConstraintEval]]:
    """Name every hard constraint evaluated against a configuration.

    A constraint's tags name it, one used as written and several sorted and
    joined, which is what makes a score legible where it is read back. An
    untagged constraint takes its position among the constraints of its kind
    instead. Positions count every hard evaluation, including the ones this
    configuration leaves inapplicable, so that a name is a fact about the
    space rather than about the configuration being scored.
    """
    counters: Counter[tuple[str, str | None]] = Counter()
    named: list[tuple[_Name, ds.ConstraintEval]] = []
    for evaluation in space.evaluate_constraints(config):
        constraint = evaluation.constraint
        if not constraint.hard:
            continue
        scope = (constraint.kind, evaluation.instance_path)
        position = counters[scope]
        counters[scope] += 1
        label = ",".join(sorted(constraint.tags)) or str(position)
        named.append(((constraint.kind, label, evaluation.instance_path), evaluation))
    return named


def _scored(space: ds.Space, config: dict[str, Any]) -> list[tuple[str, float | None, bool]]:
    """Key and score every applicable hard constraint, in Optuna's convention.

    Each entry is the key, the score, and whether the evaluation is violated.
    The score is `None` where the predicate carries no numeric distance, which
    is a question the caller settles.
    """
    named = _names(space, config)
    shared: Counter[_Name] = Counter(name for name, _ in named)
    ordinals: Counter[_Name] = Counter()
    scored: list[tuple[str, float | None, bool]] = []
    for name, evaluation in named:
        kind, label, instance_path = name
        if shared[name] > 1:
            # Two constraints of one kind carrying the same tags. Each keeps
            # the tags and takes an ordinal, rather than one of them landing
            # on the other's key and being dropped.
            label = f"{label}.{ordinals[name]}"
            ordinals[name] += 1
        if not evaluation.applicable:
            continue
        key = f"{kind}[{label}]"
        if instance_path is not None:
            key = f"{key}@{instance_path}"
        value: float | None = None
        if evaluation.margin is not None:
            margin = float(evaluation.margin)
            value = -margin if evaluation.constraint.feasible_when_satisfied else margin
        scored.append((key, value, evaluation.violated))
    return scored


def constraint_values(space: ds.Space, config: dict[str, Any]) -> dict[str, float | None]:
    """Score a configuration against every hard constraint, in Optuna's convention.

    Optuna reads a constraint as satisfied when its value is at most zero. Each
    evaluation contributes its margin, which measures the predicate rather than
    the constraint, oriented so that a feasible configuration scores at most
    zero. A `require` is feasible when its predicate holds, so its margin is
    negated; a `forbid` names a bad state, so its margin passes through. The
    result is a graded distance from feasibility rather than a flag, which is
    what a constrained sampler can actually descend.

    Soft constraints are excluded. `encourage` and `discourage` express
    preference, not feasibility, and folding them in here would make a merely
    unfashionable configuration look infeasible.

    A constraint this configuration leaves inapplicable is absent rather than
    scored zero: one whose parameters are inactive is never violated, and
    Optuna reads a constraint it was never told about as satisfied. One that
    applies but carries no numeric distance, such as an opaque predicate
    returning a bool, scores `None`. There is a verdict and nothing to
    measure, and `set_constraints` is where that verdict becomes a number.

    Each score is keyed by the constraint's tags where it carries any and by
    its position among the constraints of its kind otherwise. A constraint
    declared on the element of a repeated block is scored once per element,
    keyed with that element's path.

    Parameters
    ----------
    space : designspace.Space
        The space the configuration belongs to.
    config : dict[str, Any]
        The configuration to score.

    Returns
    -------
    dict[str, float | None]
        One entry per applicable hard constraint evaluation.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers.optuna import constraint_values
    >>> space = ds.space(
    ...     ds.param("a").integer(0, 10), ds.param("b").integer(0, 10)
    ... ).forbid(ds.param("a") > ds.param("b"), tags=("ordering",))
    >>> constraint_values(space, {"a": 1, "b": 5})
    {'forbid[ordering]': -4.0}
    >>> constraint_values(space, {"a": 9, "b": 5})
    {'forbid[ordering]': 4.0}

    An untagged constraint is named by its position instead:

    >>> plain = ds.space(ds.param("a").integer(0, 10)).forbid(ds.param("a") > 5)
    >>> constraint_values(plain, {"a": 9})
    {'forbid[0]': 4.0}
    """
    return {key: value for key, value, _ in _scored(space, config)}


def set_constraints(trial: optuna.Trial, space: ds.Space, config: dict[str, Any]) -> None:
    """Write a configuration's constraint scores onto a trial.

    A sampler reads a trial's constraints for itself, so scoring the
    configuration inside the objective is the whole of what a constrained
    search needs. The scores and their keys are the ones `constraint_values`
    computes.

    A constraint that applies but carries no numeric distance is written as a
    verdict, `1.0` where the evaluation is violated and `-1.0` where it is
    not. Optuna takes a number, and writing zero would report a violated
    constraint as feasible.

    Parameters
    ----------
    trial : optuna.Trial
        The trial to write the scores onto.
    space : designspace.Space
        The space the configuration belongs to.
    config : dict[str, Any]
        The configuration to score.

    Examples
    --------
    >>> import optuna
    >>> import designspace as ds
    >>> from designspace_solvers.optuna import set_constraints, suggest
    >>> optuna.logging.set_verbosity(optuna.logging.WARNING)
    >>> space = ds.space(
    ...     ds.param("a").integer(0, 10), ds.param("b").integer(0, 10)
    ... ).forbid(ds.param("a") > ds.param("b"), tags=("ordering",))
    >>> study = optuna.create_study(sampler=optuna.samplers.RandomSampler(seed=0))
    >>> trial = study.ask()
    >>> config = suggest(trial, space)
    >>> set_constraints(trial, space, config)
    >>> sorted(trial.constraints)
    ['forbid[ordering]']
    """
    _require_optuna()
    for key, value, violated in _scored(space, config):
        if value is None:
            value = 1.0 if violated else -1.0
        trial.set_constraint(key, value)
