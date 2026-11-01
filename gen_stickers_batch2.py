#!/usr/bin/env python3
"""Batch 2: generate 5 more stickers per pack (numbering 16..20), same pipeline as batch 1.

Reference images = image/<pack>/01..04.webp, chromakey cut, despill, 480px for Figma.

Usage: python3 gen_stickers_batch2.py st-01-kawaii-3d        # test one pack
       python3 gen_stickers_batch2.py all
Concurrency: STICKER_CONCURRENCY (default 2). Resumable.
"""
import base64
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

from gen_stickers_all import (FIG_ROOT, NEW_ROOT, REF_CACHE, api, build, clean_spill,
                              download, resize_for_figma, MAX_ATTEMPTS, POLL, TIMEOUT)
from pathlib import Path as _P
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
import os

REMOVE_BG = ".claude/skills/app-asset-generator/scripts/remove_bg.py"
REPO_IMAGE = _P("image")
OFFSET = 15                      # 01..05 -> 16
WORKERS = int(os.environ.get("STICKER_CONCURRENCY", "2"))
REF_LIMIT = int(os.environ.get("STICKER_REFS", "4"))

# style overrides for packs that batch 1 did not generate (ST-01..05)
STYLE = {
 "st-01-kawaii-3d": ("Soft 3D clay kawaii sticker", "green"),
 "st-02-retro-70s": ("Retro 70s groovy sticker with a warm earthy palette and rounded shapes", "green"),
 "st-03-y2k-chrome": ("Y2K chrome liquid metal sticker with iridescent highlights", "green"),
 "st-04-botanical": ("Soft 3D clay botanical sticker", "magenta"),
 "st-05-celestial": ("Soft 3D clay celestial sticker", "green"),
}

# 5 new subjects per pack (different from the pack's existing 15)
S = {
 "st-01-kawaii-3d": ["ladybug", "cupcake", "party balloon", "tulip flower", "planet with ring"],
 "st-02-retro-70s": ["smiley flower", "peace sign", "vinyl record", "sunset stripes", "roller skate"],
 "st-03-y2k-chrome": ["chrome star", "butterfly", "y2k phone", "chrome smiley", "bubble"],
 "st-04-botanical": ["eucalyptus sprig", "ginkgo leaves", "willow branch", "lavender", "cherry blossom branch"],
 "st-05-celestial": ["moon phases", "star cluster", "solar eclipse ring", "nebula cloud", "zodiac wheel"],

 "st-06-coffee": ["iced coffee glass", "french press", "coffee grinder", "affogato sundae", "coffee dripper"],
 "st-07-fruit": ["mango", "banana bunch", "pear", "pomegranate", "dragon fruit"],
 "st-08-weather": ["hail stones", "wind sock", "fog bank", "sun halo", "weather vane"],
 "st-09-ocean": ["whale tail", "sand dollar", "sea turtle", "message in a bottle", "coral reef cluster"],
 "st-10-space": ["telescope", "black hole", "meteor shower", "space helmet", "star map"],
 "st-11-cute-animals": ["hedgehog", "otter", "sloth", "red panda", "penguin"],
 "st-12-love": ["chocolate box", "heart locket", "candy hearts", "love potion bottle", "heart shaped cake"],
 "st-13-sparkle": ["star earring", "glitter jar", "prism", "sequin", "aurora orb"],
 "st-14-dark-coquette": ["coffin", "raven", "lace gloves", "poison bottle", "antique key"],
 "st-15-skate-street": ["chain", "graffiti crown", "skater helmet", "paint splat", "arrow tag"],
 "st-16-doodle-ink": ["scribble face", "wavy lines", "marker pen", "sketch eye", "doodle sun"],
 "st-17-pixel-8-bit": ["pixel cat", "pixel cake", "pixel cloud", "pixel flag", "pixel bomb"],
 "st-18-chrome-blob": ["chrome ribbon", "chrome lips", "chrome butterfly", "chrome ring", "chrome dice"],
 "st-19-storybook": ["picnic basket", "hedgehog traveler", "map scroll", "windmill", "berry basket"],
 "st-20-line-icon": ["camera", "coffee cup", "house", "key", "music note"],
 "st-21-seasonal": ["snowman", "beach ball", "rain boots", "ice cream cone", "kite"],
 "st-22-tet": ["chung cake", "five fruit tray", "incense sticks", "red lantern string", "tet couplet"],
 "st-23-christmas": ["wreath", "mistletoe", "sleigh", "bells", "snow globe"],
 "st-24-mid-autumn": ["moon rabbit lantern", "star fruit", "grapefruit", "mooncake box", "festival drum"],
 "st-25-birthday": ["pinata", "party blower", "number candle", "cake slice", "photo booth props"],
 "st-26-partner": ["heart necklace", "couple selfie", "love coupon", "anniversary cake", "starlit promise"],
 "st-27-friends-family": ["best friend necklaces", "sleepover pillow", "group photo", "friendship pin", "piggyback"],
 "st-28-just-me": ["face mask", "sunset walk", "headphones chill", "skincare bottle", "warm blanket"],
 "st-29-mood": ["neutral face", "confused face", "silly tongue face", "star eyes", "shy face"],
 "st-30-pets": ["dog leash", "cat bed", "hamster wheel", "bird cage", "pet collar"],
 "st-31-places": ["desert", "waterfall", "stadium", "school", "harbor"],
 "st-32-travel": ["train", "boat", "map", "hotel key", "sunglasses"],
 "st-33-vietnam": ["banh mi", "cyclo", "incense village", "water puppet", "basket boat"],
 "st-34-food": ["salad bowl", "pancake stack", "waffle", "noodle cup", "burrito"],
 "st-35-cafe": ["cold brew", "cake stand", "sugar bowl", "cafe window", "wifi sign"],
 "st-36-weather": ["frost pattern", "sandstorm", "fog bank", "sun halo", "dust devil"],
 "st-37-plants": ["orchid", "lily", "pothos", "aloe vera", "bamboo shoot"],
 "st-38-sea": ["whale", "dolphin", "seaweed", "sand dollar", "message bottle"],
 "st-39-space": ["telescope", "black hole", "space helmet", "meteor", "star map"],
 "st-40-hobby": ["paint brush", "yarn ball", "puzzle piece", "fishing rod", "dice"],
 "st-41-music": ["trumpet", "saxophone", "violin", "harp", "music stand"],
 "st-42-sport": ["volleyball", "baseball", "swimming goggles", "running shoe", "jump rope"],
 "st-43-study": ["globe", "eraser", "protractor", "sticky notes", "hourglass"],
 "st-44-beauty": ["hair brush", "nail file", "eyeliner", "hand cream", "hair clip"],
}


