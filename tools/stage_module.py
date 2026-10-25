#!/usr/bin/env python3
"""Stage the RadVeil module exactly as the Slicer extension package ships it.

The Slicer factory packages only the files listed in RadVeil/CMakeLists.txt
(MODULE_PYTHON_SCRIPTS and MODULE_PYTHON_RESOURCES). A file that exists in
the repository but is missing from those lists works when the module is run
from source and is silently absent for everyone who installs the extension.
Testing the staged copy catches that.

    python tools/stage_module.py --check            # verify lists match the tree
    python tools/stage_module.py OUT_DIR            # copy listed files to OUT_DIR/RadVeil
    python tools/stage_module.py OUT_DIR --zip Z    # ...and also write a zip archive
"""

import argparse
import os
import re
import shutil
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODULE = "RadVeil"
MODULE_DIR = os.path.join(ROOT, MODULE)
SHIPPED_EXTENSIONS = (".py", ".png", ".svg", ".ui", ".json", ".txt")


def listed_files(cmake_path=os.path.join(MODULE_DIR, "CMakeLists.txt")):
    """Relative paths listed in MODULE_PYTHON_SCRIPTS / MODULE_PYTHON_RESOURCES."""
    text = open(cmake_path, encoding="utf-8").read()
    text = re.sub(r"#[^\n]*", "", text)
    files = []
    for var in ("MODULE_PYTHON_SCRIPTS", "MODULE_PYTHON_RESOURCES"):
        m = re.search(r"set\(\s*" + var + r"\s+(.*?)\)", text, re.S)
        if not m:
            raise ValueError(f"{var} not found in {cmake_path}")
        for token in m.group(1).split():
            files.append(token.replace("${MODULE_NAME}", MODULE))
    return files


def files_on_disk():
    """Files in the module folder that a user would need at runtime."""
    found = []
    for dirpath, dirnames, filenames in os.walk(MODULE_DIR):
        dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
        for name in filenames:
            if name == "CMakeLists.txt" or not name.endswith(SHIPPED_EXTENSIONS):
                continue
            found.append(os.path.relpath(os.path.join(dirpath, name), MODULE_DIR).replace(os.sep, "/"))
    return found


def check():
    """Return a list of problems (empty when the CMake lists match the tree)."""
    listed = listed_files()
    on_disk = set(files_on_disk())
    problems = [f"listed in CMakeLists.txt but missing: {f}" for f in listed if f not in on_disk]
    problems += [
        f"not listed in CMakeLists.txt (would be missing from the extension package): {f}"
        for f in sorted(on_disk - set(listed))
    ]
    return problems


def stage(out_dir, zip_path=None):
    problems = check()
    if problems:
        raise SystemExit("\n".join(problems))
    target = os.path.join(out_dir, MODULE)
    if os.path.exists(target):
        shutil.rmtree(target)
    for rel in listed_files():
        dest = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(MODULE_DIR, rel), dest)
    for extra in ("README.md", "LICENSE", "NOTICE"):
        shutil.copy2(os.path.join(ROOT, extra), os.path.join(out_dir, extra))
    if zip_path:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, _, filenames in os.walk(out_dir):
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    if os.path.abspath(full) == os.path.abspath(zip_path):
                        continue
                    z.write(full, os.path.relpath(full, out_dir))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", nargs="?")
    parser.add_argument("--check", action="store_true", help="only verify the CMake lists")
    parser.add_argument("--zip", help="also write the staged folder to this zip file")
    args = parser.parse_args(argv)
    if args.check or not args.out_dir:
        problems = check()
        for p in problems:
            print(p, file=sys.stderr)
        print("CMakeLists.txt matches the module files." if not problems else "Packaging check FAILED.")
        return 1 if problems else 0
    print(stage(args.out_dir, args.zip))
    return 0


if __name__ == "__main__":
    sys.exit(main())
