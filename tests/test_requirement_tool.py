"""tools/radveil_requirement.py: reading and widening the radveil version range."""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import radveil_requirement as rr  # noqa: E402


def test_reads_the_module_requirement():
    sys.path.insert(0, os.path.join(HERE, "..", "RadVeil"))
    from RadVeilLib import backend as b

    assert rr.get() == b.REQUIREMENT


def test_range_for():
    assert rr.range_for("0.2.0") == "radveil>=0.2,<0.3"
    assert rr.range_for("0.10.3") == "radveil>=0.10,<0.11"
    assert rr.range_for("1.4.2") == "radveil>=1.4,<2"


def test_bump_rewrites_only_the_requirement(tmp_path):
    copy = tmp_path / "backend.py"
    shutil.copy(rr.BACKEND, copy)
    before = copy.read_text()
    original = rr.BACKEND
    rr.BACKEND = str(copy)
    try:
        assert rr.main(["--bump-to", "0.2.1"]) == 0
        assert rr.get() == "radveil>=0.2,<0.3"
    finally:
        rr.BACKEND = original
    after = copy.read_text()
    changed = [(a, b) for a, b in zip(before.splitlines(), after.splitlines()) if a != b]
    assert len(changed) == 1 and changed[0][1] == 'REQUIREMENT = "radveil>=0.2,<0.3"'
