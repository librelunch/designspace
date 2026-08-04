"""Prior protocol and built-in prior family markers (API.md, "Charts" /
"Support Types").

`Log`/`Logit`/`Power` are bounds-aware and parameterless-until-resolution:
data-only in M1 (no `.ppf()`) — charts/ (M2) is what interprets them against
a param's bounds to build the actual `Chart`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Prior(Protocol):
    """A distribution you supply yourself, for `.prior()`.

    The built-in families cover the common shapes; this is the escape
    hatch for anything else. Any object with a `ppf` satisfies it, which
    includes a frozen `scipy.stats` distribution as-is, and the library takes
    no distribution-library dependency and needs none.

    Supply `cdf` as well whenever the distribution's support runs past the
    parameter's bounds: the chart is then the truncation
    `ppf(cdf(lo) + u * (cdf(hi) - cdf(lo)))`, and without a `cdf` that case
    is an error rather than a silent clipping of tail mass onto the
    bounds. A `cdf` also makes the resulting chart invertible, which is
    what lets a representation over that parameter `encode` as well as
    `decode`.

    An external prior is opaque, so a space using one is not serializable
    without `on_unserializable="mark"`.

    Examples
    --------
    A triangular prior, written out in full. `ppf` alone is enough here
    because its support is exactly the parameter's domain.

    >>> import math
    >>> class Triangular:
    ...     def __init__(self, lo, hi):
    ...         self.lo, self.hi = lo, hi
    ...
    ...     def ppf(self, q):
    ...         return self.lo + (self.hi - self.lo) * math.sqrt(q)
    >>> s = ds.space(ds.param("x").real(0.0, 1.0).prior(Triangular(0.0, 1.0)))
    >>> round(s.sample_one(seed=0)["x"], 6)
    0.798099

    The mass leans toward the upper end, as a triangular prior should:

    >>> draws = [c["x"] for c in s.sample_dicts(200, seed=0)]
    >>> sum(d > 0.5 for d in draws) > 140
    True
    """

    def ppf(self, q: float) -> float:
        """The quantile function: the value at cumulative probability `q`.

        Required. This is what the chart calls, so it must be monotone
        over `[0, 1]`.

        Parameters
        ----------
        q : float
            A cumulative probability in `[0, 1]`.

        Returns
        -------
        float
            The corresponding value.
        """
        ...


@dataclass(frozen=True)
class Log:
    """A logarithmic prior: equal weight per order of magnitude.

    For parameters spanning decades (learning rates, tolerances,
    timeouts), where uniform sampling would spend nearly all its draws in
    the largest decade. `.log_scale()` is shorthand for this.

    Requires a strictly positive domain.
    """


@dataclass(frozen=True)
class Logit:
    """A logit prior: weight concentrated toward both ends of `(0, 1)`.

    For probabilities and rates, where the interesting behaviour is near 0
    and near 1 rather than in the middle.

    Requires a domain strictly inside `(0, 1)`.
    """


@dataclass(frozen=True)
class Power:
    """A power prior: `u ** p` weighting toward one end of the domain.

    `p > 1` favours the lower end, `p < 1` the upper; `p == 1` is uniform.

    The domain must not straddle zero unless `p` is a positive odd
    integer, since the map would not otherwise be monotone.

    Attributes
    ----------
    p : float
        The exponent.
    """

    p: float


@dataclass(frozen=True)
class Weights:
    """Relative weights over a discrete parameter's values.

    What `.prior(weights=[...])` produces, and what `ParamDef.prior` holds
    for a weighted categorical, ordinal, bool, choice, or subset. Unlike
    an external `Prior` this is fully structural, so it serializes and
    fingerprints like any other declaration.

    Attributes
    ----------
    values : tuple[float, ...]
        One weight per declared value or variant, in declaration order.
        Relative, so they need not sum to 1.
    """

    values: tuple[float, ...]


PriorSpec = Prior | Log | Logit | Power | Weights
"""Any prior a parameter can carry.

The type of `ParamDef.prior`: one of the built-in families (`Log`,
`Logit`, `Power`), a `Weights` payload for a discrete parameter, or a
consumer-supplied `Prior`. `None` there means the default uniform measure.
"""
