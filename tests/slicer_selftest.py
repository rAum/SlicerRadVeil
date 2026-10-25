"""Run the RadVeil module self-test inside 3D Slicer (used by CI).

    Slicer --no-splash --testing --additional-module-paths <staged>/RadVeil \
           --python-script tests/slicer_selftest.py

Environment:
  RADVEIL_TEST_LOG          file that receives the log and a final
                            "RADVEIL-SELFTEST: PASS|FAIL" line (Windows GUI
                            apps have no usable stdout)
  RADVEIL_SLICER_TEST_REAL  "1" to also run the real radveil package on MRHead
  RADVEIL_EXPECT_REAL       "1" to fail if the real package is not importable
"""

import logging
import os
import platform
import sys
import traceback

import slicer

LOG_PATH = os.environ.get("RADVEIL_TEST_LOG")
lines = []


def log(message):
    print(message, flush=True)
    lines.append(str(message))


def finish(ok):
    log(f"RADVEIL-SELFTEST: {'PASS' if ok else 'FAIL'}")
    if LOG_PATH:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    slicer.util.exit(0 if ok else 1)


class _Collect(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.WARNING:
            lines.append(f"[{record.levelname}] {record.getMessage()}")


logging.getLogger().addHandler(_Collect())

ok = False
try:
    log(f"Slicer {slicer.app.applicationVersion} (revision {slicer.app.repositoryRevision}), "
        f"Python {sys.version.split()[0]}, {platform.platform()}")
    if not hasattr(slicer.modules, "radveil"):
        raise RuntimeError("the RadVeil module was not loaded; check --additional-module-paths")

    from RadVeilLib import backend

    version = backend.installed_version()
    log(f"radveil package: {version or 'not installed'}")
    if os.environ.get("RADVEIL_EXPECT_REAL") == "1":
        import radveil  # noqa: F401  (fails loudly if the wheel does not load)

        log(f"radveil import OK: {radveil.__version__}")

    import RadVeil

    test = RadVeil.RadVeilTest()
    test.runTest()
    ok = True
except Exception:
    log(traceback.format_exc())
finally:
    finish(ok)
