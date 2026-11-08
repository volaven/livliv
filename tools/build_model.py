"""Cut a flat picture into LivLiv layers and write the v4 package."""
import datetime as _dt
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import imgkit as K

VISEMES = [('closed', 0.0, 1.00), ('half', 0.34, 0.95), ('open', 0.95, 1.00),
           ('round', 0.78, 0.66), ('wide', 0.50, 1.30)]

# layer sizes, as the 21 featured characters have them (tools/calibrate.py)
EYE_LAYER_W = 0.820    # the eye layer's width, in the distance between the eye centres
EYE_LAYER_H = 0.636
MOUTH_W = 0.694        # the mouth layer, in head radii
MOUTH_H = 0.496
MOUTH_ABOVE = 0.34     # how much of that height sits above the drawn lips
MOUTH_PIVOT = 0.135    # where the upper lip is pinned, down the layer
MOUTH_OPEN = 0.30      # how far a wide-open mouth drops, in head radii
MOUTH_WIDTH = 0.26     # and how wide it is then


# ------------------------------------------------------------------ utils
def clip_box(box, W, H, pad=(0, 0, 0, 0)):
    x0, y0, x1, y1 = box
    x0 -= pad[0]; y0 -= pad[1]; x1 += pad[2]; y1 += pad[3]
    x0 = int(max(0, min(W - 2, x0))); y0 = int(max(0, min(H - 2, y0)))
    x1 = int(max(x0 + 1, min(W, x1))); y1 = int(max(y0 + 1, min(H, y1)))
    return x0, y0, x1, y1


def crop(arr, box):
    x0, y0, x1, y1 = box
    return arr[y0:y1, x0:x1].copy()


def content_box(arr, thr=3):
    ys, xs = np.nonzero(arr[..., 3] > thr)
    if not len(ys):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def inpaint(region, hole, scale):
    """Paint `hole` out with the skin around it.

    Only skin feeds the fill, so a hole that touches the bangs does not smear hair across the face,
    and the fill still follows the shading the drawing has there.
    """
    out = region.copy()
    rgb, a = region[..., :3], region[..., 3]
    known = (~hole) & (a > 32)
    skin = K.skin_mask(rgb, a) & known
    ring = K.dilate(hole, max(3, int(scale * 0.5))) & known
    src = skin if skin.sum() > 32 else (ring if ring.sum() > 8 else known)
    if src.sum() < 4:
        return out
    seed = np.median(rgb[src], axis=0)
    field = np.where(skin[..., None] if skin.sum() > 32 else src[..., None], rgb, seed)
    for r in (scale * 0.8, scale * 0.4, scale * 0.18):
        field = K.blur(np.dstack([field, np.full(field.shape[:2], 255.0, np.float32)]),
                       max(1.0, r))[..., :3]
        if skin.sum() > 32:
            field = np.where(skin[..., None], rgb, field)
    out[..., :3] = np.where(hole[..., None], field, rgb)
    out[..., 3] = np.where(hole, np.maximum(a, float(np.median(a[src]))), a)
    return out


def apply_patch(arr, box, patch, hole, soft=2.0):
    """Write a patch back into the canvas, fading over a couple of pixels at the hole's rim."""
    x0, y0, x1, y1 = box
    base = arr[y0:y1, x0:x1]
    m = K.feather(hole, max(0.8, soft))[..., None]
    base[..., :3] = patch[..., :3] * m + base[..., :3] * (1 - m)
    base[..., 3] = np.maximum(base[..., 3], patch[..., 3] * m[..., 0])


