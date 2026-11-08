#!/usr/bin/env python3
"""Draw the demo character the converter is shown with: flat shapes, no one else's art.

Drawn at four times the size and shrunk, so the edges come out smooth like a painted picture's.
"""
import math
import sys

from PIL import Image, ImageDraw, ImageFilter

K = 4                                   # supersampling
W, H = 900 * K, 1250 * K
BG = (241, 241, 243)
SKIN = (252, 226, 211)
SKIN_SHADE = (236, 197, 182)
HAIR = (60, 52, 76)
HAIR_LIT = (88, 78, 108)
BROW = (92, 70, 76)
LASH = (44, 36, 52)
IRIS = (98, 150, 208)
IRIS_DEEP = (50, 90, 148)
GLINT = (252, 252, 254)
WHITE = (250, 250, 252)
MOUTH = (178, 104, 106)
SHIRT = (96, 126, 164)
SHIRT_SHADE = (76, 102, 136)
COLLAR = (238, 240, 246)


def ell(d, cx, cy, rx, ry, fill, outline=None, w=0):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill, outline=outline, width=w)


def face_path(cx, cy, rx, ry, chin_w=0.34, grow=1.0, drop=0.0):
    """A head outline: a round cranium that tapers to the chin."""
    pts = []
    for i in range(121):
        t = math.pi * 2 * i / 120
        x, y = math.cos(t), math.sin(t)
        if y > 0:                                    # the lower half narrows toward the chin
            k = 1 - (1 - chin_w) * (y ** 1.55)
            x *= k
            y *= 1.02
        pts.append((cx + x * rx * grow, cy + y * ry * grow + drop))
    return pts


def draw():
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    cx = W // 2
    cy, rx, ry = 430 * K, 196 * K, 238 * K
    chin = cy + ry * 1.02

    # 1. the hair behind the head, and its length down the back
    d.polygon(face_path(cx, cy - 10 * K, rx, ry, chin_w=0.62, grow=1.16), fill=HAIR)
    d.rounded_rectangle([cx - rx * 1.12, cy, cx + rx * 1.12, chin + 250 * K], radius=96 * K, fill=HAIR)

    # 2. shoulders
    d.rounded_rectangle([cx - 336 * K, chin + 74 * K, cx + 336 * K, H + 60 * K], radius=132 * K, fill=SHIRT)
    for s in (-1, 1):
        d.polygon([(cx + s * 336 * K, chin + 280 * K), (cx + s * 336 * K, H), (cx + s * 246 * K, H)], fill=SHIRT_SHADE)

    # 3. neck, then the collar over it
    d.rounded_rectangle([cx - 54 * K, chin - 110 * K, cx + 54 * K, chin + 96 * K], radius=26 * K, fill=SKIN_SHADE)
    d.rounded_rectangle([cx - 47 * K, chin - 110 * K, cx + 47 * K, chin + 74 * K], radius=23 * K, fill=SKIN)
    d.polygon([(cx - 142 * K, chin + 74 * K), (cx, chin + 178 * K), (cx + 142 * K, chin + 74 * K),
               (cx + 110 * K, chin + 56 * K), (cx, chin + 136 * K), (cx - 110 * K, chin + 56 * K)], fill=COLLAR)

    # 4. the face
    d.polygon(face_path(cx, cy, rx, ry), fill=SKIN)
    d.polygon(face_path(cx, cy + 10 * K, rx * 0.97, ry * 0.97), fill=SKIN)

    # 5. eyes and brows
    eye_y, sep = cy + 40 * K, 112 * K
    for s in (-1, 1):
        ex = cx + s * sep
        d.rounded_rectangle([ex - 60 * K, eye_y - 116 * K, ex + 56 * K, eye_y - 97 * K], radius=9 * K, fill=BROW)
        ell(d, ex, eye_y, 54 * K, 43 * K, WHITE)
        ell(d, ex, eye_y + 3 * K, 35 * K, 37 * K, IRIS)
        ell(d, ex, eye_y + 13 * K, 21 * K, 23 * K, IRIS_DEEP)
        ell(d, ex - 13 * K, eye_y - 16 * K, 11 * K, 9 * K, GLINT)
        d.arc([ex - 56 * K, eye_y - 50 * K, ex + 56 * K, eye_y + 44 * K], 184, 356, fill=LASH, width=14 * K)
        ell(d, ex, eye_y, 54 * K, 43 * K, None, outline=LASH, w=5 * K)

    # 6. nose and mouth
    d.line([(cx + 7 * K, chin - 120 * K), (cx - 5 * K, chin - 102 * K)], fill=SKIN_SHADE, width=6 * K)
    d.arc([cx - 33 * K, chin - 96 * K, cx + 33 * K, chin - 46 * K], 18, 162, fill=MOUTH, width=10 * K)

    # 7. the fringe, kept well above the brows
    top = cy - ry
    low = eye_y - 150 * K
    d.chord([cx - rx * 1.06, top - 14 * K, cx + rx * 1.06, low + 40 * K], 180, 360, fill=HAIR)
    for i, (x0, x1, tip) in enumerate(((-196, -96, 86), (-110, -6, 118), (0, 104, 104), (98, 198, 74))):
        d.polygon([(cx + x0 * K, low - 50 * K), (cx + x1 * K, low - 50 * K),
                   (cx + (x1 - 22) * K, low + tip * K * 0.35), (cx + (x0 + 16) * K, low)],
                  fill=HAIR_LIT if i % 2 else HAIR)

    # 8. the locks beside the face
    for s in (-1, 1):
        d.polygon([(cx + s * (rx - 30), cy - 160 * K), (cx + s * (rx + 34), cy - 130 * K),
                   (cx + s * (rx + 16), cy + 230 * K), (cx + s * (rx - 74), cy + 110 * K)], fill=HAIR)

    im = im.filter(ImageFilter.GaussianBlur(1.2)).resize((W // K, H // K), Image.LANCZOS)
    return im


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'demo.png'
    draw().save(out)
    print('wrote', out)
