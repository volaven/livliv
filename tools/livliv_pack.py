"""Pack a package folder into one .livliv file (FORMAT.md §1), or unpack one."""
import os
import struct
import sys
import zipfile
import zlib


def pack(folder, out_path, skip=('cover.webp',)):
    """Everything the package needs, and nothing else: names starting with `_` are the converter's
    own working files (the marks picture, the pose renders) and stay out, as does the cover, which a
    page shows before the package arrives."""
    names = []
    for root, _, fs in os.walk(folder):
        for f in sorted(fs):
            rel = os.path.relpath(os.path.join(root, f), folder).replace(os.sep, '/')
            if rel in skip or any(part.startswith(('.', '_')) for part in rel.split('/')):
                continue
            names.append(rel)
    names.sort()
    if 'model.json' not in names:
        raise SystemExit(f'pack: {folder} has no model.json')
    names = ['model.json'] + [n for n in names if n != 'model.json']

    local, central, at = [], [], 0
    for name in names:
        raw = open(os.path.join(folder, name), 'rb').read()
        deflate = name == 'keyforms.json'
        data = zlib.compress(raw, 9)[2:-4] if deflate else raw
        fn = name.encode('utf-8')
        crc = zlib.crc32(raw) & 0xFFFFFFFF
        method = 8 if deflate else 0
        local.append(struct.pack('<IHHHHHIIIHH', 0x04034b50, 20, 0x0800, method, 0, 0x21,
                                 crc, len(data), len(raw), len(fn), 0) + fn + data)
        central.append(struct.pack('<IHHHHHHIIIHHHHHII', 0x02014b50, 20, 20, 0x0800, method, 0, 0x21,
                                   crc, len(data), len(raw), len(fn), 0, 0, 0, 0, 0, at) + fn)
        at += 30 + len(fn) + len(data)
    cd = b''.join(central)
    end = struct.pack('<IHHHHIIH', 0x06054b50, 0, 0, len(names), len(names), len(cd), at, 0)
    with open(out_path, 'wb') as f:
        f.write(b''.join(local) + cd + end)
    return out_path, os.path.getsize(out_path), len(names)


def unpack(src, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        bad = [n for n in z.namelist() if n.startswith('/') or '..' in n.split('/')]
        if bad:
            raise SystemExit(f'unpack: unsafe entry {bad[0]}')
        root = ''
        tops = {n.split('/')[0] for n in z.namelist() if not n.startswith('__MACOSX')}
        if len(tops) == 1 and not any(n == 'model.json' for n in z.namelist()):
            root = tops.pop() + '/'
        for n in z.namelist():
            if n.endswith('/') or n.startswith('__MACOSX') or os.path.basename(n).startswith('._'):
                continue
            if os.path.basename(n) in ('.DS_Store', 'Thumbs.db'):
                continue
            rel = n[len(root):] if root and n.startswith(root) else n
            dst = os.path.join(out_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(z.read(n))
    return out_dir


if __name__ == '__main__':
    if len(sys.argv) < 3:
        raise SystemExit('usage: livliv_pack.py <folder> <out.livliv> | --unpack <file.livliv> <folder>')
    if sys.argv[1] == '--unpack':
        print('unpacked ->', unpack(sys.argv[2], sys.argv[3]))
    else:
        p, n, c = pack(sys.argv[1], sys.argv[2])
        print(f'{p}: {n/1e6:.2f} MB, {c} entries')