def eye_parts(arr, box, sep, lids=False):
    """Cut one eye: the open eye with blank whites, the whites as a mask, the iris, and a lid line.

    `box` is the eye as it is drawn; the layer around it takes the size the featured characters use,
    0.82 x 0.64 of the distance between the eyes, so a small or lopsided mark still gives a sane layer.
    """
    H, W = arr.shape[:2]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    lw, lh = max(12.0, EYE_LAYER_W * sep), max(10.0, EYE_LAYER_H * sep)
    lb = clip_box((cx - lw / 2, cy - lh / 2, cx + lw / 2, cy + lh / 2), W, H)
    c = crop(arr, lb)
    rgb, a = c[..., :3], c[..., 3]

    # the eye itself: what is neither skin nor background, inside the mark and a margin around it,
    # so bangs touching the lashes cannot drag the whole crop in
    inner = np.zeros(c.shape[:2], bool)
    ix0 = int(max(0, box[0] - 0.22 * (box[2] - box[0]) - lb[0]))
    iy0 = int(max(0, box[1] - 0.40 * (box[3] - box[1]) - lb[1]))
    ix1 = int(min(c.shape[1], box[2] + 0.22 * (box[2] - box[0]) - lb[0]))
    iy1 = int(min(c.shape[0], box[3] + 0.40 * (box[3] - box[1]) - lb[1]))
    if ix1 - ix0 < 4 or iy1 - iy0 < 4:
        return None
    inner[iy0:iy1, ix0:ix1] = True
    nonskin = (~K.skin_mask(rgb, a)) & (a > 110) & inner
    bs, lab = K.blobs(nonskin)
    px, py = (box[0] + box[2]) / 2 - lb[0], (box[1] + box[3]) / 2 - lb[1]
    blob = None
    for b in bs:
        x0, y0, x1, y1 = b['box']
        if x0 - 2 <= px <= x1 + 2 and y0 - 2 <= py <= y1 + 2:
            blob = (lab == b['label']); break
    if blob is None and bs:
        blob = (lab == bs[0]['label'])
    if blob is None or blob.sum() < 16:
        return None
    blob = K.fill_holes(blob)

    ys, xs = np.nonzero(blob)
    eh = max(4, ys.max() - ys.min() + 1)
    ew = max(4, xs.max() - xs.min() + 1)

    _, S, V = K.hsv(rgb)
    light = blob & (V > 0.78) & (S < 0.25)
    sclera = rgb[light].mean(0) if light.sum() > 24 else np.array([248.0, 247.0, 250.0])
    rim = blob & ~K.erode(blob, max(2, int(0.09 * eh)))          # the lash and the eye's outline
    murk = blob & (V < max(0.30, float(np.quantile(V[blob], 0.12))))
    lash = rgb[rim & murk].mean(0) if (rim & murk).sum() > 8 else np.array([60.0, 48.0, 54.0])

    # the iris: the coloured middle of the eye -- not the whites, not the dark rim around it
    cand = K.erode(blob, max(2, int(0.07 * eh))) & ~light & ~(rim | murk)
    if cand.sum() < 0.06 * blob.sum():
        cand = K.erode(blob, max(2, int(0.07 * eh))) & ~light
    iris = K.fill_holes(K.largest(cand)) if cand.any() else np.zeros_like(blob)
    iris = K.dilate(iris, 1) & blob
    if iris.sum() < 0.04 * blob.sum():
        iris = K.erode(blob, max(1, int(0.12 * eh)))

    eye = c.copy()
    eye[..., :3][iris] = sclera
    eye[..., :3] = K.blur(eye, 1.0)[..., :3] * iris[..., None] + eye[..., :3] * (~iris)[..., None]
    eye[..., 3] = K.feather(blob, 0.8) * 255.0

    ib = content_box(np.dstack([c[..., :3], (iris * 255).astype(np.float32)]))
    if ib:
        ix, iy, jx, jy = ib
        iris_tex = c[iy:jy, ix:jx].copy()
        iris_tex[..., 3] = K.feather(iris[iy:jy, ix:jx], 0.7) * 255.0
        iris_box = (lb[0] + ix, lb[1] + iy, lb[0] + jx, lb[1] + jy)
    else:
        iris_tex, iris_box = np.zeros_like(c), lb

    mask = np.zeros_like(c)
    mask[..., :3] = 255.0
    mask[..., 3] = K.feather(K.erode(blob, max(1, int(0.05 * eh))), 0.6) * 255.0

    lid = np.zeros_like(c)
    if lids:
        # a closed eye, drawn from the lower lash: a curve fitted through the eye's bottom edge, so a
        # gap or a stray lash in the cut-out cannot turn it into a zigzag
        tall = blob.sum(0)
        cols = np.nonzero(tall > 0.25 * tall.max())[0] if tall.max() else np.array([], int)
        if len(cols) > 8:
            bottom = (blob.shape[0] - 1 - np.argmax(blob[::-1], 0)).astype(float)
            xs2, ys2 = cols.astype(float), bottom[cols]
            for _ in range(2):
                co = np.polyfit(xs2, ys2, 2)
                res = ys2 - np.polyval(co, xs2)
                keep = np.abs(res) <= max(1.5, 2.0 * float(np.std(res)))
                if keep.sum() > 6:
                    xs2, ys2 = xs2[keep], ys2[keep]
            co = np.polyfit(xs2, ys2, 2)
            xx = np.arange(cols.min(), cols.max() + 1, dtype=float)
            line = Image.new('L', (c.shape[1], c.shape[0]), 0)
            ImageDraw.Draw(line).line([(float(x), float(np.polyval(co, x))) for x in xx],
                                      fill=255, width=max(2, int(0.13 * eh)), joint='curve')
            lid[..., :3] = lash
            lid[..., 3] = np.asarray(line.filter(ImageFilter.GaussianBlur(0.8)), np.float32)

    pivot = [lb[0] + c.shape[1] / 2, lb[1] + (ys.min() + ys.max()) / 2 + 0.06 * eh]
    return {'box': lb, 'eye': eye, 'mask': mask, 'iris': iris_tex, 'iris_box': iris_box,
            'pivot': [round(v, 2) for v in pivot], 'lid': lid, 'blob': blob,
            'range': [round(max(3.0, 0.11 * ew), 2), round(max(2.0, 0.085 * eh), 2)]}


