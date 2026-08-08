# The commit gates, defined once.
#
# This file is the single definition of every gate. The git hooks, `devenv
# test` and CI all call into it, so a gate changes in one place and every
# caller follows. Nothing here may weaken a gate: no skipped step, no relaxed
# strictness, no broad ignore.

# Show the available recipes.
default:
    @just --list

# The six commit gates. All must pass before a commit.
gates: lint format types test doctest docs

# The fast subset, run on every commit. Seconds rather than minutes.
check: lint format types

lint:
    uv run ruff check

format:
    uv run ruff format --check

types:
    uv run mypy --strict src/

test:
    uv run pytest -q

doctest:
    uv run pytest -q --doctest-modules --doctest-glob='*.md' src docs README.md

docs:
    uv run --extra docs sphinx-build -b html -W docs docs/_build

serve-docs:
    uv run python -m http.server -d docs/_build 8000

# Each exclusion below names the only polars-dependent thing in a file that is
# otherwise entirely core, so ignoring the whole file would drop the rest.

# The suite without the `polars` extra, proving the core install path.
test-core:
    uv run pytest -q \
      --ignore=tests/conformance/test_dataframe.py \
      --ignore=tests/corpus/test_delivery_routes.py \
      --ignore=tests/corpus/test_flat_hpo.py \
      --ignore=tests/corpus/test_memetic_pipeline.py \
      --ignore=tests/unit/test_frame.py \
      --deselect "tests/test_docs_site.py::test_guide_page_executes[10-diagnostics-and-dataframes]" \
      --deselect tests/conformance/test_kind_surface_matrix.py::TestEveryKindSatisfiesEveryLaw::test_dataframe_dtype_matches_the_table \
      --deselect tests/conformance/test_kind_surface_matrix.py::TestEveryKindSatisfiesEveryLaw::test_container_lift_dtype_is_an_array
