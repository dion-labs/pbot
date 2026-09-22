"""Pocket Bot local automation harness."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pocket-bot")
except PackageNotFoundError:
    # Direct source imports without an installed distribution have no release
    # metadata. Avoid reporting an unrelated hard-coded historical version.
    __version__ = "0+unknown"
