"""Small image helpers for the LivLiv converter: no scipy/cv2, numpy + Pillow only."""
import numpy as np
from PIL import Image, ImageFilter


# ---------------------------------------------------------------- components
def label(mask):
    """Connected components (4-way) of a bool array, by runs + union-find.

    Returns (labels int32 HxW with 0 = false, count).
    """
    h, w = mask.shape
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    rows, labs = [], []
    for y in range(h):
        row = mask[y]
        if not row.any():
            rows.append([]); labs.append([]); continue
        d = np.diff(row.astype(np.int8))
        starts = (np.where(d == 1)[0] + 1).tolist()
        ends = (np.where(d == -1)[0] + 1).tolist()
        if row[0]:
            starts.insert(0, 0)
        if row[-1]:
            ends.append(w)
        runs = list(zip(starts, ends))
        cur = []
        for s, e in runs:
            got = 0
            if y:
                for (ps, pe), pl in zip(rows[y - 1], labs[y - 1]):
                    if ps < e and s < pe:
                        if got == 0:
                            got = pl
                        else:
                            union(got, pl)
            if got == 0:
                parent.append(len(parent))
                got = len(parent) - 1
            cur.append(got)
        rows.append(runs); labs.append(cur)

    out = np.zeros((h, w), np.int32)
    remap, n = {}, 0
    for y, runs in enumerate(rows):
        for (s, e), l in zip(runs, labs[y]):
            r = find(l)
            if r not in remap:
                n += 1
                remap[r] = n
            out[y, s:e] = remap[r]
    return out, n


def blobs(mask):
    """[{label, area, box=(x0,y0,x1,y1), cx, cy}] sorted by area, largest first."""
    lab, n = label(mask)
    if not n:
        return [], lab
    ys, xs = np.nonzero(lab)
    l = lab[ys, xs]
    area = np.bincount(l, minlength=n + 1)
    x0 = np.full(n + 1, 1 << 30); np.minimum.at(x0, l, xs)
    x1 = np.full(n + 1, -1); np.maximum.at(x1, l, xs)
    y0 = np.full(n + 1, 1 << 30); np.minimum.at(y0, l, ys)
    y1 = np.full(n + 1, -1); np.maximum.at(y1, l, ys)
    sx = np.bincount(l, weights=xs.astype(float), minlength=n + 1)
    sy = np.bincount(l, weights=ys.astype(float), minlength=n + 1)
    out = [{'label': i, 'area': int(area[i]), 'box': (int(x0[i]), int(y0[i]), int(x1[i]) + 1, int(y1[i]) + 1),
            'cx': float(sx[i] / area[i]), 'cy': float(sy[i] / area[i])} for i in range(1, n + 1)]
    out.sort(key=lambda b: -b['area'])
    return out, lab


def largest(mask):
    bs, lab = blobs(mask)
    return (lab == bs[0]['label']) if bs else np.zeros_like(mask)


def span_fill(mask):
    """Everything between the mask's first and last pixel on each row AND on each column.

    Closes a shape that is open at one side -- an eye whose lashes run into the hair -- where
    fill_holes, which needs the hole fully enclosed, would not.
    """
    def rows(m):
        has = m.any(1)
        first = np.argmax(m, 1)
        last = m.shape[1] - 1 - np.argmax(m[:, ::-1], 1)
        i = np.arange(m.shape[1])[None, :]
        return has[:, None] & (i >= first[:, None]) & (i <= last[:, None])
    return rows(mask) & rows(mask.T).T


def fill_holes(mask):
    """mask with every region enclosed by it filled in."""
    lab, n = label(~mask)
    if not n:
        return mask.copy()
    edge = set(lab[0].tolist()) | set(lab[-1].tolist()) | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    edge.discard(0)
    outside = np.isin(lab, list(edge)) if edge else np.zeros_like(mask)
    return mask | (~mask & ~outside)


# ------------------------------------------------------------- morphology
def dilate(mask, r=1):
    out = mask.copy()
    for _ in range(int(r)):
        o = out.copy()
        o[1:, :] |= out[:-1, :]; o[:-1, :] |= out[1:, :]
        o[:, 1:] |= out[:, :-1]; o[:, :-1] |= out[:, 1:]
        out = o
    return out


def erode(mask, r=1):
    return ~dilate(~mask, r)


def feather(mask, r):
    """0..1 float matte: the mask with its edge blurred over r px."""
    im = Image.fromarray((mask * 255).astype(np.uint8), 'L')
    if r > 0:
        im = im.filter(ImageFilter.GaussianBlur(float(r)))
    return np.asarray(im, np.float32) / 255.0


def blur(arr, r):
    """Gaussian blur of an HxWxC float array."""
    if r <= 0:
        return arr.copy()
    c = arr.shape[2]
    out = np.empty_like(arr)
    for i in range(c):
        im = Image.fromarray(np.clip(arr[..., i], 0, 255).astype(np.uint8), 'L')
        out[..., i] = np.asarray(im.filter(ImageFilter.GaussianBlur(float(r))), np.float32)
    return out


# ------------------------------------------------------------------ colour
def hsv(rgb):
    """rgb float 0..255 HxWx3 -> (h 0..360, s 0..1, v 0..1)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = rgb.max(2); mn = rgb.min(2)
    d = np.maximum(mx - mn, 1e-6)
    h = np.zeros_like(mx)
    m = (mx == r); h[m] = ((g - b)[m] / d[m]) % 6
    m = (mx == g) & (mx != r); h[m] = ((b - r)[m] / d[m]) + 2
    m = (mx == b) & (mx != r) & (mx != g); h[m] = ((r - g)[m] / d[m]) + 4
    return h * 60, np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0), mx / 255.0


def skin_mask(rgb, alpha):
    """Anime skin: warm, light, lightly saturated."""
    H, S, V = hsv(rgb)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    return ((alpha > 128) & (V > 0.52) & (S > 0.04) & (S < 0.62)
            & (((H >= 0) & (H <= 52)) | (H >= 330)) & (r >= g - 2) & (g >= b - 6))


# ------------------------------------------------------------------- misc
def to_image(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), 'RGBA')


def save_texture(arr, path, lossless=False, quality=92):
    im = to_image(arr)
    if str(path).endswith('.png'):
        im.save(path, 'PNG', optimize=True)
    else:
        im.save(path, 'WEBP', lossless=lossless, quality=100 if lossless else quality, method=4)


def unpremul_edge(rgb, alpha01, bg):
    """Pull the background colour back out of anti-aliased edge pixels."""
    a = np.clip(alpha01, 0, 1)[..., None]
    soft = (a > 0.02) & (a < 0.98)
    out = rgb.copy()
    rec = bg + (rgb - bg) / np.maximum(a, 0.08)
    out = np.where(soft, np.clip(rec, 0, 255), rgb)
    return out
