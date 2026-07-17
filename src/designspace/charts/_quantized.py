"""Quantized chart (API_v3.md, "Charts" > "Quantization").

Wraps a continuous chart built over the grid's extension
(`charts/_grid.py::GridShape.extension_top`); the emitted value is the
greatest grid point <= the continuous draw.
"""

from __future__ import annotations

from dataclasses import dataclass

from designspace.charts._grid import GridShape, floor_to_grid
from designspace.ir import Chart


@dataclass(frozen=True)
class QuantizedChart:
    base: Chart
    shape: GridShape

    def from_unit(self, u: float) -> float:
        x = self.base.from_unit(u)
        return floor_to_grid(self.shape, x)

    def to_unit(self, value: float) -> float:
        return self.base.to_unit(value)


@dataclass(frozen=True)
class IntegerGridChart:
    """A quantized-real grid whose emitted values are cast to `int`.

    Used for `.integer(...).quantized(...)` — the grid mechanism already
    lands on discrete points; this just narrows the output type.
    """

    quantized: QuantizedChart

    def from_unit(self, u: float) -> int:
        return round(self.quantized.from_unit(u))

    def to_unit(self, value: int) -> float:
        return self.quantized.to_unit(float(value))
