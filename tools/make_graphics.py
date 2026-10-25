#!/usr/bin/env python3
"""Generate the extension's icon and README graphics in RadVeil's visual style.

    python tools/make_graphics.py

Writes RadVeil.png and RadVeil/Resources/Icons/RadVeil.png (128 px icon),
docs/images/hero.png (README banner / GitHub social preview, 1280x640) and
docs/images/how-it-works.png. The head renders come from RadVeil's own
figures of 3D Slicer's public MRHead sample (docs/images/radveil/).
Needs Pillow; uses the Inter font when installed.
"""

import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMAGES = os.path.join(ROOT, "docs", "images")
RENDERS = os.path.join(IMAGES, "radveil")

# RadVeil's dark palette (site CSS variables).
GROUND = (12, 15, 18)
SURFACE = (19, 24, 29)
SURFACE2 = (26, 32, 39)
LINE = (36, 45, 54)
LINE_STRONG = (51, 64, 75)
INK = (233, 238, 242)
MUTED = (154, 166, 178)
FAINT = (102, 114, 126)
ACCENT = (79, 209, 189)
MASK = (227, 170, 75)
BRAIN = (96, 165, 250)
SKIN = (226, 196, 168)

FONT_DIRS = ["/usr/share/fonts/opentype/inter", "/Library/Fonts", os.path.expanduser("~/Library/Fonts"),
             "C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu"]


def font(name, size):
    candidates = {
        "display": ["InterDisplay-Bold.otf", "Inter-Bold.otf", "DejaVuSans-Bold.ttf"],
        "semibold": ["Inter-SemiBold.otf", "DejaVuSans-Bold.ttf"],
        "medium": ["Inter-Medium.otf", "DejaVuSans.ttf"],
        "regular": ["Inter-Regular.otf", "DejaVuSans.ttf"],
        "mono": ["DejaVuSansMono.ttf"],
    }[name]
    for d in FONT_DIRS:
        for c in candidates:
            path = os.path.join(d, c)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def vertical_gradient(size, top, bottom):
    w, h = size
    g = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        g.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return g.resize((w, h))


def catmull_rom(points, samples=24, closed=True):
    pts = list(points)
    n = len(pts)
    out = []
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0, p1 = pts[(i - 1) % n], pts[i]
        p2, p3 = pts[(i + 1) % n], pts[(i + 2) % n]
        for s in range(samples):
            t = s / samples
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3)
                for a, b, c, d in zip(p0, p1, p2, p3)
            ))
    return out


# Head in profile, facing right, on a 1024 canvas.
HEAD = [
    (560, 168), (420, 182), (300, 250), (228, 372), (214, 500), (250, 612), (318, 690),
    (338, 760), (336, 1010), (660, 1010), (652, 800), (690, 744), (738, 712), (756, 668),
    (748, 628), (764, 602), (746, 580), (770, 552), (756, 526), (812, 494), (800, 466),
    (742, 380), (748, 330), (720, 246), (650, 190),
]


def icon(size=128):
    S = 1024
    pad = 40
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    card = Image.new("L", (S, S), 0)
    ImageDraw.Draw(card).rounded_rectangle([pad, pad, S - pad, S - pad], radius=210, fill=255)
    bg = vertical_gradient((S, S), SURFACE2, GROUND).convert("RGBA")
    base.paste(bg, (0, 0), card)
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=210, outline=LINE_STRONG + (255,), width=10)

    # Head silhouette, slightly shaded towards the back.
    head_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(head_mask).polygon(catmull_rom(HEAD), fill=255)
    head_mask = ImageChops.multiply(head_mask, card)
    shade = Image.new("RGB", (S, S))
    for x in range(S):
        t = min(max((x - 220) / 560, 0), 1)
        col = tuple(round(a * (0.78 + 0.22 * t)) for a in SKIN)
        ImageDraw.Draw(shade).line([(x, 0), (x, S)], fill=col)
    base.paste(shade, (0, 0), head_mask)

    # The veil: the face region (front of the head) in mask amber.
    veil = Image.new("L", (S, S), 0)
    ImageDraw.Draw(veil).polygon(
        [(560, 300), (900, 300), (900, 760), (600, 760), (585, 640), (560, 470)], fill=255)
    veil = ImageChops.multiply(veil, head_mask)
    amber = Image.new("RGBA", (S, S), MASK + (255,))
    base.paste(amber, (0, 0), veil.point(lambda v: v * 0.94))
    # Scan lines across the veil: the re-attack that verifies the result.
    lines = Image.new("L", (S, S), 0)
    ld = ImageDraw.Draw(lines)
    for y in range(330, 760, 52):
        ld.line([(540, y), (900, y)], fill=255, width=12)
    lines = ImageChops.multiply(lines, veil)
    base.paste(Image.new("RGBA", (S, S), (246, 205, 130, 255)), (0, 0), lines)
    # The veil's inner edge in accent mint (where the anonymized region starts).
    edge = Image.new("L", (S, S), 0)
    ImageDraw.Draw(edge).line([(560, 300), (560, 470), (585, 640), (600, 760)], fill=255, width=22, joint="curve")
    edge = ImageChops.multiply(edge, head_mask)
    base.paste(Image.new("RGBA", (S, S), ACCENT + (255,)), (0, 0), edge)
    return base.resize((size, size), Image.LANCZOS)


def load_render(name):
    return Image.open(os.path.join(RENDERS, name)).convert("RGB")


