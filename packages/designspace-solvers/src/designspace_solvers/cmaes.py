"""CMA-ES binding.

`Optimizer` searches a space by ask and tell. `ask` proposes a generation of
configurations in domain units, `tell` reports what each of them scored, and
`history` keeps every pair scored so far. `sigma` sets the initial step in
unit coordinates, so one value means the same thing for every parameter
whatever its domain, and `mean` starts the search at a configuration already
known to be good.

The layout is fixed before the first generation, so the space must be flat:
every parameter always active, every list a fixed length, and no subspace or
variant. `Optimizer` refuses anything else on construction, naming each
parameter responsible. `KINDS` holds the kinds it places.

Where each kind sits. A real parameter takes a continuous coordinate in
`[0, 1]` decoded through its chart, so a log-scaled one is perturbed
multiplicatively and a quantized one lands on its grid. An integer with at
most `MAX_INTEGER_LEVELS` values takes a slot in the solver's integer block,
which holds its values explicitly; a wider one takes a continuous coordinate
instead. An ordinal takes the integer block too, keeping its order visible to
the solver, while a categorical, a bool, and each item of a subset take the
categorical block, which the solver represents one-hot. A permutation takes
one continuous coordinate per item and is read back in that order, so every
proposal is a valid ordering.

A declared prior reaches the solver wherever the solver has somewhere to put
it. A real or integer parameter carries its prior in its chart, so the
geometry arrives with the coordinate. A categorical, bool or subset parameter
with `.prior(weights=...)` starts the solver's own categorical distribution
at those weights rather than uniform, and the run adapts from there. An
ordinal is the exception: it sits in the integer block, which holds a
Gaussian rather than a distribution over levels, so its weights have no
counterpart and do not reach the solver.

Examples
--------
Ten generations against a mixed continuous, integer and categorical space:

>>> import designspace as ds
>>> from designspace_solvers.cmaes import Optimizer
>>> space = ds.space(
...     ds.param("lr").real(1e-4, 1e-1).log_scale(),
...     ds.param("depth").integer(1, 8),
...     ds.param("act").categorical("relu", "tanh"),
... )
>>> def loss(config):
...     return abs(config["lr"] - 0.01) + abs(config["depth"] - 5)
>>> optimizer = Optimizer(space, seed=0)
>>> for _ in range(10):
...     proposals = optimizer.ask()
...     optimizer.tell([(p, loss(p.config)) for p in proposals])
>>> all(space.is_feasible(p.config) for p in proposals)
True

`history` holds every configuration scored, so the best one is read from it:

>>> best, value = min(optimizer.history, key=lambda pair: pair[1])
>>> best["depth"], value < 0.01
(5, True)

A run starting from a known-good configuration searches around it. Only the
continuous and integer parameters inform the mean:

>>> warm = Optimizer(space, seed=0, sigma=0.05, mean=best)
>>> first = warm.ask()[0].config
>>> first["depth"], round(first["lr"], 2)
(5, 0.01)

Declared weights start the categorical block where the space says the good
values are, so a heavily weighted variant dominates the first generation
instead of arriving at even odds:

>>> weighted = ds.space(
...     ds.param("act").categorical("relu", "tanh").prior(weights=[9.0, 1.0]),
...     ds.param("depth").integer(1, 8),
... )
>>> first = [p.config["act"] for p in Optimizer(weighted, seed=0).ask()]
>>> first.count("relu") > first.count("tanh")
True
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

import designspace as ds
from designspace_solvers._profile import Rejection, UnsupportedSpace, require

__all__ = ["KINDS", "MAX_INTEGER_LEVELS", "Optimizer", "Proposal"]

#: The parameter kinds this binding places. Absent are the structural kinds, a
#: flat layout having no room for a subspace, a variant, or a list, along with
#: the program and custom kinds, which carry no coordinate of their own.
KINDS = frozenset({"real", "integer", "bool", "categorical", "ordinal", "subset", "permutation"})

#: How many distinct values an integer parameter may have before it is placed
#: as a continuous coordinate instead of an explicit level set. The integer
#: block holds one entry per level, so a wide range costs the solver a large
#: discrete alphabet for little benefit, while a chart-decoded continuous
#: coordinate snaps to the same grid at constant width.
MAX_INTEGER_LEVELS = 64


def _require_cmaes() -> Any:
    try:
        from cmaes import CatCMAwM
    except ImportError as exc:  # pragma: no cover - exercised by the core install path
        raise ImportError(
            "the CMA-ES binding needs cmaes, which is an optional dependency. "
            "Install it with `pip install designspace-solvers[cmaes]`."
        ) from exc
    return CatCMAwM


@dataclass(frozen=True)
class Proposal:
    """One configuration the optimizer proposed, and the handle to score it.

    Attributes
    ----------
    config : dict[str, Any]
        The proposed configuration, in domain units.
    solution : Any
        The optimizer's own record of the proposal. Pass the proposal back to
        `Optimizer.tell` rather than reading this.
    """

    config: dict[str, Any]
    solution: Any


@dataclass(frozen=True)
class _Slot:
    """Where one parameter lives in the solver's fixed layout."""

    path: str
    kind: ds.TypeKind
    block: str
    start: int
    width: int
    values: tuple[Any, ...]
    chart: ds.Chart | None