# ------------------------------------------------------------------ mouth
def mouth_parts(arr, box, rx):
    """Cut the mouth and draw the frames it has to have: closed, half, open, round, wide.

    A flat picture has one mouth, drawn shut, so the open frames are made here: the lip line stays
    where it was drawn and an opening is laid under it, sized from the head, not from the mark --
    a mark found a little small or a little low still gives a mouth the right size.
    """
    H, W = arr.shape[:2]
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    lw, lh = max(16.0, MOUTH_W * rx), max(12.0, MOUTH_H * rx)
    lb = clip_box((cx - lw / 2, cy - MOUTH_ABOVE * lh, cx + lw / 2, cy + (1 - MOUTH_ABOVE) * lh), W, H)
    c = crop(arr, lb)
    rgb, a = c[..., :3], c[..., 3]

    inner = np.zeros(c.shape[:2], bool)
    ix0 = int(max(0, box[0] - 0.25 * (box[2] - box[0]) - lb[0]))
    iy0 = int(max(0, box[1] - 0.6 * (box[3] - box[1]) - lb[1]))
    ix1 = int(min(c.shape[1], box[2] + 0.25 * (box[2] - box[0]) - lb[0]))
    iy1 = int(min(c.shape[0], box[3] + 0.6 * (box[3] - box[1]) - lb[1]))
    inner[iy0:max(iy0 + 2, iy1), ix0:max(ix0 + 2, ix1)] = True
    _, _, V = K.hsv(rgb)
    lit = (a > 110)
    ref = float(np.percentile(V[lit], 72)) if lit.sum() > 32 else 0.8
    stroke = inner & lit & (V < 0.90 * ref)
    bs, lab = K.blobs(stroke)
    smask = (lab == bs[0]['label']) if bs else np.zeros(c.shape[:2], bool)
    if smask.sum() < 6:
        smask = inner & lit & (V < 0.95 * ref)
    ys, xs = np.nonzero(smask)
    if not len(ys):
        return None
    sx0, sy0, sx1, sy1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    scx = float(xs.mean())
    lipc = rgb[smask].mean(0)
    inner_col = np.clip(lipc * 0.42 + np.array([64.0, 26.0, 32.0]) * 0.58, 0, 255)
    tongue = np.clip(inner_col * 0.45 + np.array([206.0, 108.0, 118.0]) * 0.55, 0, 255)

    full = MOUTH_OPEN * rx                 # how far the mouth drops when it is wide open
    wide = MOUTH_WIDTH * rx                # and how wide it is then
    frames = []
    for name, t, wf in VISEMES:
        f = c.copy()
        if t > 0:
            w_open, h_open = wide * wf, max(3.0, t * full)
            top = sy0 + (sy1 - sy0) * 0.45
            m = Image.new('L', (c.shape[1], c.shape[0]), 0)
            ImageDraw.Draw(m).ellipse([scx - w_open / 2, top, scx + w_open / 2, top + h_open], fill=255)
            om = np.asarray(m, np.float32) / 255.0
            tm = Image.new('L', (c.shape[1], c.shape[0]), 0)
            ImageDraw.Draw(tm).ellipse([scx - w_open * 0.34, top + h_open * 0.5,
                                        scx + w_open * 0.34, top + h_open * 1.04], fill=255)
            tn = (np.asarray(tm, np.float32) / 255.0) * om
            soft = np.asarray(m.filter(ImageFilter.GaussianBlur(1.1)), np.float32) / 255.0
            f[..., :3] = inner_col * soft[..., None] + f[..., :3] * (1 - soft[..., None])
            f[..., :3] = tongue * tn[..., None] + f[..., :3] * (1 - tn[..., None])
            lip = K.feather(smask & (np.arange(c.shape[0])[:, None] <= sy0 + (sy1 - sy0) * 0.55), 0.6)[..., None]
            f[..., :3] = c[..., :3] * lip + f[..., :3] * (1 - lip)
            f[..., 3] = np.maximum(f[..., 3], soft * 255.0)
        frames.append((name, f))
    pivot = [lb[0] + c.shape[1] / 2, lb[1] + MOUTH_PIVOT * c.shape[0]]
    return {'box': lb, 'frames': frames, 'pivot': [round(v, 2) for v in pivot], 'stroke': smask}


