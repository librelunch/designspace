"""One-shot generator for the known-answer digest vectors under
`tests/conformance/vectors/*.json` (PLAN.md.md M7 gate:
"known-answer digest vectors ... for every corpus fixture").

**Not collected by pytest** (leading underscore) and **not called by any
test** — `test_vectors.py` only reads the committed files and fails loudly
if one is missing, never regenerates. Run this by hand, deliberately, only
when the version-bump protocol says a new vector should be *added*
(PLAN.md.md: "bump the shared integer, add — never replace —
known-answer vectors"):

    uv run python tests/conformance/vectors/_generate.py

Confirms every corpus fixture is fully serializable (no `dropped` manifest
entries — i.e. no fixture secretly depends on an opaque external prior)
before writing, so a frozen vector can never silently bake in a mark/drop
artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parents[2] / "corpus"
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
]


def main() -> None:
    sys.path.insert(0, str(CORPUS_DIR))
    import importlib

    for name in FIXTURES:
        space = importlib.import_module(name).build_space()
        doc = space.to_json()
        assert "dropped" not in doc, (
            f"{name}: to_json() carries a 'dropped' manifest — a corpus fixture must be "
            "fully serializable, or it would freeze a mark/drop artifact into the vectors"
        )
        vector = {
            "fingerprint_full": space.fingerprint("full"),
            "fingerprint_sampling": space.fingerprint("sampling"),
            "to_json": doc,
        }
        out_path = VECTORS_DIR / f"{name}.json"
        out_path.write_text(json.dumps(vector, indent=2, sort_keys=True) + "\n")
        print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
