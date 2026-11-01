#!/usr/bin/env python3
"""Generate 10 extra stickers for each given pack, cut out, resize for Figma.

Reads pack ids from argv (e.g. ST-06 ST-07). Produces:
  out/sticker-new/<pack>/01..10.png      (full-res, transparent)
  out/sticker-figma/<pack>/06..15.png    (480px, for Figma insertion)

Rules (AGENTS.md): keep only the final transparent PNG of generation.
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image

from despill_edges import analyse, despill, GREEN_INTERIOR_LIMIT

BASE = "http://127.0.0.1:18610"
KEY = "dummy"
REMOVE_BG = ".claude/skills/app-asset-generator/scripts/remove_bg.py"
NEW_ROOT = Path("out/sticker-new")
FIG_ROOT = Path("out/sticker-figma")
REPO_IMAGE = Path("image")
USE_REFS = os.environ.get("STICKER_REFS", "1") != "0"
POLL = 3.0
TIMEOUT = 420.0
MAX_WORKERS = int(os.environ.get("STICKER_CONCURRENCY", "4"))
MAX_ATTEMPTS = 4

# style, key mode, subjects(10)
P = {
 "ST-06-coffee": ("Soft 3D clay kawaii sticker", "green",
   ["latte cup","croissant","coffee beans","latte art heart","takeaway cup","espresso machine","cinnamon roll","milk carton","teapot","macaron"]),
 "ST-07-fruit": ("Soft 3D clay kawaii sticker", "green",
   ["strawberry","cherries","peach","lemon","watermelon slice","pineapple","blueberry","kiwi","orange slice","grapes"]),
 "ST-08-weather": ("Soft 3D clay kawaii sticker", "green",
   ["rain cloud","rainbow","smiling sun","raindrop","lightning bolt","snowflake","tornado","sun behind cloud","umbrella","thermometer"]),
 "ST-09-ocean": ("Soft 3D clay kawaii sticker", "green",
   ["scallop shell","starfish","ocean wave","pearl oyster","seahorse","jellyfish","coral branch","tropical fish","crab","anchor"]),
 "ST-10-space": ("Soft 3D clay kawaii sticker", "green",
   ["rocket","ufo","astronaut cat","saturn","crescent moon","star cluster","planet earth","comet","satellite","spiral galaxy"]),
 "ST-11-cute-animals": ("Soft 3D clay kawaii sticker", "green",
   ["cat","bunny","bear","duck","frog","panda","fox","koala","pig","chick"]),
 "ST-12-love": ("Soft 3D clay kawaii sticker", "green",
   ["heart","cupid arrow","love letter","two hearts","sparkle heart","rose","cupid","wedding ring","love birds","heart balloon"]),
 "ST-13-sparkle": ("Soft 3D clay kawaii sticker", "green",
   ["sparkle","gem","star cluster","glitter trail","diamond","magic wand","shooting star","crystal","twinkle stars","disco ball"]),
 "ST-14-dark-coquette": ("Dark coquette gothic 3D sticker with deep burgundy and black lace tones", "green",
   ["bat","black heart","lace bow","cross","crescent moon","skull","spider","rose","candle","moth"]),
 "ST-15-skate-street": ("Bold graffiti skate-street sticker with punk colors and thick outlines", "green",
   ["skull","flame","lightning bolt","spiked star","broken heart","spray can","skateboard","anarchy star","bandaid","boom box"]),
 "ST-16-doodle-ink": ("Hand-drawn doodle ink sticker with black line art", "green",
   ["arrow","squiggle","star","underline","burst","spiral","flower doodle","heart doodle","lightning doodle","cloud doodle"]),
 "ST-17-pixel-8-bit": ("Retro pixel art 8-bit sticker", "green",
   ["heart","star","potion","sword","coin","mushroom","ghost","gem","key","slime"]),
 "ST-18-chrome-blob": ("Liquid chrome blob Y2K sticker", "green",
   ["blob","bubble","chrome heart","drop","sphere","chrome star","chrome flower","chrome skull","chrome wings","chrome smiley"]),
 "ST-19-storybook": ("Cozy storybook watercolor illustration sticker", "green",
   ["mushroom house","acorn","snail","leaf boat","lantern","owl","cottage","frog prince","teacup","book"]),
 "ST-20-line-icon": ("Minimal line icon sticker with single-weight strokes", "green",
   ["smiley","flower","heart","sun","cloud","star","moon","leaf","arrow","sparkle"]),
 "ST-21-seasonal": ("Soft 3D clay kawaii sticker", "green",
   ["autumn leaf","snowflake","spring blossom","summer sun","pumpkin","pinecone","cherry blossom","maple leaf","raindrop","sun"]),
 "ST-22-tet": ("Soft 3D clay kawaii Vietnamese Tet sticker", "green",
   ["apricot blossom","red envelope","lantern","kumquat","peach blossom","firecracker","gold coin","bamboo","tangerine","lion dance"]),
 "ST-23-christmas": ("Soft 3D clay kawaii Christmas sticker", "green",
   ["christmas tree","santa hat","candy cane","stocking","snowman","gift box","reindeer","ornament ball","star","gingerbread"]),
 "ST-24-mid-autumn": ("Soft 3D clay kawaii Mid-Autumn festival sticker", "green",
   ["mooncake","lantern","rabbit","full moon","lotus","osmanthus","jade rabbit","tea cup","star","cloud"]),
 "ST-25-birthday": ("Soft 3D clay kawaii birthday sticker", "green",
   ["birthday cake","balloon","gift","party hat","confetti","candle","cupcake","party popper","banner","present"]),
 "ST-26-partner": ("Soft 3D clay kawaii romantic sticker", "green",
   ["heart hands","couple rings","love letter","promise heart","teddy bear","rose","heart balloon","lock and key","couple mug","sparkle heart"]),
 "ST-27-friends-family": ("Soft 3D clay kawaii friendship sticker", "green",
   ["two hearts","group hug","friendship bracelet","high five","family","handshake","heart chain","photo frame","sparkle friends","cheers"]),
 "ST-28-just-me": ("Soft 3D clay kawaii self-care sticker", "green",
   ["mirror","self care","coffee me time","book","bubble bath","yoga","journal","plant","candle","spa"]),
 "ST-29-mood": ("Soft 3D clay kawaii emoji sticker", "green",
   ["happy smiley","sad face","angry face","sleepy face","love eyes","cool sunglasses","crying face","surprised face","wink face","blush face"]),
 "ST-30-pets": ("Soft 3D clay kawaii sticker", "green",
   ["dog","cat","hamster","rabbit","parrot","fish","turtle","guinea pig","puppy","kitten"]),
 "ST-31-places": ("Soft 3D clay kawaii sticker", "green",
   ["house","mountain","beach","city","forest","lighthouse","bridge","cafe","park","temple"]),
 "ST-32-travel": ("Soft 3D clay kawaii sticker", "green",
   ["airplane","suitcase","passport","map pin","camera","beach umbrella","compass","globe","ticket","backpack"]),
 "ST-33-vietnam": ("Soft 3D clay kawaii Vietnamese sticker", "green",
   ["lotus","conical hat","rice field","pho bowl","lantern","ao dai","dragon","bamboo","coffee","motorbike"]),
 "ST-34-food": ("Soft 3D clay kawaii sticker", "green",
   ["pizza slice","burger","sushi","ramen bowl","taco","ice cream","fries","hot dog","popcorn","dumpling"]),
 "ST-35-cafe": ("Soft 3D clay kawaii sticker", "green",
   ["coffee cup","latte art","croissant","cake slice","teapot","macaron","cafe sign","menu","cupcake","milk"]),
 "ST-36-weather": ("Soft 3D clay kawaii sticker", "green",
   ["rain cloud","rainbow","smiling sun","raindrop","lightning bolt","snowflake","tornado","sun behind cloud","umbrella","thermometer"]),
 "ST-37-plants": ("Soft 3D clay kawaii plant sticker", "magenta",
   ["monstera leaf","cactus","fern","succulent","tulip","sunflower","bonsai","ivy","palm leaf","flowerpot"]),
 "ST-38-sea": ("Soft 3D clay kawaii sticker", "green",
   ["wave","shell","starfish","jellyfish","seahorse","coral","fish","pearl","anchor","crab"]),
 "ST-39-space": ("Soft 3D clay kawaii sticker", "green",
   ["rocket","ufo","astronaut cat","saturn","moon","star cluster","planet earth","comet","satellite","galaxy"]),
 "ST-40-hobby": ("Soft 3D clay kawaii sticker", "green",
   ["paint palette","guitar","camera","book","knitting","plant","game controller","chess","cooking","photography"]),
 "ST-41-music": ("Soft 3D clay kawaii sticker", "green",
   ["music note","headphones","vinyl record","guitar","microphone","boombox","cassette","piano keys","speaker","drum"]),
 "ST-42-sport": ("Soft 3D clay kawaii sticker", "green",
   ["basketball","soccer ball","tennis racket","dumbbell","trophy","bicycle","skateboard","boxing glove","whistle","medal"]),
 "ST-43-study": ("Soft 3D clay kawaii sticker", "green",
   ["book","pencil","notebook","graduation cap","lightbulb","ruler","backpack","apple","paperclip","calculator"]),
 "ST-44-beauty": ("Soft 3D clay kawaii sticker", "green",
   ["lipstick","nail polish","perfume","mirror","flower","sparkle","face cream","makeup brush","eyeshadow palette","diamond"]),
}
KEY = {"green": ("green", "#00FF00"), "magenta": ("magenta", "#FF00FF")}


def api(method, url, payload=None, timeout=60):
    data = None
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def build(style, keymode, subj):
    kn, hx = KEY[keymode]
    return (f"{style} of a cute {subj}, single subject centered and fully visible with a clean "
            f"12 percent empty margin on every side, crisp clean edges, solid flat uniform pure "
            f"{kn} {hx} background filling the entire frame, seamless clean render")


def download(item):
    if "b64_json" in item:
        return base64.b64decode(item["b64_json"])
    with urllib.request.urlopen(item["url"], timeout=120) as r:
        return r.read()


def resize_for_figma(src: Path, dst: Path):
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    s = 480 / max(w, h)
    if s < 1:
        im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, optimize=True)


def clean_spill(path: Path):
    """Kill chroma-key green cast on the cut-out edge band (skips green subjects)."""
    try:
        in_frac, band_frac = analyse(path)
        if in_frac < GREEN_INTERIOR_LIMIT and band_frac > 0.08:
            despill(path)
    except Exception as e:
        print(f"  SPILLSKIP {path}: {e}", flush=True)


REF_CACHE: dict = {}


def pack_refs(pack_id, limit=4):
    """Data URLs of the pack's existing stickers (image/<pack>/01..05.webp) for style reference."""
    key = (pack_id, limit)
    if key in REF_CACHE:
        return REF_CACHE[key]
    repo_dir = REPO_IMAGE / pack_id.lower()
    refs = []
    for n in range(1, 6):
        src = repo_dir / f"{n:02d}.webp"
        if not src.is_file() or len(refs) >= limit:
            continue
        im = Image.open(src).convert("RGBA")
        im.thumbnail((512, 512), Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, "PNG", optimize=True)
        refs.append("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode())
    REF_CACHE[key] = refs
    return refs


def run_job(pack_id, style, keymode, i, subj):
    pdir = NEW_ROOT / pack_id
    pdir.mkdir(parents=True, exist_ok=True)
    final = pdir / f"{i:02d}.png"
    fig = FIG_ROOT / pack_id / f"{5+i:02d}.png"
    if final.exists() and fig.exists() and not USE_REFS:
        clean_spill(final)
        clean_spill(fig)
        return True
    prompt = build(style, keymode, subj)
    refs = pack_refs(pack_id) if USE_REFS else []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            payload = {"prompt": prompt, "size": "1:1", "n": 1, "async": True}
            if refs:
                payload["image"] = refs
            tid = api("POST", f"{BASE}/v1/images/generations", payload)["id"]
            started = time.monotonic()
            while True:
                t = api("GET", f"{BASE}/v1/images/generations/{tid}")
                st = t.get("status")
                if st == "succeeded":
                    raw = Path(f"/tmp/raw_{pack_id}_{i:02d}_{attempt}.webp")
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
                        print(f"  OK   {pack_id} {i:02d} {subj}", flush=True)
                        return True
                    break
                if st in ("failed", "cancelled"):
                    print(f"  GENFAIL {pack_id} {i:02d} t{attempt}: {t.get('error')}", flush=True)
                    break
                if time.monotonic() - started > TIMEOUT:
                    print(f"  TIMEOUT {pack_id} {i:02d} t{attempt}", flush=True)
                    break
                time.sleep(POLL)
        except Exception as e:
            print(f"  ERR {pack_id} {i:02d} t{attempt}: {e}", flush=True)
        time.sleep(4 * attempt)
    print(f"  GAVEUP {pack_id} {i:02d} {subj}", flush=True)
    return False


def main():
    ids = sys.argv[1:]
    jobs = []
    for pid in ids:
        if pid not in P:
            print(f"unknown pack {pid}", flush=True)
            continue
        style, keymode, subs = P[pid]
        for i, subj in enumerate(subs, 1):
            jobs.append((pid, style, keymode, i, subj))
    print(f"jobs: {len(jobs)} concurrency={MAX_WORKERS}", flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(run_job, *j) for j in jobs]
        for f in futs:
            if f.result():
                ok += 1
    print(f"GROUP DONE ok={ok}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