# ------------------------------------------------------------------ build
def _run_at(row, x):
    """The run of true values in `row` that covers column x, as (start, end)."""
    n = len(row)
    x = int(np.clip(x, 0, n - 1))
    if not row[x]:
        near = np.nonzero(row)[0]
        if not len(near):
            return None
        x = int(near[np.argmin(np.abs(near - x))])
    a = x
    while a > 0 and row[a - 1]:
        a -= 1
    b = x
    while b < n - 1 and row[b + 1]:
        b += 1
    return a, b + 1


def build(rgba, marks, out_dir, cid, name, opts):
    H, W = rgba.shape[:2]
    tex = os.path.join(out_dir, 'textures')
    os.makedirs(tex, exist_ok=True)
    head = marks['head']
    ry, neck = float(head['ry']), float(marks['neck_y'])
    base = rgba.copy()
    notes = []

    mk = marks['eyes']
    ec = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in mk]
    sep = float(np.hypot(ec[0][0] - ec[1][0], ec[0][1] - ec[1][1])) if len(mk) > 1 else float(head['rx']) / 0.955
    eyes = []
    for i, b in enumerate(mk):
        p = eye_parts(base, tuple(b), sep, bool(opts.get('lids')))
        if p:
            eyes.append(p)
        else:
            notes.append(f'eye {i + 1} could not be cut; it stays part of the face')
    brow_boxes = [tuple(b) for b in marks.get('brows') or []]
    mouth = mouth_parts(base, tuple(marks['mouth']), float(head['rx']))
    if not mouth:
        notes.append('no mouth found: lip sync will not move')

    # the face keeps everything but the parts that now move on their own
    face_arr = base.copy()
    for p in eyes:
        x0, y0, x1, y1 = p['box']
        eh = max(8, int(0.42 * (y1 - y0)))                 # the drawn eye inside its layer box
        hole = K.dilate(p['blob'], max(3, int(0.16 * eh)))
        apply_patch(face_arr, p['box'], inpaint(crop(face_arr, p['box']), hole, max(8.0, eh * 0.7)),
                    hole, max(1.5, 0.05 * eh))
    brows_layer = None
    if brow_boxes:
        bx0 = min(b[0] for b in brow_boxes); by0 = min(b[1] for b in brow_boxes)
        bx1 = max(b[2] for b in brow_boxes); by1 = max(b[3] for b in brow_boxes)
        bh = by1 - by0
        lb = clip_box((bx0, by0, bx1, by1), W, H, (int(0.10 * (bx1 - bx0)), int(0.9 * bh),
                                                   int(0.10 * (bx1 - bx0)), int(0.9 * bh)))
        c = crop(base, lb)
        ns = (~K.skin_mask(c[..., :3], c[..., 3])) & (c[..., 3] > 110)
        keep = np.zeros(c.shape[:2], bool)
        bs, lab = K.blobs(ns)
        for b in brow_boxes:
            px, py = (b[0] + b[2]) / 2 - lb[0], (b[1] + b[3]) / 2 - lb[1]
            for blob in bs:
                x0, y0, x1, y1 = blob['box']
                if x0 - 1 <= px <= x1 + 1 and y0 - 1 <= py <= y1 + 1:
                    keep |= (lab == blob['label']); break
        if keep.sum() > 24:
            bt = c.copy()
            bt[..., 3] = K.feather(keep, 0.7) * 255.0
            brows_layer = {'box': lb, 'tex': bt}
            hole = K.dilate(keep, max(3, int(0.45 * bh)))
            apply_patch(face_arr, lb, inpaint(crop(face_arr, lb), hole, max(8.0, bh * 1.6)),
                        hole, max(1.5, 0.12 * bh))
        else:
            notes.append('brows could not be cut; they stay part of the face')

    # Head and body are cut apart just under the chin, and the neck is carried on upward behind the
    # head (the featured characters are built the same way): a turn or a nod then slides the chin
    # over neck instead of over a hole, and at rest the two layers meet on pixels that already match.
    cut = int(round(min(H - 2, neck + 0.10 * ry)))
    skin = K.skin_mask(base[..., :3], base[..., 3])
    lo, hi = cut + 1, int(min(H - 1, neck + 0.75 * ry))
    src, best, run = None, None, None
    for y in range(lo, max(lo + 1, hi)):
        r = _run_at(skin[y], int(head['cx']))
        if r and r[1] - r[0] <= 2.2 * head['rx'] and (best is None or r[1] - r[0] < best):
            best, src, run = r[1] - r[0], y, r
    if run is None:                                   # a high collar: back the chin with what is there
        y = min(H - 1, cut + 2)
        r = _run_at(base[y, :, 3] > 64, int(head['cx']))
        if r:
            half = min((r[1] - r[0]) / 2, 0.55 * head['rx'])
            mid = (r[0] + r[1]) / 2
            src, run = y, (int(mid - half), int(mid + half))
        else:
            notes.append('nothing found under the chin: a turn may show a gap behind the jaw')

    # the head fades out over the last few rows, onto body that still holds the same pixels there:
    # at rest the two add up to the picture again, and a turn's small shift has no hard edge to show
    fade = max(4.0, 0.045 * ry)
    yy = np.arange(H, dtype=np.float32)[:, None]
    head_arr = face_arr.copy()
    head_arr[..., 3] *= np.clip((cut - yy) / fade + 1.0, 0, 1)

    body_arr = base.copy()
    body_arr[:max(0, int(cut - fade)), :, 3] = 0
    stub_top = int(max(0, cut - fade - 0.80 * ry))
    if run is not None and stub_top < cut:
        # the neck carried up behind the head, no wider than the head's own outline, so at rest it is
        # hidden exactly and a turn uncovers neck rather than background
        fill = np.median(base[src, run[0]:run[1], :3], axis=0)
        cover = K.dilate(face_arr[..., 3] > 32, max(3, int(0.05 * ry)))
        band = np.zeros((H, W), bool); band[stub_top:max(stub_top + 1, int(cut - fade))] = True
        m = band & cover
        taper = np.clip((yy - stub_top) / max(1.0, 0.22 * (cut - fade - stub_top)), 0, 1)
        body_arr[..., :3] = np.where(m[..., None], fill, body_arr[..., :3])
        body_arr[..., 3] = np.where(m, np.maximum(body_arr[..., 3], 255.0 * taper), body_arr[..., 3])

    head_box = content_box(head_arr) or (0, 0, W, 1)
    body_box = content_box(body_arr) or (0, 0, W, H)

    layers, files = [], []

    def put(arr_or_img, fname, lossless=False):
        path = os.path.join(tex, fname)
        K.save_texture(arr_or_img, path, lossless=lossless)
        files.append(fname)
        return 'textures/' + fname

    def box_fields(box):
        return {'x': int(box[0]), 'y': int(box[1]), 'w': int(box[2] - box[0]), 'h': int(box[3] - box[1])}

    layers.append({'id': 'body', 'texture': put(crop(body_arr, body_box), 'body.webp'),
                   **box_fields(body_box), 'group': 'body', 'depth': 0})
    layers.append({'id': 'face', 'texture': put(crop(head_arr, head_box), 'face.webp'),
                   **box_fields(head_box), 'group': 'head', 'depth': 0})

    for i, p in enumerate(eyes):
        s = 'L' if i == 0 else 'R'
        if p['lid'][..., 3].max() > 8:
            layers.append({'id': f'eye_{s}_closed', 'texture': put(p['lid'], f'eye_{s}_closed.webp'),
                           **box_fields(p['box']), 'group': 'head', 'depth': 0, 'role': f'lid_{s}'})
        layers.append({'id': f'eye_{s}', 'texture': put(p['eye'], f'eye_{s}.webp'),
                       'mask': put(p['mask'], f'eye_{s}_mask.png', lossless=True),
                       **box_fields(p['box']), 'group': 'head', 'depth': 0,
                       'role': f'eye_{s}', 'pivot': p['pivot']})
        if p['iris'][..., 3].max() > 8:
            layers.append({'id': f'iris_{s}', 'texture': put(p['iris'], f'iris_{s}.webp'),
                           **box_fields(p['iris_box']), 'group': 'head', 'depth': 0,
                           'role': f'iris_{s}', 'pivot': p['pivot'], 'clip': f'eye_{s}', 'range': p['range']})

    if mouth:
        frame_paths = [put(f, f'mouth_f{i}.webp') for i, (_, f) in enumerate(mouth['frames'])]
        layers.append({'id': 'mouth', 'texture': put(mouth['frames'][0][1], 'mouth.webp'),
                       'frames': frame_paths, 'visemes': [n for n, _, _ in VISEMES],
                       **box_fields(mouth['box']), 'group': 'head', 'depth': 0,
                       'role': 'mouth', 'pivot': mouth['pivot']})
    if brows_layer:
        layers.append({'id': 'brows', 'texture': put(brows_layer['tex'], 'brows.webp'),
                       **box_fields(brows_layer['box']), 'group': 'head', 'depth': 0})

    # cover and avatar
    cover = K.to_image(base)
    cw, ch = cover.size
    s = min(512 / cw, 768 / ch)
    cover.resize((max(1, int(cw * s)), max(1, int(ch * s))), Image.LANCZOS).save(
        os.path.join(out_dir, 'cover.webp'), 'WEBP', quality=88, method=4)
    hb = clip_box((int(head['cx'] - head['rx'] * 1.15), int(head['cy'] - ry * 1.15),
                   int(head['cx'] + head['rx'] * 1.15), int(head['cy'] + ry * 1.15)), W, H)
    av = K.to_image(crop(base, hb)).resize((96, 96), Image.LANCZOS)
    av.save(os.path.join(out_dir, 'avatar.webp'), 'WEBP', quality=90, method=4)

    model = {
        'format': 'livliv-model', 'version': 4, 'name': name,
        'meta': {
            'generator': {'name': opts.get('generator', 'livliv-convert'), 'build': '1'},
            'created': _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        },
        'requires': [],
        'files': {'avatar': 'avatar.webp'},   # cover.webp stays beside the package, as the featured ones do
        'canvas': [W, H],
        'profile': {'id': opts.get('profile', 'anime_half'), 'facing': 'front', 'glasses': bool(opts.get('glasses'))},
        'rig': {
            'yaw': opts.get('yaw', 0.28), 'pitch': 0.22, 'roll': 0.5, 'bulge': 0.6,
            'wind': 1, 'breath': 1, 'sway': 1, 'brow': 0.06,
            'body': {'yaw': 0.35, 'roll': 0.3, 'breath': 1, 'bust': opts.get('bust', 0)},
        },
        'anchors': {
            'head': {k: float(v) for k, v in head.items()},
            'face': [float(v) for v in marks['face']],
            'neck_y': float(neck), 'top_y': float(marks['top_y']), 'bottom_y': float(marks['bottom_y']),
            'hair_root_y': float(marks['hair_root_y']),
            'eyes': [[float(v) for v in b] for b in marks['eyes']],
            'jaw': {'top': round(neck - 0.5 * ry, 1), 'chin': float(neck),
                    'half': 0, 'open': 0, 'round': 0, 'wide': 0},
            'chest': {k: float(v) for k, v in marks['chest'].items()},
        },
        'expressions': [],
        'layers': layers,
    }
    if brow_boxes:
        model['anchors']['brows'] = [[float(v) for v in b] for b in brow_boxes]
    if opts.get('author'):
        model['meta']['author'] = {'name': opts['author']}
    if opts.get('license'):
        model['meta']['license'] = {'id': opts['license']}
    if opts.get('mark'):
        model['meta']['watermark'] = {'kind': 'text', 'text': opts['mark'][:24]}
    with open(os.path.join(out_dir, 'model.json'), 'w', encoding='utf-8') as f:
        json.dump(model, f, ensure_ascii=False, separators=(',', ':'))
    return model, notes
