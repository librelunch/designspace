"""Chart protocol (API.md, "IR" / "Charts").

Every generative scalar param resolves to a static chart: a monotone map
`[0,1] -> domain`. Concrete implementations (charts/) build these against a
param's envelope bounds at resolution step 6; this module only defines the
shape so that ir/ (which ParamDef.chart is typed against) never has to
import charts/.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import designspace as ds  # noqa: F401


class Chart(Protocol):
    """A monotone map from `[0, 1]` onto a parameter's domain.

    The single idea behind both sampling and solver integration. Declaring
    a prior *is* declaring a chart, so there is no separate "transform"
    concept: drawing a value means drawing a uniform `u` and applying
    `from_unit`, and a solver proposing in unit coordinates gets
    type-appropriate behaviour for free — a log-scaled parameter is
    perturbed multiplicatively, a quantized one snaps to its grid.

    Charts are static: they are built once, at resolution, and never
    depend on a configuration. A parameter with expression bounds gets its
    chart from the bounds' envelope, not from the values of a particular
    draw.

    A chart lives on `ParamDef.chart` — except for a lifted parameter,
    whose chart is on `ListDomain.element_chart`.

    Examples
    --------
    >>> s = ds.space(ds.param("lr").real(1e-4, 1e-1).log_scale())
    >>> chart = s.params["lr"].chart
    >>> round(chart.from_unit(0.0), 6), round(chart.from_unit(1.0), 6)
    (0.0001, 0.1)
    >>> round(chart.from_unit(0.5), 6)
    0.003162
    """

    def from_unit(self, u: float) -> Any:
        """Map a unit coordinate to a value in the domain.

        Parameters
        ----------
        u : float
            A coordinate in `[0, 1]`.

        Returns
        -------
        Any
            The corresponding value. `from_unit(0)` is the domain's lower
            end and `from_unit(1)` its upper.
        """
        ...

    def to_unit(self, value: Any) -> float:
        """Map a value in the domain back to its unit coordinate.

        The inverse of `from_unit`, where one exists. For a chart that
        quantizes — an integer or a grid — many values share a coordinate
        interval, so `from_unit(to_unit(v)) == v` holds while the reverse
        round trip does not.

        Parameters
        ----------
        value : Any
            A value in the parameter's domain.

        Returns
        -------
        float
            The coordinate in `[0, 1]`.
        """
        ...
