"""Widget wiring checks without Slicer (stubbed Qt/Slicer, mock backend).

They catch Python-level mistakes in the panel logic; the in-Slicer self-test
(RadVeilTest) covers real rendering, layouts and MRML."""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def test_widget_flows_with_stubbed_slicer():
    env = dict(os.environ)
    env.pop("RADVEIL_SLICER_MOCK", None)
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "stubbed_widget_check.py"), os.path.join(HERE, "..", "RadVeil")],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for marker in ("ALL WIDGET CHECKS PASSED", "FEATURE CHECKS PASSED", "INSTALL CHECKS PASSED"):
        assert marker in proc.stdout, proc.stdout + proc.stderr
