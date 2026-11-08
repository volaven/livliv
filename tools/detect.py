"""Find the background, the canvas and the character's anchors in a flat picture."""
import os

import numpy as np
from PIL import Image

import imgkit as K


# ------------------------------------------------------------ background
def cut_background(im, tol=22, soft=64):
    """RGBA uint8 array with a flat background turned transparent (kept as is when the file has alpha)."""
    rgba = np.asarray(im.convert('RGBA'), np.float32).copy()
    if (rgba[..., 3] < 250).mean() > 0.005:
        return rgba, False
    rgb = rgba[..., :3]
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.abs(rgb - bg).max(2)
    near = dist <= tol
    lab, n = K.label(near)
    if not n:
        return rgba, False
    edge = set(lab[0].tolist()) | set(lab[-1].tolist()) | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    edge.discard(0)
    if not edge:
        return rgba, False
    core = np.isin(lab, list(edge))
    if core.mean() < 0.02:                       # not a flat backdrop after all
        return rgba, False
    band = K.dilate(core, 3) & ~core             # the anti-aliased rim
    a = np.where(core, 0.0, 1.0)
    a = np.where(band, np.clip((dist - tol) / max(soft - tol, 1), 0, 1), a)
    rgba[..., :3] = K.unpremul_edge(rgb, a, bg)
    rgba[..., 3] = a * 255
    return rgba, True


def fit_canvas(rgba, max_side=1536, margin=0.045):
    """Give the drawing room to turn in, then scale it so no side passes max_side."""
    a = rgba[..., 3]
    ys, xs = np.nonzero(a > 8)
    if not len(ys):
        raise SystemExit('convert: the picture is empty')
    y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
    h, w = a.shape
    cw, ch = x1 - x0, y1 - y0
    need = int(round(margin * max(cw, ch)))
    pad = [max(0, need - x0), max(0, need - (w - x1)), max(0, need - y0), 0]   # l, r, t, b (feet may sit on the edge)
    if y1 >= h - 2:
        pad[3] = 0
    else:
        pad[3] = max(0, need - (h - y1))
    if any(pad):
        out = np.zeros((h + pad[2] + pad[3], w + pad[0] + pad[1], 4), np.float32)
        out[pad[2]:pad[2] + h, pad[0]:pad[0] + w] = rgba
        rgba = out
    H, W = rgba.shape[:2]
    s = min(1.0, max_side / max(H, W))
    if s < 1.0:
        im = K.to_image(rgba).resize((max(16, int(round(W * s))), max(16, int(round(H * s)))), Image.LANCZOS)
        rgba = np.asarray(im, np.float32).copy()
    # an even canvas keeps the lattice tidy
    H, W = rgba.shape[:2]
    if H % 2 or W % 2:
        out = np.zeros((H + H % 2, W + W % 2, 4), np.float32)
        out[:H, :W] = rgba
        rgba = out
    return rgba


# --------------------------------------------------------------- anchors
def _face_component(rgb, a, W, H):
    """The topmost sizeable patch of skin: the face, with the neck and whatever else it runs into.

    Returns the skin as drawn (eyes and mouth are still holes in it), the same with the holes filled
    in (for measuring widths) and the component's box.
    """
    skin = K.skin_mask(rgb, a)
    bs, lab = K.blobs(skin)
    if not bs:
        return None, None, None
    floor = max(0.0008 * W * H, 0.15 * bs[0]['area'])
    cand = [b for b in bs if b['area'] >= floor and b['box'][1] < 0.6 * H]
    if not cand:
        cand = [bs[0]]
    face = min(cand, key=lambda b: (b['box'][1], -b['area']))
    raw = lab == face['label']
    return raw, K.fill_holes(raw), face


CHIN_FLARE = 1.5      # the profile growing this much past its low point: the chest, stop there
CHIN_NECK = 1.10      # the chin: the first row down to this much of the neck's own width
CHIN_FLOOR = 0.40     # ... and never wider than this much of the face's widest row
CHIN_REACH = 1.8      # and the chin is never further below the forehead than this, in face widths


