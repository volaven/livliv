#!/usr/bin/env python3
"""Measure the detector against the 21 featured characters, whose anchors are known.

Each cover.webp is the character at rest in its own canvas at half scale, so doubling it puts the
drawing back on the model's own coordinates and the detected anchors can be compared with the ones
livliv.ai wrote.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from PIL import Image

import detect as D

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def one(cid):
    mp = os.path.join(ROOT, 'characters', cid, 'model.json')
    cp = os.path.join(ROOT, 'characters', cid, 'cover.webp')
    if not (os.path.exists(mp) and os.path.exists(cp)):
        return None
    ref = json.load(open(mp, encoding='utf-8'))
    W, H = ref['canvas']
    im = Image.open(cp).convert('RGBA').resize((W, H), Image.LANCZOS)
    rgba = np.asarray(im, np.float32).copy()
    got = D.detect(rgba)
    a = ref['anchors']
    return {'id': cid, 'ref': a, 'got': got, 'ry': a['head']['ry'], 'layers': ref['layers']}


def main():
    ids = sorted(d for d in os.listdir(os.path.join(ROOT, 'characters'))
                 if os.path.isdir(os.path.join(ROOT, 'characters', d)))
    rows, keys = [], ['neck_y', 'hair_root_y', 'head.cx', 'head.cy', 'head.rx', 'head.ry']
    for cid in ids:
        r = one(cid)
        if not r:
            continue
        a, g, ry = r['ref'], r['got'], r['ry']
        ref = {'layers': r['layers']}
        d = {}
        for k in keys:
            rv = a['head'][k.split('.')[1]] if '.' in k else a[k]
            gv = g['head'][k.split('.')[1]] if '.' in k else g[k]
            d[k] = (gv - rv) / ry
        mouth_err = None
        ml = [L for L in ref['layers'] if L.get('role') == 'mouth'] if 'layers' in ref else []
        if ml:
            mb = ml[0]
            mc = (mb['x'] + mb['w'] / 2, mb['y'] + mb['h'] / 2)
            gb = g['mouth']
            mouth_err = max(abs(mc[0] - (gb[0] + gb[2]) / 2), abs(mc[1] - (gb[1] + gb[3]) / 2)) / ry
        eye_err = None
        if a.get('eyes') and g.get('eyes') and 'eyes' not in g.get('guessed', []):
            ce = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in a['eyes']]
            cg = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in g['eyes']]
            eye_err = max(max(abs(p[0] - q[0]), abs(p[1] - q[1])) for p, q in zip(ce, cg)) / ry
        rows.append((cid, d, g.get('guessed', []), eye_err, mouth_err))
    print(f'{"id":8} ' + ' '.join(f'{k.split(".")[-1]:>7}' for k in keys) + '   eyes  mouth  guessed')
    for cid, d, guess, ee, me in rows:
        print(f'{cid:8} ' + ' '.join(f'{d[k]:+7.2f}' for k in keys)
              + f'  {("%.2f" % ee) if ee is not None else "  - "}  {("%.2f" % me) if me is not None else "  - "}   {",".join(guess)}')
    print('\nmedian |error| in head radii:')
    for k in keys:
        v = np.median([abs(d[k]) for _, d, _, _, _ in rows])
        print(f'  {k:14} {v:.3f}')
    ok = [r for r in rows if not r[2]]
    print(f'\nfeatures found on {len(ok)}/{len(rows)} characters')
    ee = [r[3] for r in rows if r[3] is not None]
    if ee:
        print(f'eyes  found on {len(ee)}/{len(rows)}; centre error median {np.median(ee):.3f}, worst {max(ee):.3f} head radii')
    det = [r[4] for r in rows if r[4] is not None and 'mouth' not in r[2]]
    gue = [r[4] for r in rows if r[4] is not None and 'mouth' in r[2]]
    if det:
        print(f'mouth found   {len(det):2}/{len(rows)}: median {np.median(det):.3f}, worst {max(det):.3f} head radii')
    if gue:
        print(f'mouth guessed {len(gue):2}/{len(rows)}: median {np.median(gue):.3f}, worst {max(gue):.3f} head radii')


if __name__ == '__main__':
    main()
