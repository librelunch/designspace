"""sample: the reference sampler (API.md, "Sampling and Generativity");
`sampling_report` (API.md, "Sampling diagnostics")."""

from designspace.sample._diagnostics import sampling_report
from designspace.sample._sample import sample_dicts, sample_flat, sample_one

__all__ = [
    "sample_dicts",
    "sample_flat",
    "sample_one",
    "sampling_report",
]