def _levels(defn: ds.ParamDef) -> int | None:
    """How many distinct values an integer parameter takes, if that is small.

    A quantized parameter reports nothing, which sends it to the continuous
    block. Enumerating its levels would mean reconstructing the grid the chart
    already holds, and getting that arithmetic wrong produces values off the
    grid that the space then rejects. Decoding through the chart snaps to the
    same grid without reconstructing anything.
    """
    if defn.quantized is not None:
        return None
    chart = defn.chart
    assert chart is not None
    span = int(chart.from_unit(1.0)) - int(chart.from_unit(0.0)) + 1
    return span if span <= MAX_INTEGER_LEVELS else None


def _layout(
    space: ds.Space,
) -> tuple[tuple[_Slot, ...], list[list[float]], list[list[Any]], list[int]]:
    """Assign every parameter a place in the continuous, integer and categorical blocks."""
    slots: list[_Slot] = []
    x_space: list[list[float]] = []
    z_space: list[list[Any]] = []
    c_space: list[int] = []

    for path in space.topological_order:
        defn = space.params[path]
        kind = defn.type_kind
        domain = defn.domain

        if kind == "real" or (kind == "integer" and _levels(defn) is None):
            slots.append(_Slot(path, kind, "x", len(x_space), 1, (), defn.chart))
            x_space.append([0.0, 1.0])
        elif kind == "integer":
            chart = defn.chart
            assert chart is not None
            values = tuple(range(int(chart.from_unit(0.0)), int(chart.from_unit(1.0)) + 1))
            slots.append(_Slot(path, kind, "z", len(z_space), 1, values, None))
            z_space.append(list(values))
        elif kind == "ordinal":
            assert isinstance(domain, ds.OrdinalDomain)
            # An ordinal is ordered, so it belongs in the integer block, where
            # the solver can move along it, rather than the categorical one.
            slots.append(_Slot(path, kind, "z", len(z_space), 1, domain.values, None))
            z_space.append(list(range(len(domain.values))))
        elif kind == "categorical":
            assert isinstance(domain, ds.CategoricalDomain)
            slots.append(_Slot(path, kind, "c", len(c_space), 1, domain.values, None))
            c_space.append(len(domain.values))
        elif kind == "bool":
            slots.append(_Slot(path, kind, "c", len(c_space), 1, (False, True), None))
            c_space.append(2)
        elif kind == "subset":
            assert isinstance(domain, ds.SubsetDomain)
            # One inclusion flag per item, each its own categorical.
            slots.append(
                _Slot(path, kind, "c", len(c_space), len(domain.items), domain.items, None)
            )
            c_space.extend([2] * len(domain.items))
        elif kind == "permutation":
            assert isinstance(domain, ds.PermutationDomain)
            # Random keys: one continuous coordinate per item, read in order.
            # Every draw decodes to a valid permutation.
            width = len(domain.items)
            slots.append(_Slot(path, kind, "x", len(x_space), width, domain.items, None))
            x_space.extend([[0.0, 1.0]] * width)
        else:  # pragma: no cover - `require` rejects these before the layout runs
            raise UnsupportedSpace(
                "the CMA-ES binding",
                [Rejection(path=path, kind=kind, reason="no layout is defined for this kind")],
            )

    return tuple(slots), x_space, z_space, c_space