def _chin_row(filled, box):
    """Where the jaw gives way to the neck: the face tapers to the neck's width and stays there."""
    x0, y0, x1, y1 = box
    H = filled.shape[0]
    rows = filled.sum(1).astype(np.float64)
    span = max(8, y1 - y0)
    k = max(3, int(span * 0.035)) | 1
    sm = np.convolve(rows, np.ones(k) / k, mode='same')
    look = slice(y0, min(y0 + max(6, int(0.55 * span)), H))
    wide = y0 + int(np.argmax(sm[look]))
    peak = max(1.0, sm[wide])
    neck_w, stop = peak, min(y1, H - 1)
    for y in range(wide, min(y1 + 1, H)):
        if sm[y] < neck_w:
            neck_w = sm[y]
        elif sm[y] > CHIN_FLARE * neck_w:          # the shoulders or the chest: the neck is behind us
            stop = y
            break
    want = max(CHIN_NECK * neck_w, CHIN_FLOOR * peak)
    reach = int(y0 + CHIN_REACH * max(8, x1 - x0))        # a face is never this much taller than it is wide
    for y in range(wide, min(stop + 1, H)):
        if sm[y] <= want:
            return y, peak
    return min(stop, reach), peak


# how a head sits around the eyes, measured on the 21 featured characters (tools/calibrate.py)
EYE_RX = 0.955        # head.rx / the distance between the eye centres
EYE_RY = 1.210        # head.ry / that distance
EYE_CY = -0.270       # head.cy, from the eyes' line, in that distance
EYE_TRUST = 0.33      # keep the chin the drawing shows while it is this close to the one the eyes imply
EYE_BOX_W = 0.433     # the eye mark's own size, in the distance between the eye centres
EYE_BOX_H = 0.289
MOUTH_DX = 0.028      # where the mouth sits: from the head's middle, and below the eyes' line
MOUTH_DY = 0.485
MOUTH_HOLD = 0.18     # a mouth found further than this from there is pulled back to it
HAIR_ABOVE = 0.59     # hair standing above the hairline, in head radii (median of the featured characters)
MOUTH_DARK = float(os.environ.get('LIVLIV_MOUTH_DARK', 0.94))   # a mouth is this much darker than the skin round it
BROW_DARK = float(os.environ.get('LIVLIV_BROW_DARK', 0.86))


def _dark(rgb, a, box, factor, pct=72):
    """Pixels inside `box` clearly darker than the skin that fills most of that same box.

    The level is taken from the box itself, so a shaded face, a bright one and a dark one all work.
    """
    x0, y0, x1, y1 = [max(0, int(v)) for v in box]
    _, _, V = K.hsv(rgb)
    m = np.zeros(V.shape, bool)
    m[y0:y1, x0:x1] = True
    m &= a > 110
    if m.sum() < 32:
        return np.zeros(V.shape, bool)
    return m & (V < factor * float(np.percentile(V[m], pct)))


