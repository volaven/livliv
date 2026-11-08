"""Check a package against schema/livliv-model-v4.json and the rules in FORMAT.md §8."""
import json
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def validate(folder, schema_path=None):
    errs, warns = [], []
    mp = os.path.join(folder, 'model.json')
    if not os.path.exists(mp):
        return ['no model.json'], []
    model = json.load(open(mp, encoding='utf-8'))

    schema_path = schema_path or os.path.join(ROOT, 'schema', 'livliv-model-v4.json')
    try:
        import jsonschema
        schema = json.load(open(schema_path, encoding='utf-8'))
        v = jsonschema.Draft202012Validator(schema)
        for e in sorted(v.iter_errors(model), key=lambda e: list(e.path))[:20]:
            errs.append('schema: /' + '/'.join(str(p) for p in e.path) + ': ' + e.message)
    except ImportError:
        warns.append('jsonschema is not installed: only the extra rules were checked')

    W, H = model.get('canvas', [0, 0])
    ids, hot = set(), set()
    expr = {e['id'] for e in model.get('expressions', [])}
    for L in model.get('layers', []):
        lid = L.get('id', '?')
        if lid in ids:
            errs.append(f'layer {lid}: the id is used twice')
        ids.add(lid)
        x, y, w, h = L.get('x', 0), L.get('y', 0), L.get('w', 0), L.get('h', 0)
        if x < 0 or y < 0 or x + w > W or y + h > H:
            errs.append(f'layer {lid}: the box {x},{y} {w}x{h} leaves the canvas {W}x{H}')
        imgs = [L.get('texture'), L.get('mask'), L.get('talk'), L.get('brow_tex')] + list(L.get('frames') or [])
        for rel in [i for i in imgs if i]:
            p = os.path.join(folder, rel)
            if not os.path.exists(p):
                errs.append(f'layer {lid}: {rel} is missing')
                continue
            with Image.open(p) as im:
                if im.size != (w, h):
                    errs.append(f'layer {lid}: {rel} is {im.size[0]}x{im.size[1]}, the box is {w}x{h}')
        if L.get('frames') and len(L['frames']) != len(L.get('visemes') or []):
            errs.append(f'layer {lid}: frames and visemes are different lengths')
        if L.get('role') == 'mouth' and len(L.get('frames') or []) < 3:
            errs.append(f'layer {lid}: a mouth needs at least three frames')
        if L.get('expression') and L['expression'] not in expr:
            errs.append(f'layer {lid}: expression {L["expression"]} is not declared')
    for L in model.get('layers', []):
        if L.get('clip') and L['clip'] not in ids:
            errs.append(f'layer {L.get("id")}: clip {L["clip"]} is not a layer')
    for e in model.get('expressions', []):
        if e.get('hotkey') in hot:
            errs.append(f'expression {e["id"]}: hotkey {e["hotkey"]} is used twice')
        hot.add(e.get('hotkey'))
    for rel in (model.get('files') or {}).values():
        if not os.path.exists(os.path.join(folder, rel)):
            errs.append(f'files: {rel} is missing')
    a = model.get('anchors', {})
    if a and not (a.get('top_y', 0) <= a.get('neck_y', 0) <= a.get('bottom_y', 0)):
        warns.append('anchors: neck_y is not between top_y and bottom_y')
    if not model.get('layers'):
        errs.append('no layers')
    return errs, warns


if __name__ == '__main__':
    bad = 0
    for folder in sys.argv[1:]:
        errs, warns = validate(folder)
        tag = os.path.basename(folder.rstrip('/'))
        for w in warns:
            print(f'  ! {tag}: {w}')
        for e in errs:
            print(f'  x {tag}: {e}')
        print(f'{"FAIL" if errs else "ok  "} {tag}: {len(errs)} errors, {len(warns)} warnings')
        bad += len(errs)
    sys.exit(1 if bad else 0)