def _categorical_start(
    space: ds.Space, slots: Sequence[_Slot], c_space: Sequence[int]
) -> np.ndarray[Any, Any] | None:
    """The distribution the categorical block starts from, read off the space.

    The solver holds one categorical distribution per variable and adapts it
    as the run proceeds, so a declared `.prior(weights=...)` has somewhere to
    go: it is that distribution's starting point, normalized to sum to one.
    Weights say where good values are expected to be, which is what an initial
    distribution is for, and leaving them out would start a weighted parameter
    uniform while a real or integer parameter's prior reaches the solver
    through its chart.

    The result is `None` when no categorical parameter declares weights,
    which leaves every row uniform, the solver's own default and what a space
    with no prior means.
    """
    if not c_space:
        return None
    q = np.zeros((len(c_space), max(c_space)))
    for index, width in enumerate(c_space):
        q[index, :width] = 1.0 / width
    declared = False
    for slot in slots:
        if slot.block != "c":
            continue
        prior = space.params[slot.path].prior
        if not isinstance(prior, ds.Weights):
            continue
        declared = True
        if slot.kind == "subset":
            # Subset weights are independent inclusion probabilities, one per
            # item, and each item is its own two-level variable here. Column 1
            # is inclusion, which is what `_decode` reads back.
            for offset, probability in enumerate(prior.values):
                q[slot.start + offset, :2] = (1.0 - probability, probability)
        else:
            # Categorical and bool weights are relative over declared order,
            # which is the order the block already holds them in. There is one
            # per value, so the uniform row is overwritten whole.
            weights = np.asarray(prior.values, dtype=float)
            q[slot.start, : len(weights)] = weights / weights.sum()
    return q if declared else None


def _decode(slots: Sequence[_Slot], solution: Any) -> dict[str, Any]:
    """Read one solution back into a configuration in domain units."""
    config: dict[str, Any] = {}
    for slot in slots:
        if slot.block == "x":
            if slot.kind == "permutation":
                keys = [float(solution.x[slot.start + i]) for i in range(slot.width)]
                config[slot.path] = [
                    item for _, item in sorted(zip(keys, slot.values, strict=True))
                ]
            else:
                assert slot.chart is not None
                config[slot.path] = slot.chart.from_unit(float(solution.x[slot.start]))
        elif slot.block == "z":
            raw = solution.z[slot.start]
            config[slot.path] = slot.values[int(raw)] if slot.kind == "ordinal" else int(raw)
        else:
            onehot = np.asarray(solution.c)
            if slot.kind == "subset":
                config[slot.path] = [
                    item
                    for offset, item in enumerate(slot.values)
                    if bool(onehot[slot.start + offset][1])
                ]
            else:
                config[slot.path] = slot.values[int(np.argmax(onehot[slot.start]))]
    return config


