"""SMAC3 binding.

`Optimizer` drives SMAC's Bayesian-optimization facade over the ConfigSpace
translation `designspace_solvers.configspace` builds, ask and tell, one
configuration at a time. It places exactly what the ConfigSpace binding
places, `KINDS` being the same frozenset, and refuses exactly what that
binding refuses: a condition or a hard constraint with no ConfigSpace
counterpart surfaces the same way, since `Optimizer` builds its search space
by calling `configspace.translate` and nothing here narrows it further.

`ask()` proposes one configuration, decoded through the translation; `tell()`
reports what it scored. `observe()` reports a configuration the optimizer
never proposed, encoded back into ConfigSpace's own terms, which is how a
run is warm started from a configuration already known to be good, the
counterpart to the cmaes binding's `mean=`. `history` keeps every pair
scored so far, `ask`- and `observe`-derived alike.

SMAC configures Python's root logger and writes a run directory to disk by
default, both invasive for a library call; `Optimizer` disables the former
outright and takes `output_directory` for the latter rather than leaving
either to SMAC's own defaults.

Examples
--------
Ten trials against a mixed continuous, integer and categorical space:

>>> import tempfile
>>> import designspace as ds
>>> from designspace_solvers.smac import Optimizer
>>> space = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("depth").integer(1, 8),
...     ds.param("act").categorical("relu", "tanh"),
... )
>>> def loss(config):
...     return abs(config["lr"] - 0.01) + abs(config["depth"] - 5)
>>> with tempfile.TemporaryDirectory() as tmp:
...     optimizer = Optimizer(space, seed=0, n_trials=10, output_directory=tmp)
...     for _ in range(10):
...         proposal = optimizer.ask()
...         optimizer.tell(proposal, loss(proposal.config))
>>> all(space.is_feasible(config) for config, _ in optimizer.history)
True

`history` holds every configuration scored, so the best one is read from it:

>>> best, value = min(optimizer.history, key=lambda pair: pair[1])
>>> value <= max(v for _, v in optimizer.history)
True

Reporting a configuration the optimizer never asked for warm starts the
surrogate with it, the counterpart to the cmaes binding's `mean=`:

>>> with tempfile.TemporaryDirectory() as tmp:
...     warm = Optimizer(space, seed=0, n_trials=5, output_directory=tmp)
...     warm.observe({"lr": 0.01, "depth": 5, "act": "relu"}, 0.0)
>>> warm.history
[({'lr': 0.01, 'depth': 5, 'act': 'relu'}, 0.0)]
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import designspace as ds
from designspace_solvers._placement import require_backend
from designspace_solvers.configspace import KINDS, translate

if TYPE_CHECKING:
    from smac.runhistory import TrialInfo

__all__ = ["KINDS", "Optimizer", "Proposal"]

#: SMAC's local-search acquisition maximizer times its own iterations and
#: reports the mean, `np.mean(times)`, before the first iteration has run,
#: which is a mean over nothing. Both warnings come from that one call and
#: report nothing about this binding or the space being searched.
_LOCAL_SEARCH_EMPTY_MEAN = (
    "Mean of empty slice",
    "invalid value encountered in scalar divide",
)


def _require_smac() -> Any:
    return require_backend("smac", binding="SMAC", needs="smac", extra="smac")


@dataclass(frozen=True)
class Proposal:
    """One configuration SMAC proposed, and the handle to score it.

    Attributes
    ----------
    config : dict[str, Any]
        The proposed configuration, in domain units.
    info : smac.runhistory.TrialInfo
        SMAC's own record of the proposal. Pass the proposal back to
        `Optimizer.tell` rather than reading this.
    """

    config: dict[str, Any]
    info: TrialInfo


class Optimizer:
    """Drive SMAC's Bayesian optimization over a translated design space.

    Parameters
    ----------
    space : designspace.Space
        The space to search. Placed exactly as
        `designspace_solvers.configspace.translate` places it; a condition
        or a hard constraint with no ConfigSpace counterpart is refused the
        same way.
    facade : Callable[..., Any] | None
        The SMAC facade class to drive, called as `facade(scenario,
        target_function=None, overwrite=True, logging_level=False)`.
        Defaults to `smac.HyperparameterOptimizationFacade`.
    seed : int
        The scenario's random seed.
    n_trials : int
        The trial budget SMAC's initial design and intensifier plan around.
    output_directory : str | Path | None
        Where SMAC writes its run directory. Defaults to SMAC's own
        `smac3_output/`.
    default : dict[str, Any] | None
        Forwarded to `configspace.translate`: a configuration to seed
        hyperparameter defaults from, in place of each parameter's own
        declared default.
    **scenario_kwargs : Any
        Forwarded to `smac.Scenario`.

    Attributes
    ----------
    translation : designspace_solvers.configspace.Translation
        The space as SMAC sees it. Read `untranslated_constraints` here for
        the hard constraints the search carries no margin for.
    scenario : smac.Scenario
        The scenario this optimizer was built with.
    facade : Any
        The SMAC facade being driven. `ask` and `tell` go through this
        optimizer rather than through the facade directly, so that `history`
        stays a complete record.
    history : list[tuple[dict[str, Any], float]]
        Every configuration scored so far paired with its cost, in the order
        reported, `ask`- and `observe`-derived alike.

    Raises
    ------
    UnsupportedSpace
        When a parameter's kind, or its condition, has no ConfigSpace
        counterpart. Every reason is reported at once.
    """

    def __init__(
        self,
        space: ds.Space,
        *,
        facade: Callable[..., Any] | None = None,
        seed: int = 0,
        n_trials: int = 100,
        output_directory: str | Path | None = None,
        default: dict[str, Any] | None = None,
        **scenario_kwargs: Any,
    ) -> None:
        smac = _require_smac()
        self.translation = translate(space, default=default)
        directory_kwargs = (
            {} if output_directory is None else {"output_directory": output_directory}
        )
        self.scenario = smac.Scenario(
            self.translation.config_space,
            seed=seed,
            n_trials=n_trials,
            **directory_kwargs,
            **scenario_kwargs,
        )
        facade_cls = facade or smac.HyperparameterOptimizationFacade
        self.facade = facade_cls(
            self.scenario, target_function=None, overwrite=True, logging_level=False
        )
        self.history: list[tuple[dict[str, Any], float]] = []

    def ask(self) -> Proposal:
        """Propose one configuration.

        Returns
        -------
        Proposal
            The proposed configuration, in domain units, and the handle to
            score it.
        """
        with warnings.catch_warnings():
            for message in _LOCAL_SEARCH_EMPTY_MEAN:
                warnings.filterwarnings("ignore", message=message, category=RuntimeWarning)
            info = self.facade.ask()
        return Proposal(config=self.translation.decode(info.config), info=info)

    def tell(self, proposal: Proposal, cost: float) -> None:
        """Report what a proposal scored.

        Parameters
        ----------
        proposal : Proposal
            A proposal `ask` returned.
        cost : float
            The score to minimize.
        """
        from smac.runhistory import TrialValue

        self.facade.tell(proposal.info, TrialValue(cost=float(cost)))
        self.history.append((proposal.config, float(cost)))

    def observe(self, config: dict[str, Any], cost: float) -> None:
        """Report a configuration the optimizer never proposed.

        Parameters
        ----------
        config : dict[str, Any]
            A complete configuration this optimizer's space validates.
        cost : float
            The score to minimize.
        """
        from smac.runhistory import TrialInfo, TrialValue

        configuration = self.translation.encode(config)
        info = TrialInfo(config=configuration, seed=self.scenario.seed)
        self.facade.tell(info, TrialValue(cost=float(cost)))
        self.history.append((config, float(cost)))
