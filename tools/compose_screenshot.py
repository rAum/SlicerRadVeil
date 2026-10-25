#!/usr/bin/env python3
"""Combine the captures from tools/make_screenshots.py into one screenshot.

    python tools/compose_screenshot.py Screenshots/          # -> Screenshots/RadVeil.png

The module panel goes on the left, the comparison layout on the right, both
scaled to the same height, as in a Slicer window. Needs Pillow.
"""

import os
import sys

from PIL import Image


def compose(folder, height=900):
    panel = Image.open(os.path.join(folder, "panel.png")).convert("RGB")
    layout = Image.open(os.path.join(folder, "layout.png")).convert("RGB")

    def scaled(im):
        return im.resize((round(im.width * height / im.height), height), Image.LANCZOS)

    panel, layout = scaled(panel), scaled(layout)
    out = Image.new("RGB", (panel.width + layout.width, height), (32, 32, 32))
    out.paste(panel, (0, 0))
    out.paste(layout, (panel.width, 0))
    path = os.path.join(folder, "RadVeil.png")
    out.save(path, optimize=True)
    return path


if __name__ == "__main__":
    print(compose(sys.argv[1] if len(sys.argv) > 1 else "Screenshots"))
