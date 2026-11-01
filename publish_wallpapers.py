#!/usr/bin/env python3
"""Publish generated wallpapers (06..15) into the static repo.

For every pack in out/wp-new/<pack>/06..15.webp:
  image/<pack>/NN.webp        best (1000x1000)
  image/<pack>/NN_thumb.webp  thumb (333x333)
and rewrite data/wallpaper.json so each pack lists 01..15 (backgrounds untouched).

Usage:
  python3 publish_wallpapers.py           # copy + json
  python3 publish_wallpapers.py --dry-run
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

SRC_ROOT = Path("out/wp-new")
IMG_ROOT = Path("image")
JSON_PATH = Path("data/wallpaper.json")
FIRST_NEW, LAST_NEW = 6, 15


def render_json(data) -> str:
    """Keep the repo's one-line-per-pack, column-aligned style."""
    max_id = max(len(p["id"]) for p in data["packs"])
    name_col = 13 + max_id + 2
    img_col = name_col + 29
    lines = []
    for i, p in enumerate(data["packs"]):
        imgs = ",".join(f'"{s}"' for s in p["images"])
        arr = f'[{imgs}]'
        head = f'    {{ "id": "{p["id"]}",'.ljust(name_col)
        mid = f'"name": "{p["name"]}",'.ljust(img_col - name_col)
        tail = f'"images": {arr} }}' + ("," if i < len(data["packs"]) - 1 else "")
        lines.append(head + mid + tail)
    bg = data.get("backgrounds", [])
    bg_lines = []
    for i in range(0, len(bg), 10):
        chunk = ", ".join(f'"{b}"' for b in bg[i:i + 10])
        bg_lines.append("    " + chunk + ("," if i + 10 < len(bg) else ""))
    out = '{\n  "version": "%s",\n  "packs": [\n%s\n  ],\n  "backgrounds": [\n%s\n  ]\n}\n'
    return out % (data["version"], "\n".join(lines), "\n".join(bg_lines))


def main():
    dry = "--dry-run" in sys.argv
    packs = sorted(p for p in SRC_ROOT.iterdir() if p.is_dir()) if SRC_ROOT.exists() else []
    copied = skipped = 0
    for src_dir in packs:
        pack = src_dir.name
        dst_dir = IMG_ROOT / pack
        if not dst_dir.is_dir():
            print(f"  SKIP {pack}: missing {dst_dir}")
            skipped += 1
            continue
        got = 0
        for n in range(1, LAST_NEW - FIRST_NEW + 2):
            best = src_dir / f"{n:02d}.webp"
            thumb = src_dir / f"{n:02d}_thumb.webp"
            if not (best.is_file() and thumb.is_file()):
                continue
            dst = n + FIRST_NEW - 1
            got += 1
            if not dry:
                shutil.copy2(best, dst_dir / f"{dst:02d}.webp")
                shutil.copy2(thumb, dst_dir / f"{dst:02d}_thumb.webp")
        print(f"  {'WOULD COPY' if dry else 'copied'} {pack}: {got}/{LAST_NEW - FIRST_NEW + 1}")
        copied += got
        if got < LAST_NEW - FIRST_NEW + 1:
            skipped += 1
    print(f"packs={len(packs)} incomplete={skipped} images={copied}{' (dry)' if dry else ''}")

    data = json.loads(JSON_PATH.read_text())
    changed = 0
    for p in data["packs"]:
        ids = [f"{n:02d}" for n in range(1, LAST_NEW + 1)
               if (IMG_ROOT / p["id"] / f"{n:02d}.webp").is_file()]
        if len(ids) >= 6 and p["images"] != ids:
            p["images"] = ids
            changed += 1
    if not dry and changed:
        JSON_PATH.write_text(render_json(data))
    print(f"json packs changed={changed} (total {len(data['packs'])})")


if __name__ == "__main__":
    main()