class Optimizer:
    """Drive CMA-ES with margin over a flat design space.

    The optimizer proposes a generation at a time. Each proposal carries a
    configuration in domain units, ready to evaluate, and the handle the
    optimizer needs to learn from the result.

    Parameters
    ----------
    space : designspace.Space
        The space to search. It must be flat: no conditional activity, no
        variable-length list, and no structural or program parameter.
    seed : int or None, optional
        Seed for the optimizer's own draws.
    sigma : float or None, optional
        Initial step size, in unit coordinates. Every continuous parameter is
        placed in `[0, 1]`, so one value is meaningful across a whole space
        regardless of the domains behind it.
    mean : dict[str, Any] or None, optional
        A configuration to start from, which is how a known-good setting warms
        the run up. Only continuous and integer parameters inform the mean.
        The categorical block starts from the space's declared weights, warm
        start or not, since a distribution over categories is not something a
        single configuration determines.

    Raises
    ------
    UnsupportedSpace
        When the space is conditional, has a variable-length list, or holds a
        kind with no place in a flat layout. Every reason is reported at once,
        by path.

    Examples
    --------
    >>> import designspace as ds
    >>> from designspace_solvers.cmaes import Optimizer
    >>> space = ds.space(ds.param("x").real(-5.0, 5.0), ds.param("y").real(-5.0, 5.0))
    >>> optimizer = Optimizer(space, seed=0)
    >>> for _ in range(30):
    ...     proposals = optimizer.ask()
    ...     optimizer.tell([(p, p.config["x"] ** 2 + p.config["y"] ** 2) for p in proposals])
    >>> best = min(optimizer.history, key=lambda pair: pair[1])
    >>> round(best[1], 3) < 1.0
    True

    A conditional space is refused rather than padded, and the refusal names
    the parameter responsible.

    >>> conditional = ds.space(
    ...     ds.param("use").bool(),
    ...     ds.param("level").integer(1, 3).when(ds.param("use")),
    ... )
    >>> Optimizer(conditional)
    Traceback (most recent call last):
        ...
    designspace_solvers._profile.UnsupportedSpace: the CMA-ES binding cannot search this
    space: level (integer): active only under a condition, and this backend has no
    representation for an absent parameter
    """

    def __init__(
        self,
        space: ds.Space,
        *,
        seed: int | None = None,
        sigma: float | None = None,
        mean: dict[str, Any] | None = None,
    ) -> None:
        catcmawm = _require_cmaes()
        require(
            space,
            backend="the CMA-ES binding",
            kinds=KINDS,
            conditional=False,
            variable_length=False,
        )
        self._space = space
        self._slots, x_space, z_space, c_space = _layout(space)
        self.history: list[tuple[dict[str, Any], float]] = []
        self._optimizer = catcmawm(
            x_space=x_space or None,
            z_space=z_space or None,
            c_space=c_space or None,
            seed=seed,
            sigma=sigma,
            mean=None if mean is None else self._mean_vector(mean, len(x_space), len(z_space)),
            cat_param=_categorical_start(space, self._slots, c_space),
        )

    def _mean_vector(self, config: dict[str, Any], n_x: int, n_z: int) -> np.ndarray[Any, Any]:
        """Place a configuration's continuous and integer parts into a mean vector."""
        vector = np.zeros(n_x + n_z)
        vector[:n_x] = 0.5
        for slot in self._slots:
            if slot.path not in config:
                continue
            if slot.block == "x" and slot.kind != "permutation":
                assert slot.chart is not None
                vector[slot.start] = slot.chart.to_unit(config[slot.path])
            elif slot.block == "z":
                value = config[slot.path]
                vector[n_x + slot.start] = (
                    slot.values.index(value) if slot.kind == "ordinal" else float(value)
                )
        return vector

    @property
    def population_size(self) -> int:
        """How many proposals one generation holds.

        Returns
        -------
        int
            The optimizer's population size.
        """
        size: int = self._optimizer.population_size
        return size

    def ask(self) -> list[Proposal]:
        """Propose one generation of configurations.

        Returns
        -------
        list[Proposal]
            One proposal per member of the population, each carrying a
            configuration in domain units.
        """
        return [
            Proposal(config=_decode(self._slots, solution), solution=solution)
            for solution in (self._optimizer.ask() for _ in range(self.population_size))
        ]

    def tell(self, results: Sequence[tuple[Proposal, float]]) -> None:
        """Report the objective value of each proposal in a generation.

        Parameters
        ----------
        results : Sequence[tuple[Proposal, float]]
            Every proposal from one `ask`, paired with its objective value.
            The optimizer minimizes.
        """
        self.history.extend((proposal.config, float(value)) for proposal, value in results)
        self._optimizer.tell([(proposal.solution, float(value)) for proposal, value in results])