def rounded(im, radius):
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def card(canvas, im, box, label, color, border):
    x0, y0, x1, y1 = box
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle(box, radius=14, fill=GROUND, outline=border, width=3)
    inner = (x1 - x0 - 16, y1 - y0 - 16)
    scale = min(inner[0] / im.width, inner[1] / im.height)
    shown = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    pos = (x0 + (x1 - x0 - shown.width) // 2, y0 + (y1 - y0 - shown.height) // 2)
    canvas.paste(rounded(shown, 8), pos, rounded(shown, 8))
    f = font("semibold", 17)
    text = " ".join(label.upper())
    tw = d.textlength(text, font=f)
    d.text(((x0 + x1 - tw) / 2, y1 + 16), text, font=f, fill=color)


def hero():
    W, H = 1280, 640
    im = vertical_gradient((W, H), (16, 21, 24), GROUND).convert("RGBA")
    d = ImageDraw.Draw(im)
    # faint grid, as on RadVeil's site
    for x in range(0, W, 40):
        d.line([(x, 0), (x, H)], fill=(18, 23, 27))
    for y in range(0, H, 40):
        d.line([(0, y), (W, y)], fill=(18, 23, 27))

    ic = icon(84)
    im.paste(ic, (72, 92), ic)
    d.text((176, 104), "3D SLICER EXTENSION", font=font("semibold", 19), fill=ACCENT)
    d.text((176, 130), "Utilities  \u2192  RadVeil Defacing", font=font("medium", 18), fill=MUTED)
    d.text((70, 210), "RadVeil", font=font("display", 104), fill=INK)
    d.text((72, 336), "Face and ear anonymization for head MRI and CT,", font=font("medium", 26), fill=INK)
    d.text((72, 370), "verified, then reviewed side by side in Slicer.", font=font("medium", 26), fill=ACCENT)
    bullets = [
        "Linked before/after 3D views at the skin surface",
        "Brain segment, detected landmarks, region preview",
        "Same face, every series of the session",
    ]
    y = 432
    for b in bullets:
        d.rectangle([74, y + 9, 82, y + 17], fill=ACCENT)
        d.text((98, y), b, font=font("regular", 20), fill=MUTED)
        y += 36
    d.text((72, 562), "Extensions Manager  \u2192  search \"RadVeil\"", font=font("mono", 18), fill=FAINT)

    card(im, load_render("site_input.png"), (760, 120, 978, 362), "Original", MUTED, LINE_STRONG)
    card(im, load_render("site_adaptive.png"), (1010, 120, 1228, 362), "Anonymized", MASK, MASK)
    d.text((983, 226), "\u2192", font=font("semibold", 26), fill=ACCENT)
    card(im, load_render("side_ears.png"), (760, 416, 978, 572), "Ears", MASK, LINE_STRONG)
    card(im, load_render("brain.png"), (1010, 416, 1228, 572), "Brain vs region", BRAIN, LINE_STRONG)
    return im.convert("RGB")


def how_it_works():
    W, H = 1600, 560
    im = Image.new("RGB", (W, H), GROUND)
    d = ImageDraw.Draw(im)
    d.text((60, 44), "How RadVeil anonymizes a head scan", font=font("display", 38), fill=INK)
    d.text((60, 96), "It attacks the scan the way a re-identifier would, and accepts the result only "
                     "when that attack fails.", font=font("regular", 21), fill=MUTED)
    steps = [
        ("1", "Find the face", "Render the volume as a 3D portrait\nand run a face detector on it.",
         "site_input.png", ACCENT),
        ("2", "Anonymize", "Smooth, cut or block a skin-deep\nregion; everything else bit-exact.",
         "slices_adaptive.png", MASK),
        ("3", "Verify", "Re-render and re-run the detector.\nEscalate until no face is found.",
         "site_adaptive.png", MASK),
        ("4", "Review in Slicer", "Linked before/after views, brain\nsegment and changed region.",
         "brain.png", BRAIN),
    ]
    cw, gap, x = 340, 40, 60
    for num, title, body, img, color in steps:
        y0 = 160
        d.rounded_rectangle([x, y0, x + cw, y0 + 360], radius=16, fill=SURFACE, outline=LINE, width=2)
        d.ellipse([x + 20, y0 + 20, x + 56, y0 + 56], outline=color, width=3)
        d.text((x + 38, y0 + 38), num, font=font("semibold", 20), fill=color, anchor="mm")
        d.text((x + 70, y0 + 24), title, font=font("semibold", 25), fill=INK)
        thumb = load_render(img)
        tb = (cw - 40, 170)
        s = min(tb[0] / thumb.width, tb[1] / thumb.height)
        thumb = thumb.resize((round(thumb.width * s), round(thumb.height * s)), Image.LANCZOS)
        tx = x + (cw - thumb.width) // 2
        rt = rounded(thumb, 8)
        im.paste(rt, (tx, y0 + 74), rt)
        d.multiline_text((x + 22, y0 + 266), body, font=font("regular", 19), fill=MUTED, spacing=8)
        if num != "4":
            ax = x + cw + gap / 2
            d.text((ax, y0 + 160), "\u2192", font=font("semibold", 30), fill=FAINT, anchor="mm")
        x += cw + gap
    return im


def main():
    os.makedirs(IMAGES, exist_ok=True)
    ic = icon(128)
    for path in (os.path.join(ROOT, "RadVeil.png"), os.path.join(ROOT, "RadVeil", "Resources", "Icons", "RadVeil.png")):
        ic.save(path, optimize=True)
    hero().save(os.path.join(IMAGES, "hero.png"), optimize=True)
    how_it_works().save(os.path.join(IMAGES, "how-it-works.png"), optimize=True)
    icon(512).save(os.path.join(IMAGES, "icon-512.png"), optimize=True)
    print("written: RadVeil.png, docs/images/{hero,how-it-works,icon-512}.png")


if __name__ == "__main__":
    main()
