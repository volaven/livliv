#!/usr/bin/env python3
"""Turn one flat character picture into a LivLiv v4 package the player can load.

  python3 tools/convert.py my-characters/source/mina.png --name Mina
  python3 tools/convert.py --all

What it does: cuts the flat background away, finds the head, eyes, brows and mouth, cuts them into
layers, writes model.json with the anchors, checks it against schema/livliv-model-v4.json and packs
a .livliv. The marks it found are written to my-characters/marks/<id>.json -- edit that (or use
tools/mark.html) and run again to correct anything it got wrong.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from PIL import Image, ImageDraw

import build_model
import detect as D
import imgkit as K
import livliv_pack
import livliv_validate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, 'my-characters')
SRC, MARKS, OUT = (os.path.join(WORK, d) for d in ('source', 'marks', 'out'))
EXTS = ('.png', '.webp', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')


def slug(s):
    s = re.sub(r'[^A-Za-z0-9_]+', '_', os.path.splitext(os.path.basename(s))[0]).strip('_')
    return (s or 'character')[:40]


def overlay(rgba, marks, path):
    """A picture of what the converter thinks it found, to check by eye."""
    im = K.to_image(rgba).convert('RGBA')
    bg = Image.new('RGBA', im.size, (26, 26, 30, 255))
    bg.alpha_composite(im)
    d = ImageDraw.Draw(bg)
    h = marks['head']
    d.ellipse([h['cx'] - h['rx'], h['cy'] - h['ry'], h['cx'] + h['rx'], h['cy'] + h['ry']],
              outline=(90, 200, 255, 255), width=3)
    d.rectangle(marks['face'], outline=(255, 210, 90, 255), width=2)
    for b in marks['eyes']:
        d.rectangle(b, outline=(120, 255, 140, 255), width=2)
    for b in marks.get('brows') or []:
        d.rectangle(b, outline=(255, 140, 220, 255), width=2)
    d.rectangle(marks['mouth'], outline=(255, 110, 110, 255), width=2)
    W = marks['canvas'][0]
    for y, col in ((marks['neck_y'], (255, 255, 255, 190)), (marks['hair_root_y'], (160, 160, 255, 190))):
        d.line([0, y, W, y], fill=col, width=2)
    c = marks['chest']
    d.ellipse([c['cx'] - c['rx'], c['cy'] - c['ry'], c['cx'] + c['rx'], c['cy'] + c['ry']],
              outline=(180, 180, 200, 160), width=2)
    bg.convert('RGB').save(path, 'PNG')


def convert(src, args):
    cid = args.id or slug(src)
    name = args.name or cid.replace('_', ' ').title()
    out_dir = os.path.join(args.out or OUT, cid)
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(MARKS, exist_ok=True)

    print(f'· {cid}: reading {os.path.relpath(src, ROOT)}')
    im = Image.open(src)
    rgba, cut = D.cut_background(im, tol=args.bg_tol)
    rgba = D.fit_canvas(rgba, max_side=args.max_side)
    W, H = rgba.shape[1], rgba.shape[0]
    kept = float((rgba[..., 3] > 32).mean())
    print(f'  canvas {W}x{H}{" (flat background removed)" if cut else " (kept the file-s own alpha)"}'
          f', {kept * 100:.0f}% of it is the character')
    if cut and kept < 0.22:
        print('  ! little of the picture was kept. Where the character wears something close to the '
              'background colour it is cut away with it: look at _marks.png, and try a lower --bg-tol')

    mpath = args.marks or os.path.join(MARKS, cid + '.json')
    marks = None
    if os.path.exists(mpath) and not args.redetect:
        marks = json.load(open(mpath, encoding='utf-8'))
        if marks.get('canvas') != [W, H]:
            print(f'  marks {os.path.basename(mpath)} were made for {marks.get("canvas")}; detecting again')
            marks = None
        else:
            print(f'  marks: {os.path.relpath(mpath, ROOT)}')
    if marks is None:
        marks = D.detect(rgba)
        with open(mpath, 'w', encoding='utf-8') as f:
            json.dump(marks, f, ensure_ascii=False, indent=1)
        print(f'  marks: detected -> {os.path.relpath(mpath, ROOT)}'
              + (f'  (guessed: {", ".join(marks["guessed"])})' if marks.get('guessed') else ''))

    opts = {k: getattr(args, k) for k in ('author', 'license', 'mark', 'profile', 'bust', 'glasses')}
    opts['lids'] = not args.no_lids
    model, notes = build_model.build(rgba, marks, out_dir, cid, name, opts)
    overlay(rgba, marks, os.path.join(out_dir, '_marks.png'))
    K.to_image(rgba).save(os.path.join(out_dir, '_canvas.webp'), 'WEBP', quality=82, method=4)
    for n in notes:
        print(f'  ! {n}')
    print(f'  layers: {", ".join(L["id"] for L in model["layers"])}')

    errs, warns = livliv_validate.validate(out_dir)
    for w in warns:
        print(f'  ! {w}')
    for e in errs:
        print(f'  x {e}')
    if errs:
        print(f'  FAILED: {len(errs)} problems in the package')
        return cid, name, False
    if not args.no_pack:
        p, nbytes, n = livliv_pack.pack(out_dir, os.path.join(args.out or OUT, cid + '.livliv'))
        print(f'  packed: {os.path.relpath(p, ROOT)}  {nbytes/1e6:.2f} MB, {n} files')
    print(f'  ok: {os.path.relpath(out_dir, ROOT)}/')
    return cid, name, True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('source', nargs='*', help='picture(s); default: everything in my-characters/source/')
    ap.add_argument('--all', action='store_true', help='convert every picture in my-characters/source/')
    ap.add_argument('--id', help='character id (default: the file name)')
    ap.add_argument('--name', help='the name shown in the package (default: the id)')
    ap.add_argument('--marks', help='a marks file to use instead of my-characters/marks/<id>.json')
    ap.add_argument('--redetect', action='store_true', help='ignore the saved marks and find them again')
    ap.add_argument('--out', help='output folder (default: my-characters/out)')
    ap.add_argument('--max-side', type=int, default=2048, help='scale down so no side passes this (default 2048)')
    ap.add_argument('--bg-tol', type=int, default=22, help='how close to the corner colour counts as background')
    ap.add_argument('--author', help='meta.author.name')
    ap.add_argument('--license', help='meta.license.id, e.g. CC-BY-4.0 or LicenseRef-Mine')
    ap.add_argument('--mark', help='a watermark of your own, at most 24 characters')
    ap.add_argument('--profile', default='anime_half', choices=['anime_half', 'chibi', 'mascot', 'painterly'])
    ap.add_argument('--glasses', action='store_true')
    ap.add_argument('--bust', type=float, default=0.0, help='chest spring, 0..1 (default 0)')
    ap.add_argument('--no-lids', action='store_true',
                    help='no closed-eye layer: a blink then squashes the open eye instead of showing a lash line')
    ap.add_argument('--no-pack', action='store_true', help='leave the folder, write no .livliv')
    args = ap.parse_args()

    for d in (SRC, MARKS, OUT):
        os.makedirs(d, exist_ok=True)
    srcs = list(args.source)
    if args.all or not srcs:
        srcs = [os.path.join(SRC, f) for f in sorted(os.listdir(SRC))
                if f.lower().endswith(EXTS) and not f.startswith('.')] if os.path.isdir(SRC) else []
        if not srcs:
            print(f'convert: put a picture in {os.path.relpath(SRC, ROOT)}/ first, or name one on the command line')
            return 1
    if len(srcs) > 1 and (args.id or args.name or args.marks):
        print('convert: --id / --name / --marks only make sense with one picture')
        return 2

    done, bad = [], 0
    for s in srcs:
        cid, name, ok = convert(s, args)
        if ok:
            done.append({'id': cid, 'name': name})
        else:
            bad += 1

    if done:
        idx_path = os.path.join(args.out or OUT, 'index.json')
        idx = []
        if os.path.exists(idx_path):
            try:
                idx = json.load(open(idx_path, encoding='utf-8'))
            except Exception:
                idx = []
        by = {e['id']: e for e in idx}
        for e in done:
            by[e['id']] = e
        with open(idx_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(by.values(), key=lambda e: e['id']), f, ensure_ascii=False, indent=1)
        print(f'\n{len(done)} character(s) ready. Preview: npm run my:serve  ->  http://localhost:8080/tools/preview.html')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
