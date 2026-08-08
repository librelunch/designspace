"""The one-shot generator for the known-answer digest vectors.

The vectors live under `tests/conformance/vectors/*.json`, one per corpus
fixture.

This module is not collected by pytest, its name leading with an underscore,
and no test calls it. `test_vectors.py` reads the committed files and fails
loudly when one is missing, and never regenerates. Run this by hand,
deliberately, only when the version-bump protocol calls for a new vector to
be added rather than an existing one replaced:

    uv run python tests/conformance/vectors/_generate.py

Before writing, it confirms that every corpus fixture is fully
serializable, carrying no `dropped` manifest entries, so that no fixture
secretly depends on an opaque external prior and no frozen vector bakes in a
mark or drop artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
CONF_DIR = Path(__file__).resolve().parents[1]
VECTORS_DIR = Path(__file__).resolve().parent

FIXTURES = [
    "flat_hpo",
    "greenhouse",
    "flow_chemistry",
    "job_shop",
    "sat_solver",
    "wind_farm_grid",
    "delivery_routes",
    "solver_portfolio",
    "memetic_pipeline",
    "firmware_buffers",
    "pump_configurator",
    "compiler_pipeline",
    "vi_family",
    "mixture_stickbreaking",
    "annealing_schedule",
]


def _write_vector(name: str, space: object) -> None:
    doc = space.to_json()  # type: ignore[attr-defined]
    assert "dropped" not in doc, (
        f"{name}: to_json() carries a 'dropped' manifest; a vector fixture must be "
        "fully serializable, or it would freeze a mark/drop artifact into the vectors"
    )
    vector = {
        "fingerprint_full": space.fingerprint("full"),  # type: ignore[attr-defined]
        "fingerprint_sampling": space.fingerprint("sampling"),  # type: ignore[attr-defined]
        "to_json": doc,
    }
    out_path = VECTORS_DIR / f"{name}.json"
    out_path.write_text(json.dumps(vector, indent=2, sort_keys=True) + "\n")
    print(f"wrote {out_path}")


def main() -> None:
    sys.path.insert(0, str(CORPUS_DIR))
    sys.path.insert(0, str(CONF_DIR))
    import importlib

    for name in FIXTURES:
        _write_vector(name, importlib.import_module(name).build_space())

    # Non-corpus demo vectors, kept apart from the corpus loop so that the
    # corpus vectors stay a clean byte-identity check. Each was added rather
    # than replacing a corpus vector: `anchor_demo` is kept out of
    # `sat_solver` for exactly that reason, and `chart_apply_demo` freezes
    # the ChartApply expression codec through an induced representation's
    # target.
    import _anchor_demo
    import _chart_apply_demo
    import _discourage_demo
    import _require_demo

    _write_vector("require_demo", _require_demo.build_space())
    _write_vector("discourage_demo", _discourage_demo.build_space())
    _write_vector("anchor_demo", _anchor_demo.build_space())
    _write_vector("chart_apply_demo", _chart_apply_demo.build_space())


if __name__ == "__main__":
    main()
