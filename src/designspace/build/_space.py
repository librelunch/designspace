"""Space: the resolved container returned by `ds.space()` (API_v3.md, "Space").

M1 exposes only what flat scalar spaces need; structural operations,
sampling, and the rest of introspection land with their milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from designspace.ir import Condition, Constraint, ParamDef


@dataclass(frozen=True)
class Space:
    params: MappingProxyType[str, ParamDef]
    conditions: tuple[Condition, ...]
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)

    @property
    def n_params(self) -> int:
        return len(self.params)

    @property
    def is_conditional(self) -> bool:
        return any(p.condition is not None for p in self.params.values())
