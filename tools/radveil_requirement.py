#!/usr/bin/env python3
"""The radveil version range this extension installs (single source of truth:
``REQUIREMENT`` in RadVeil/RadVeilLib/backend.py).

    python tools/radveil_requirement.py              # print it, e.g. radveil>=0.1,<0.2
    python tools/radveil_requirement.py --latest     # newest radveil on PyPI and whether it is in range
    python tools/radveil_requirement.py --bump-to V  # widen the range to the minor series of V

``--latest`` and ``--bump-to`` need the ``packaging`` package.
"""

import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND = os.path.join(ROOT, "RadVeil", "RadVeilLib", "backend.py")
PATTERN = re.compile(r'^(REQUIREMENT\s*=\s*")([^"]+)(")', re.M)


def get():
    m = PATTERN.search(open(BACKEND, encoding="utf-8").read())
    if not m:
        raise SystemExit(f"REQUIREMENT not found in {BACKEND}")
    return m.group(2)


def set_(requirement):
    text = open(BACKEND, encoding="utf-8").read()
    new, n = PATTERN.subn(lambda m: m.group(1) + requirement + m.group(3), text)
    if n != 1:
        raise SystemExit("could not update REQUIREMENT")
    with open(BACKEND, "w", encoding="utf-8") as f:
        f.write(new)


def range_for(version):
    """``radveil>=X.Y,<X.(Y+1)`` for 0.x (minor = breaking), ``>=X.Y,<X+1`` otherwise."""
    from packaging.version import Version

    v = Version(version)
    if v.major == 0:
        return f"radveil>={v.major}.{v.minor},<{v.major}.{v.minor + 1}"
    return f"radveil>={v.major}.{v.minor},<{v.major + 1}"


def latest_on_pypi():
    from packaging.version import Version

    with urllib.request.urlopen("https://pypi.org/pypi/radveil/json", timeout=30) as r:
        data = json.load(r)
    versions = [Version(v) for v, files in data["releases"].items() if files]
    stable = [v for v in versions if not v.is_prerelease]
    return str(max(stable or versions)) if versions else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--bump-to", metavar="VERSION")
    args = parser.parse_args(argv)

    if args.bump_to:
        new = range_for(args.bump_to)
        old = get()
        if new != old:
            set_(new)
        print(new)
        return 0
    if args.latest:
        from packaging.requirements import Requirement

        latest = latest_on_pypi()
        current = get()
        in_range = latest is not None and Requirement(current).specifier.contains(latest, prereleases=True)
        # Key=value lines, suitable for $GITHUB_OUTPUT.
        print(f"requirement={current}")
        print(f"latest={latest or ''}")
        print(f"in_range={'true' if in_range else 'false'}")
        return 0
    print(get())
    return 0


if __name__ == "__main__":
    sys.exit(main())
