from importlib.metadata import version

import designspace


def test_version_matches_the_distribution() -> None:
    """`__version__` and the distribution's own version are one fact.

    The number is written twice, in `pyproject.toml` and beside the exports,
    and nothing at runtime reads one from the other. This is what stops the
    two from drifting: a release that bumps one and forgets the other fails
    here rather than shipping a package whose two answers disagree.
    """
    assert designspace.__version__ == version("designspace")
