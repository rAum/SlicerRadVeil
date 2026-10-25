"""The extension package must contain every file the module needs."""

import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import stage_module  # noqa: E402


def test_cmake_lists_match_module_files():
    assert stage_module.check() == []


def test_stage_and_zip(tmp_path):
    out = tmp_path / "stage"
    zpath = str(tmp_path / "module.zip")
    target = stage_module.stage(str(out), zpath)
    for rel in stage_module.listed_files():
        assert os.path.isfile(os.path.join(target, rel)), rel
    names = zipfile.ZipFile(zpath).namelist()
    assert "RadVeil/RadVeil.py" in names and "README.md" in names and "LICENSE" in names


def test_index_entry_and_cmake_agree():
    import json

    entry = json.load(open(os.path.join(HERE, "..", "RadVeil.json")))
    cmake = open(os.path.join(HERE, "..", "CMakeLists.txt"), encoding="utf-8").read()
    assert entry["category"] in cmake
    homepage = re.search(r'EXTENSION_HOMEPAGE "([^"]+)"', cmake).group(1)
    assert entry["scm_url"].removesuffix(".git").lower() == homepage.lower()
    assert entry["scm_revision"] == "release"  # users get tagged releases only
