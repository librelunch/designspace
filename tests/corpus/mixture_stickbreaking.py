"""`mixture_stickbreaking` corpus fixture (PLAN.md M11 corpus table).

Exercises: a genuinely **chosen** representation morphism (API.md, "The
Representation Layer": "stick-breaking ... supplied by a consumer or a
type author" — never core), **mixed genotypes** (one param bridged to
u-space, the rest passed through untouched, since `represent()` given an
explicit rule never falls back to the induced rule for what it misses),
and a **custom-to-u-space bridge**: `weights`' native form is a `k`-length
list of mixture weights summing to 1; its stick-breaking `Encoding`
(`StickBreakingEncoding`, below — never in `src/`, per the milestone's own
"zero chosen encodings in core" gate) targets a `k - 1`-length list of
independent `real(0, 1)` breaking fractions at that same path (D-53: one
source param, one target `ParamDef`, dimensionality unconstrained).

Stick-breaking (GEM) construction: given fractions `v_1..v_{k-1}`,
`w_i = v_i * prod_{j<i}(1 - v_j)`, `w_k = prod_{j<k}(1 - v_j)` — telescopes
to `sum(w) == 1` exactly (up to floating point). The inverse recovers each
`v_i = w_i / (1 - sum(w_1..w_{i-1}))`, well-defined whenever every fraction
is strictly interior to `(0, 1)` (true with probability 1 under continuous
sampling from the induced-uniform target `StickBreakingEncoding.target()`
declares).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import designspace as ds
from designspace import Space
from designspace.ir import CustomDomain, ListDomain, ParamDef, RealDomain


class MixtureWeights:
    """A fixed-`k` mixture-weight vector: `k` non-negative floats summing
    to 1. Native and phenotype coincide (a plain JSON-safe list), matching
    the simplest full-protocol custom types in the corpus (`vi_family`'s
    own topologies)."""

    def __init__(self, k: int) -> None:
        self.k = k

    @property
    def type_key(self) -> str:
        return "mixture_weights"

    def sample(self, rng: Any) -> Any:
        """Generative via the same GEM construction `StickBreakingEncoding`
        bridges to explicitly — this is the type's own baseline generative
        capability (every corpus fixture but `vi_family`'s `FixedTopology`
        has one), independent of any representation."""
        remaining = 1.0
        weights: list[float] = []
        for v in rng.random(self.k - 1).tolist():
            w = v * remaining
            weights.append(w)
            remaining *= 1.0 - v
        weights.append(remaining)
        return weights

    def validate(self, value: Any) -> bool:
        if not isinstance(value, list) or len(value) != self.k:
            return False
        if not all(
            isinstance(w, int | float) and not isinstance(w, bool) and w >= 0 for w in value
        ):
            return False
        return abs(sum(value) - 1.0) < 1e-6

    def to_json(self, value: Any) -> Any:
        return list(value)

    def from_json(self, data: Any) -> Any:
        return list(data)

    def describe(self) -> dict[str, Any]:
        return {"k": self.k}


def mixture_weights_factory(described: dict[str, Any]) -> MixtureWeights:
    return MixtureWeights(**described)


CUSTOM_TYPES: dict[str, Any] = {"mixture_weights": mixture_weights_factory}


class StickBreakingEncoding:
    """The chosen morphism itself — a consumer-authored `Encoding`, never
    shipped by core. `target()` replaces `weights`' `CustomDomain` with a
    `k - 1`-length `real(0, 1)` list at the same path; `decode`/`encode`
    apply the GEM construction and its inverse, element-wise handled
    trivially since both operate on the whole list at once (mirroring how
    `represent/_charts.py::_ChartEncoding` handles a direct scalar lift).
    """

    def __init__(self, k: int) -> None:
        self.k = k

    def target(self, param: ParamDef) -> ParamDef:
        return replace(
            param,
            type_kind="list",
            domain=ListDomain(
                element_kind="real",
                element_domain=RealDomain(0.0, 1.0),
                element_chart=None,
                element_prior=None,
                element_periodic=False,
                element_quantized=None,
                element_default=None,
                count=self.k - 1,
            ),
            prior=None,
            quantized=None,
            chart=None,
            default=None,
        )

    def decode(self, param: ParamDef, value: Any) -> Any:
        remaining = 1.0
        weights: list[float] = []
        for v in value:
            w = v * remaining
            weights.append(w)
            remaining *= 1.0 - v
        weights.append(remaining)
        return weights

    def encode(self, param: ParamDef, value: Any) -> Any:
        remaining = 1.0
        fractions: list[float] = []
        for w in value[:-1]:
            fractions.append(w / remaining if remaining > 0.0 else 0.0)
            remaining -= w
        return fractions

    def measure_preserving(self) -> bool:
        # Not proven -- the honest default (API.md, "Obligations": "declared,
        # never assumed"). The pushforward of k-1 independent uniforms
        # through the GEM map is the well-known symmetric-Dirichlet(1,...,1)
        # measure, not the uniform measure on the simplex's own coordinates.
        return False


def stickbreaking_rule(pd: ParamDef) -> StickBreakingEncoding | None:
    if pd.path != "weights" or not isinstance(pd.domain, CustomDomain):
        return None
    param_type = pd.domain.param_type
    assert isinstance(param_type, MixtureWeights)
    return StickBreakingEncoding(param_type.k)


K_COMPONENTS = 3


def build_space() -> Space:
    return ds.space(
        ds.param("weights").custom(MixtureWeights(K_COMPONENTS)),
        ds.param("means").real(-5.0, 5.0).repeat(K_COMPONENTS),
        ds.param("scale").real(0.1, 2.0).log_scale(),
    )