def pack_refs(pack_id, limit=4):
    key = ("refs", pack_id, limit)
    if key in REF_CACHE:
        return REF_CACHE[key]
    refs = []
    for n in range(1, 6):
        src = REPO_IMAGE / pack_id / f"{n:02d}.webp"
        if not src.is_file() or len(refs) >= limit:
            continue
        im = Image.open(src).convert("RGBA")
        im.thumbnail((512, 512), Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, "PNG", optimize=True)
        refs.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    REF_CACHE[key] = refs
    return refs


def run_job(pack_id, style, keymode, idx, subj):
    pdir = NEW_ROOT / pack_id
    pdir.mkdir(parents=True, exist_ok=True)
    final = pdir / f"{idx:02d}.png"
    fig = FIG_ROOT / pack_id / f"{idx:02d}.png"
    if final.exists() and fig.exists():
        return True
    prompt = build(style, keymode, subj)
    refs = pack_refs(pack_id, REF_LIMIT) if REF_LIMIT > 0 else []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            payload = {"prompt": prompt, "size": "1:1", "n": 1, "async": True}
            if refs:
                payload["image"] = refs
            tid = api("POST", "http://127.0.0.1:18610/v1/images/generations", payload)["id"]
            started = time.monotonic()
            while True:
                t = api("GET", f"http://127.0.0.1:18610/v1/images/generations/{tid}")
                st = t.get("status")
                if st == "succeeded":
                    raw = _P(f"/tmp/raw2_{pack_id}_{idx}.webp")
                    raw.write_bytes(download(t["result"]["data"][0]))
                    subprocess.run([sys.executable, REMOVE_BG, str(raw), "-o", str(final)],
                                   capture_output=True, text=True)
                    for p in pdir.glob(final.stem + "_*.png"):
                        p.unlink(missing_ok=True)
                    raw.unlink(missing_ok=True)
                    if final.exists():
                        clean_spill(final)
                        resize_for_figma(final, fig)
                        clean_spill(fig)
                        print(f"  OK   {pack_id} {idx:02d} {subj}", flush=True)
                        return True
                    break
                if st in ("failed", "cancelled"):
                    print(f"  GENFAIL {pack_id} {idx:02d} t{attempt}: {t.get('error')}", flush=True)
                    break
                if time.monotonic() - started > TIMEOUT:
                    print(f"  TIMEOUT {pack_id} {idx:02d} t{attempt}", flush=True)
                    break
                time.sleep(POLL)
        except Exception as e:
            print(f"  ERR {pack_id} {idx:02d} t{attempt}: {e}", flush=True)
        time.sleep(4 * attempt)
    print(f"  GAVEUP {pack_id} {idx:02d} {subj}", flush=True)
    return False


def main():
    from gen_stickers_all import P as P1
    styles = {k.lower(): (v[0], v[1]) for k, v in P1.items()}
    styles.update(STYLE)
    args = sys.argv[1:]
    if not args or args == ["all"]:
        args = list(S)
    jobs = []
    for pid in args:
        if pid not in S:
            print(f"unknown pack {pid}", flush=True)
            continue
        style, keymode = styles[pid.lower()]
        for j, subj in enumerate(S[pid]):
            jobs.append((pid, style, keymode, OFFSET + j + 1, subj))
    print(f"packs={len(args)} jobs={len(jobs)} concurrency={WORKERS}", flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(lambda j: run_job(*j), jobs):
            if r:
                ok += 1
    print(f"BATCH DONE ok={ok}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