def _head_from_eyes(pair):
    c = [((b['box'][0] + b['box'][2]) / 2, (b['box'][1] + b['box'][3]) / 2) for b in pair]
    sep = max(8.0, float(np.hypot(c[0][0] - c[1][0], c[0][1] - c[1][1])))
    ecx, ecy = (c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2
    return dict(sep=sep, ecx=ecx, ecy=ecy, cx=ecx, cy=ecy + EYE_CY * sep,
                rx=EYE_RX * sep, ry=EYE_RY * sep)


def _pair_fit(pair, opaque, top_y, bottom_y, chin_hint=None):
    """How much a candidate pair looks like a real pair of eyes on this drawing."""
    H, W = opaque.shape
    g = _head_from_eyes(pair)
    cx, cy, rx, ry = g['cx'], g['cy'], g['rx'], g['ry']
    if cy - ry < -0.4 * ry or cy + ry > H + 0.2 * ry or cx - rx < -0.2 * rx or cx + rx > W + 0.2 * rx:
        return -1.0
    yy = np.arange(H)[:, None]; xx = np.arange(W)[None, :]
    ell = ((xx - cx) / max(rx, 1)) ** 2 + ((yy - cy) / max(ry, 1)) ** 2 <= 1
    if ell.sum() < 16:
        return -1.0
    solid = float((opaque & ell).sum()) / float(ell.sum())
    # how much hair stands above the hairline, in head radii: 0.59 across the featured characters,
    # 0.40 to 0.80 for nine in ten of them. A pair too wide apart implies too big a head and lands
    # near 0; too close together, far above 1. Both are penalised.
    above = ((cy - ry) - top_y) / max(ry, 1)
    if not (-0.5 <= above <= 2.5):
        return -1.0
    pen = 0.62 * min(1.0, (abs(above - HAIR_ABOVE) / 0.45) ** 2)
    row = int(np.clip(g['ecy'], 0, H - 1))
    cols = np.nonzero(opaque[row])[0]
    wide = (cols.max() - cols.min() + 1) / max(2 * rx, 1) if len(cols) > 2 else 3.0
    pen += 0.0 if wide <= 2.3 else min(1.0, (wide - 2.3) / 2.0)
    if chin_hint is not None:
        pen += 0.45 * min(1.0, abs((cy + ry) - chin_hint) / max(0.9 * ry, 1))
    return solid - 0.9 * pen


def _eye_pair(rgb, a, W, H, top_y, bottom_y, gate=None, grow=1):
    """The eyes found on their own: two matching marks, high on the figure, that are neither skin
    nor background -- an iris with its lashes. Found without knowing where the face is, because
    pale hair and cream clothes are hard to tell from skin but nothing else looks like a pair of
    eyes."""
    _, S, V = K.hsv(rgb)
    m = (a > 128) & ((S > 0.25) | (V < 0.50))
    if gate is not None:
        m = m & gate
    r = max(1, int(round(min(W, H) * 0.0022))) * grow
    m = K.erode(m, r)
    bs, _ = K.blobs(m)
    canvas = float(W * H)
    span = max(32, bottom_y - top_y)
    cand = []
    for b in bs:
        x0, y0, x1, y1 = b['box']
        w, h = x1 - x0, y1 - y0
        if not (0.00006 * canvas <= b['area'] <= 0.012 * canvas) or w < 5 or h < 5:
            continue
        if not (0.45 <= w / h <= 3.4) or b['area'] < 0.34 * w * h:
            continue
        if b['cy'] > top_y + 0.62 * span:
            continue
        cand.append(dict(b, box=(x0 - r, y0 - r, x1 + r, y1 + r), w=w + 2 * r, h=h + 2 * r))
    out = []
    for i, A in enumerate(cand):
        for B in cand[i + 1:]:
            L, R = (A, B) if A['cx'] <= B['cx'] else (B, A)
            dy, hm = abs(L['cy'] - R['cy']), max(L['h'], R['h'])
            if dy > 0.55 * hm:
                continue
            ar = min(L['area'], R['area']) / max(L['area'], R['area'])
            hr = min(L['h'], R['h']) / max(L['h'], R['h'])
            if ar < 0.40 or hr < 0.55:
                continue
            d, mw = R['cx'] - L['cx'], (L['w'] + R['w']) / 2
            if not (0.85 * mw <= d <= 3.4 * mw):
                continue
            score = (L['area'] + R['area']) * ar * hr * (1 - dy / (0.6 * hm))
            out.append((score, [L, R]))
    out.sort(key=lambda t: -t[0])
    top = out[:8]
    return [p for _, p in top], [sc / top[0][0] for sc, _ in top] if top else []


def _find_eyes(skin, face_box):
    """The eyes as the two big openings the drawing leaves in the face."""
    fx0, fy0, fx1, fy1 = face_box
    fw, fh = fx1 - fx0, max(8, fy1 - fy0)
    pad = max(2, int(0.02 * fh))
    filled = K.fill_holes(skin) | (K.span_fill(skin) & K.dilate(skin, pad))
    bs, _ = K.blobs(filled & ~skin)
    area = max(1, skin.sum())
    fcx = (fx0 + fx1) / 2
    cand = [b for b in bs if 0.0015 * area <= b['area'] <= 0.22 * area
            and b['box'][0] >= fx0 - 2 and b['box'][2] <= fx1 + 2
            and fy0 + 0.10 * fh < b['cy'] < fy0 + 0.78 * fh]
    out = []
    for i, A in enumerate(cand):
        for B in cand[i + 1:]:
            if (A['cx'] - fcx) * (B['cx'] - fcx) >= 0:
                continue
            if abs(A['cy'] - B['cy']) > 0.13 * fh:
                continue
            if min(A['area'], B['area']) < 0.3 * max(A['area'], B['area']):
                continue
            out.append((A['area'] + B['area'], sorted([A, B], key=lambda b: b['cx'])))
    out.sort(key=lambda t: -t[0])
    top = out[:4]
    return [p for _, p in top], [sc / top[0][0] for sc, _ in top] if top else []


def _guess_eyes(face_box):
    fx0, fy0, fx1, fy1 = face_box
    fw, fh = fx1 - fx0, fy1 - fy0
    ew, eh, ey = 0.27 * fw, 0.17 * fh, fy0 + 0.46 * fh
    mk = lambda cx: {'box': (int(cx - ew / 2), int(ey - eh / 2), int(cx + ew / 2), int(ey + eh / 2)),
                     'cx': cx, 'cy': ey, 'area': 0, 'guessed': True}
    return [mk((fx0 + fx1) / 2 - 0.26 * fw), mk((fx0 + fx1) / 2 + 0.26 * fw)]


def _find_brows(rgb, a, eyes, face_box):
    fx0, fy0, fx1, fy1 = face_box
    out = []
    for e in eyes:
        ex0, ey0, ex1, ey1 = e['box']
        ew, eh = ex1 - ex0, max(4, ey1 - ey0)
        box = (ex0 - 0.30 * ew, max(fy0 - 0.2 * eh, ey0 - 2.0 * eh), ex1 + 0.30 * ew, ey0 - 0.02 * eh)
        if box[3] - box[1] < 3:
            out.append(None); continue
        bs, _ = K.blobs(_dark(rgb, a, box, BROW_DARK))
        pick = None
        for b in bs:
            x0, y0, x1, y1 = b['box']
            w, h = x1 - x0, max(1, y1 - y0)
            if w < 0.35 * ew or w < 1.4 * h or h > 0.9 * eh:
                continue
            score = b['area'] * (1.0 + 0.4 * w / max(ew, 1))
            if pick is None or score > pick[0]:
                pick = (score, b)
        out.append(pick[1] if pick else None)
    return [list(b['box']) for b in out] if all(out) else []


def _find_mouth(rgb, a, eyes, face_box, chin):
    """The mouth: a small dark mark low on the face, near its middle."""
    fx0, fy0, fx1, fy1 = face_box
    fw, fh = fx1 - fx0, max(8, fy1 - fy0)
    fcx = (fx0 + fx1) / 2
    eye_bot = max(e['box'][3] for e in eyes)
    span = max(8.0, chin - eye_bot)
    lo, hi = eye_bot + 0.28 * span, chin + 0.03 * span
    want = eye_bot + 0.62 * span                               # where a mouth usually sits
    bs, _ = K.blobs(_dark(rgb, a, (fcx - 0.30 * fw, lo, fcx + 0.30 * fw, hi), MOUTH_DARK))
    pick = None
    for b in bs:
        x0, y0, x1, y1 = b['box']
        w, h = x1 - x0, max(1, y1 - y0)
        if not (0.05 * fw <= w <= 0.50 * fw) or h > 0.17 * fh or w < 0.85 * h:
            continue
        if abs(b['cx'] - fcx) > 0.17 * fw:
            continue
        score = b['area'] * float(np.exp(-(((b['cy'] - want) / (0.34 * span)) ** 2))) \
            * (1.0 - 0.5 * abs(b['cx'] - fcx) / (0.17 * fw))
        if pick is None or score > pick[0]:
            pick = (score, b)
    if pick:
        return list(pick[1]['box']), False
    mw, mh = 0.20 * fw, 0.055 * fh
    return [int(fcx - mw / 2), int(want - mh / 2), int(fcx + mw / 2), int(want + mh / 2)], True


def detect(rgba):
    """Anchors and feature boxes, all in canvas pixels.

    Two passes: the silhouette says roughly where the face is, the eyes found inside it then say
    where the head really sits -- a head's size and centre follow the distance between the eyes far
    more closely than they follow the outline, which hair and collars pull about.
    """
    H, W = rgba.shape[:2]
    rgb, a = rgba[..., :3], rgba[..., 3]
    opaque = a > 32
    ys, xs = np.nonzero(opaque)
    top_y, bottom_y = int(ys.min()), int(ys.max())
    guessed = []

    comp, filled, info = _face_component(rgb, a, W, H)
    if comp is None:                                        # no skin at all: go by the outline
        guessed.append('face')
        hx = np.nonzero(opaque.any(0))[0]
        fx0, fx1 = int(hx.min()), int(hx.max()) + 1
        chin = top_y + 0.19 * (bottom_y - top_y)
        fy0 = int(top_y + 0.30 * (chin - top_y))
        comp = np.zeros_like(opaque); comp[fy0:int(chin), fx0:fx1] = True
        filled = comp
    else:
        chin, _ = _chin_row(filled, info['box'])
        fy0 = info['box'][1]
        sol = filled.copy(); sol[int(chin):] = False
        fys, fxs = np.nonzero(sol)
        if len(fys):
            fx0, fx1, fy0 = int(fxs.min()), int(fxs.max()) + 1, int(fys.min())
        else:
            fx0, fx1 = info['box'][0], info['box'][2]

    face_skin = comp.copy(); face_skin[int(chin + 0.05 * (chin - fy0)):] = False
    gate = None
    if comp is not None and comp.any():
        gate = K.dilate(K.span_fill(comp) | comp, max(2, int(0.004 * min(W, H))))
    pairs, rel = [], []
    for g in (None, gate):
        for grow in (1, 2):
            if g is None and grow == 2:
                continue
            ps, rs = _eye_pair(rgb, a, W, H, top_y, bottom_y, g, grow)
            pairs += ps; rel += list(rs)
    hp, hrel = _find_eyes(face_skin, (fx0, fy0, fx1, chin))
    pairs, rel = pairs + hp, rel + list(hrel)
    hint = chin if abs(chin - fy0) < 2.2 * max(8, fx1 - fx0) else None
    eyes, best = None, -9.0
    for pair, r in zip(pairs, rel):
        v = _pair_fit(pair, opaque, top_y, bottom_y, hint) + 0.18 * r
        if v > best:
            eyes, best = pair, v
    if best < 0.25:
        eyes = None

    if eyes:                                                # the eyes rule: redo the head around them
        c = [((b['box'][0] + b['box'][2]) / 2, (b['box'][1] + b['box'][3]) / 2) for b in eyes]
        sep = max(8.0, float(np.hypot(c[0][0] - c[1][0], c[0][1] - c[1][1])))
        ecx, ecy = (c[0][0] + c[1][0]) / 2, (c[0][1] + c[1][1]) / 2
        cx, rx, ry = ecx, EYE_RX * sep, EYE_RY * sep
        cy = ecy + EYE_CY * sep
        chin_e = cy + ry
        if abs(chin - chin_e) > EYE_TRUST * sep:
            chin = chin_e
        else:
            cy = chin - ry
        hair_root = cy - ry
    else:
        guessed.append('eyes')
        eyes = _guess_eyes((fx0, fy0, fx1, chin))
        raw_h = max(8, chin - fy0)
        hair_root = max(float(top_y), fy0 - 0.345 * raw_h)
        ry = max(8.0, (chin - hair_root) / 2)
        cy, cx, rx = chin - ry, (fx0 + fx1) / 2, max(8.0, (fx1 - fx0) / 2)

    # the eye marks take the size the featured characters have, around the centres found here: a
    # mark found small or lopsided would otherwise cut a lopsided pair of layers
    if len(eyes) == 2:
        ec = [((e['box'][0] + e['box'][2]) / 2, (e['box'][1] + e['box'][3]) / 2) for e in eyes]
        sep = max(8.0, float(np.hypot(ec[0][0] - ec[1][0], ec[0][1] - ec[1][1])))
        bw, bh = EYE_BOX_W * sep / 2, EYE_BOX_H * sep / 2
        eyes = [{'box': (int(round(x - bw)), int(round(y - bh)), int(round(x + bw)), int(round(y + bh))),
                 'cx': x, 'cy': y, 'area': e.get('area', 0)} for (x, y), e in zip(ec, eyes)]
        ecy = (ec[0][1] + ec[1][1]) / 2
    else:
        sep = max(8.0, rx / EYE_RX)
        ecy = float(np.mean([(e['box'][1] + e['box'][3]) / 2 for e in eyes]))

    chin = float(np.clip(chin, top_y + 4, H - 2))
    hair_root = float(np.clip(hair_root, 0, chin - 8))
    face_box = [float(max(0, cx - rx)), float(max(0, min(fy0, cy - 0.42 * ry))),
                float(min(W, cx + rx)), float(min(H, chin + 0.07 * (chin - fy0)))]

    brows = _find_brows(rgb, a, eyes, (face_box[0], face_box[1], face_box[2], chin))
    if not brows:
        guessed.append('brows')
    mouth, mguess = _find_mouth(rgb, a, eyes, (face_box[0], face_box[1], face_box[2], chin), chin)
    if mguess:
        guessed.append('mouth')

    chest_cy = min(H - 2.0, chin + 1.95 * ry)
    row = int(np.clip(chest_cy, 0, H - 1))
    cols = np.nonzero(opaque[row])[0]
    if len(cols) > 4:
        chest_rx = float((cols.max() - cols.min()) / 2 * 1.08)
        chest_cx = float((cols.max() + cols.min()) / 2)
    else:
        chest_rx, chest_cx = rx * 1.7, cx
    return {
        'canvas': [W, H],
        'top_y': top_y, 'bottom_y': bottom_y, 'neck_y': round(float(chin), 1),
        'hair_root_y': round(float(hair_root), 1),
        'head': {'cx': round(float(cx), 1), 'cy': round(float(cy), 1),
                 'rx': round(float(rx), 1), 'ry': round(float(ry), 1)},
        'face': [round(v, 1) for v in face_box],
        'eyes': [list(e['box']) for e in eyes],
        'brows': brows,
        'mouth': list(mouth),
        'chest': {'cx': round(chest_cx, 1), 'cy': round(chest_cy, 1),
                  'rx': round(chest_rx, 1), 'ry': round(chest_rx * 0.44, 1)},
        'guessed': guessed,
    }
