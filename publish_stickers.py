#!/usr/bin/env python3
"""Publish generated stickers (06..NN) into the static repo.

For every PNG in out/sticker-figma/<pack>/06..NN.png:
  image/<pack>/NN.webp        best, 480x480 RGBA canvas (art fitted to longest side 480)
  image/<pack>/NN_thumb.webp  thumb, 160x160 (1/3)
and rewrite data/sticker.json so each pack lists every id that exists (01..NN).

Usage:
  python3 publish_stickers.py            # write files + json
  python3 publish_stickers.py --dry-run  # report only
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

FIG_ROOT = Path("out/sticker-figma")
IMG_ROOT = Path("image")
JSON_PATH = Path("data/sticker.json")
BEST = 480
THUMB = BEST // 3
QUALITY = 86
METHOD = 4
WORKERS = 8
FIRST_NEW, LAST_NEW = 6, 20


def on_canvas(im: Image.Image, size: int) -> Image.Image:
    im = im.convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    return canvas


def write_one(args):
    f, dst_dir, dry = args
    best = on_canvas(Image.open(f), BEST)
    thumb = best.resize((THUMB, THUMB), Image.LANCZOS)
    if not dry:
        best.save(dst_dir / f"{f.stem}.webp", "WEBP", quality=QUALITY, method=METHOD)
        thumb.save(dst_dir / f"{f.stem}_thumb.webp", "WEBP", quality=QUALITY, method=METHOD)
    return 2


def render_json(data) -> str:
    """Write data/sticker.json in the repo's one-line-per-pack, column-aligned style."""
    max_id = max(len(p["id"]) for p in data["packs"])
    name_col = 13 + max_id + 3          # "    { "id": "…", " → 4 spaces + 9 + id + '",' + space
    stick_col = name_col + 28           # name column width
    lines = []
    for i, p in enumerate(data["packs"]):
        arr = '[' + ",".join(f'"{s}"' for s in p["stickers"]) + ']'
        head = f'    {{ "id": "{p["id"]}",'.ljust(name_col)
        mid = f'"name": "{p["name"]}",'.ljust(stick_col - name_col)
        tail = f'"stickers": {arr} }}' + ("," if i < len(data["packs"]) - 1 else "")
        lines.append(head + mid + tail)
    return '{\n  "version": "%s",\n  "packs": [\n%s\n  ]\n}\n' % (
        data["version"], "\n".join(lines))


def main():
    dry = "--dry-run" in sys.argv
    packs = sorted(p.name for p in FIG_ROOT.iterdir() if p.is_dir())
    jobs = []
    for pack in packs:
        src_dir = FIG_ROOT / pack
        dst_dir = IMG_ROOT / pack.lower()
        if not dst_dir.is_dir():
            print(f"  SKIP {pack}: missing repo dir {dst_dir}")
            continue
        for f in sorted(src_dir.glob("*.png")):
            n = int(f.stem)
            if n >= FIRST_NEW:
                jobs.append((f, dst_dir, dry))
    written = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for n in ex.map(write_one, jobs):
            written += n
    print(f"packs={len(packs)} files_written={written}{' (dry)' if dry else ''}")

    data = json.loads(JSON_PATH.read_text())
    changed = 0
    for p in data["packs"]:
        nums = sorted(int(f.stem) for f in (IMG_ROOT / p["id"]).glob("*.webp")
                      if not f.stem.endswith("_thumb"))
        if nums and nums == list(range(1, len(nums) + 1)) and len(nums) >= FIRST_NEW:
            ids = [f"{n:02d}" for n in nums]
            if p["stickers"] != ids:
                p["stickers"] = ids
                changed += 1
    if not dry and changed:
        JSON_PATH.write_text(render_json(data))
    print(f"json packs updated={changed} (total {len(data['packs'])} packs)")


if __name__ == "__main__":
    main()
