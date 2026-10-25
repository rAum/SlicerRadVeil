"""Locating, installing and loading the ``radveil`` Python package.

RadVeil ships as prebuilt abi3 wheels (CPython >= 3.9) for Linux x86_64,
macOS (Intel and Apple Silicon) and Windows x86_64, so it installs into
Slicer's own Python with pip, without a compiler. The extension installs it
on first use (with the user's confirmation), or from a local wheel file for
machines without internet access.

Set the environment variable ``RADVEIL_SLICER_MOCK=1`` (or tick "Use mock
backend" in the module) to run against :mod:`RadVeilLib.mock_radveil`.
"""

import importlib
import os

# Accept bug-fix releases of the API this module was written against.
REQUIREMENT = "radveil>=0.1,<0.2"
PIP_NAME = "radveil"


def mock_requested():
    return os.environ.get("RADVEIL_SLICER_MOCK", "").strip().lower() in ("1", "true", "yes", "on")


def installed_version():
    """Version string of the installed real package, or None."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python < 3.8
        return None
    try:
        return version(PIP_NAME)
    except PackageNotFoundError:
        return None


def is_installed():
    return installed_version() is not None


def load(use_mock=False):
    """Return the module to run: the real ``radveil`` or the mock.

    Raises ImportError if the real package is requested but missing."""
    if use_mock or mock_requested():
        from . import mock_radveil

        return mock_radveil
    module = importlib.import_module("radveil")
    return module


def is_mock(module):
    return bool(getattr(module, "IS_MOCK", False))


def install(wheel_path=None):
    """Install radveil into Slicer's Python with pip (from PyPI, or from a
    local ``.whl`` file). Must run inside Slicer."""
    import slicer

    # A list is passed through to pip as-is (no shell splitting), which keeps
    # paths with spaces and the ">=,<" specifier intact.
    if wheel_path:
        slicer.util.pip_install([os.fspath(wheel_path)])
    else:
        slicer.util.pip_install([REQUIREMENT])
    importlib.invalidate_caches()
    return installed_version()
