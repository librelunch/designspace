"""Prior protocol and built-in prior family markers (API_v3.md, "Charts" /
"Support Types").

`Log`/`Logit`/`Power` are bounds-aware and parameterless-until-resolution:
data-only in M1 (no `.ppf()`) — charts/ (M2) is what interprets them against
a param's bounds to build the actual `Chart`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Prior(Protocol):
    """External prior: `.ppf()` required, `.cdf()` optional (duck-typed)."""

    def ppf(self, q: float) -> float: ...


@dataclass(frozen=True)
class Log:
    pass


@dataclass(frozen=True)
class Logit:
    pass


@dataclass(frozen=True)
class Power:
    p: float


@dataclass(frozen=True)
class Weights:
    """`.prior(weights=[...])` payload for categorical/ordinal/bool/choice."""

    values: tuple[float, ...]


PriorSpec = Prior | Log | Logit | Power | Weights
