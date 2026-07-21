"""Chart protocol (API.md, "IR" / "Charts").

Every generative scalar param resolves to a static chart: a monotone map
`[0,1] -> domain`. Concrete implementations (charts/) build these against a
param's envelope bounds at resolution step 6; this module only defines the
shape so that ir/ (which ParamDef.chart is typed against) never has to
import charts/.
"""

from __future__ import annotations

from typing import Any, Protocol


class Chart(Protocol):
    def from_unit(self, u: float) -> Any: ...
    def to_unit(self, value: Any) -> float: ...
