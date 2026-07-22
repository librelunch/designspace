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
]


def _write_vector(name: str, space: object) -> None:
    doc = space.to_json()  # type: ignore[attr-defined]
    assert "dropped" not in doc, (
        f"{name}: to_json() carries a 'dropped' manifest — a vector fixture must be "
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

    # Non-corpus demo vectors kept apart from the corpus loop so the corpus
    # vectors stay a clean byte-identity check. Added — never replace a corpus
    # vector. `require_demo` (M7.5), `discourage_demo` (M7.6), `anchor_demo`
    # (M8, DECISIONS.md D-40 — kept out of `sat_solver` to avoid replacing
    # its already-committed vector).
    import _anchor_demo
    import _discourage_demo
    import _require_demo

    _write_vector("require_demo", _require_demo.build_space())
    _write_vector("discourage_demo", _discourage_demo.build_space())
    _write_vector("anchor_demo", _anchor_demo.build_space())


if __name__ == "__main__":
    main()
