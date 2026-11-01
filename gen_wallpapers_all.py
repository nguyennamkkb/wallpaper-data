#!/usr/bin/env python3
"""Generate 10 extra images for each wallpaper pack, matching the pack's existing samples.

Per pack: 4 existing images (image/<pack>/01..04.webp) are sent as style references,
plus a description of the new shot kept distinct from the 5 shots the pack already has.
No background removal — full-bleed photographic art.

Output: out/wp-new/<pack>/01..10.webp (1000x1000) + 01..10_thumb.webp (333x333)

Usage: python3 gen_wallpapers_all.py wp-01-golden-hour wp-02-misty-mountain
       python3 gen_wallpapers_all.py all
Resumable: existing outputs are skipped.
"""
import base64
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image

BASE = "http://127.0.0.1:18610"
KEY = "dummy"
REPO_IMAGE = Path("image")
OUT_ROOT = Path("out/wp-new")
BEST = 1000
THUMB = BEST // 3
QUALITY = 86
METHOD = 4
POLL = 3.0
TIMEOUT = 420.0
MAX_ATTEMPTS = 4
MAX_WORKERS = int(os.environ.get("WP_CONCURRENCY", "4"))
REF_LIMIT = int(os.environ.get("WP_REFS", "4"))

BASE_PROMPT = ("{style}. {shot}. Square 1:1 wallpaper, edge-to-edge composition filling the whole "
               "frame, no text, no watermark, no border, no frame, high detail, natural clean rendering")

# style  | 10 shot descriptions, each DIFFERENT from the pack's existing 5
P = {
 "wp-01-golden-hour": ("Warm golden-hour landscape photograph, low sun, amber rim light and soft haze", [
   "dusty country road at sunset with warm light between trees",
   "old wooden fence in a golden field, long shadows",
   "sunlit orchard rows fading into warm haze",
   "rope swing hanging from a tree at golden hour",
   "sunflower field facing a low warm sun",
   "hay bales scattered across a sunlit field",
   "windmill silhouette against an amber sky",
   "river bend with glowing sunlit banks",
   "backlit autumn tree alone on a hill",
   "warm bokeh of grass seeds against the low sun"]),
 "wp-02-misty-mountain": ("Moody layered mountain landscape photograph, cool blue fog, low contrast depth", [
   "stone hut on a foggy alpine meadow",
   "mist drifting through a pine ridge",
   "rope bridge crossing a fog filled gorge",
   "waterfall dropping into a misty basin",
   "mountain road with guardrail at dusk",
   "rocky summit above a low sea of clouds",
   "cold blue glacier tongue between peaks",
   "mountain lake shore with stones in fog",
   "fog rolling over a forested hillside at dawn",
   "distant ridgeline under heavy clouds"]),
 "wp-03-ocean-coast": ("Editorial seascape photograph, ocean and coastline, natural light and texture", [
   "pebble beach with wet stones and gentle surf",
   "cliff path above a turquoise bay",
   "harbor pier posts on a calm morning",
   "seagulls over breaking waves",
   "rock pool with clear water and shells",
   "long sand spit curving into blue water",
   "sea foam rings on dark sand seen from above",
   "lighthouse on a rocky headland",
   "empty surf beach at low tide",
   "backlit wave crest with spray"]),
 "wp-04-desert-dunes": ("Desert landscape photograph, warm sand tones, sculpted dunes, deep shadows", [
   "lone dead tree in cracked desert ground",
   "sandstone slot canyon with a light beam",
   "desert mesa at sunset, layered rock",
   "thorn shrubs on dry dunes",
   "wind blown sand spray off a dune crest",
   "star dune at sunrise with a sharp ridge",
   "dry riverbed stones under harsh light",
   "sand pattern lines with a small pebble",
   "desert mountains behind a flat sand plain",
   "warm dune silhouette against a pale sky"]),
 "wp-05-forest-light": ("Atmospheric woodland photograph, sun shafts through trees, mossy green detail", [
   "forest stream running over mossy stones",
   "sunlit clearing with tall wild grass",
   "fallen tree bark texture close-up",
   "mushrooms on a mossy log",
   "canopy seen from below with light gaps",
   "narrow trail between tall trunks",
   "dew on a spiderweb between ferns",
   "dark pine forest pierced by a light beam",
   "autumn leaves floating in a forest pool",
   "exposed roots on a forest bank"]),
 "wp-06-night-sky": ("Night sky astrophotography, stars and dark landscape silhouettes, deep blue tones", [
   "star trails circling above a lone tree",
   "galaxy core over desert dunes",
   "shooting star streak above a forest",
   "moonlit clouds over a quiet lake",
   "night sky reflected in wet sand",
   "silhouetted pines under dense stars",
   "deep purple night gradient with faint stars",
   "zodiacal light above a mountain silhouette",
   "stars above snow covered peaks",
   "bright full moon with thin clouds"]),
 "wp-07-soft-gradient": ("Abstract soft gradient artwork, smooth color mesh, no objects, silky blends", [
   "sage green fading into ivory",
   "coral blending into buttercream",
   "powder blue meeting pale sand",
   "mauve gradient wash into greige",
   "aqua fading into soft lemon",
   "rose quartz gradient with subtle noise",
   "midnight blue blending into dusty pink",
   "olive gradient into cream",
   "apricot diagonal gradient into lilac",
   "mint vertical gradient into white"]),
 "wp-08-liquid-glass": ("Minimal liquid glass artwork, one clean translucent glass form, soft studio light, uncluttered pastel space", [
   "glass sphere refracting a striped backdrop",
   "water caustics playing on a wall",
   "translucent gel sheet with a soft shadow",
   "droplets beaded on a clear panel",
   "bent glass tube with light inside",
   "frozen soap film with rainbow edges",
   "liquid metal droplet on a matte surface",
   "clear resin block with bright inclusions",
   "glass shards scattered on a pale gradient",
   "prism splitting light on a soft surface"]),
 "wp-09-paper-grain": ("Minimal paper texture photograph, a single sheet of paper filling the frame, natural fiber grain, soft even studio light, no objects", [
   "folded paper with a soft shadow crease",
   "deckled edge paper on gray",
   "recycled pulp texture with flecks",
   "embossed blind stamp on thick card",
   "stack of paper seen edge-on",
   "watercolor paper tooth macro",
   "brown kraft envelope corner",
   "paper fibers lit from the side",
   "creased tracing paper over light",
   "off white card with a fine grain"]),
 "wp-10-minimal-geometry": ("Minimal geometric composition, flat shapes, restrained palette, studio light", [
   "two overlapping circles in muted tones",
   "stacked rectangles in warm neutrals",
   "triangle with a soft gradient fill",
   "thin line grid over beige",
   "half circle rising from a flat horizon",
   "small dot matrix on cream",
   "quarter circle shadow study",
   "three spheres casting soft shadows",
   "diagonal split of two pastel colors",
   "concentric rings in sand tones"]),
 "wp-11-floral-macro": ("Floral macro photograph, petals and detail, natural soft light", [
   "peony petals in soft window light",
   "dried lavender bundle close-up",
   "sunflower center spiral detail",
   "lily stamen and pollen macro",
   "hydrangea cluster in muted blue",
   "poppy petals against a dark background",
   "eucalyptus branches on cream",
   "cherry blossom branch in soft focus",
   "dahlia layered petals from above",
   "freesia blooms with shallow depth"]),
 "wp-12-rain-window": ("Rain on glass photograph, water droplets, blurred lights, moody atmosphere", [
   "rain on a car windshield with bokeh",
   "condensation running down a dark pane",
   "rain hitting a metal railing",
   "umbrella edge in the rain",
   "wet cobblestone street at night",
   "rain rings spreading in a puddle",
   "window with a tree silhouette and rain",
   "splashes on a glass table top",
   "fogged mirror with droplet trails",
   "raindrops beaded on a leaf"]),
 "wp-13-city-dusk": ("Urban skyscape photograph at dusk, blue hour light, city detail", [
   "glass towers reflecting a violet sky",
   "street lamps in blue hour fog",
   "parking garage roof view at dusk",
   "river promenade with city lights",
   "foggy skyline at dawn, muted tones",
   "subway entrance lights at dusk",
   "balcony view of distant towers",
   "awning lights on a quiet street",
   "skyline seen from a hill at twilight",
   "skyscraper facades in cold blue light"]),
 "wp-14-snow-winter": ("Winter landscape photograph, snow and ice, cool clean light", [
   "snow covered pine forest",
   "footprints in fresh powder",
   "icicles hanging from a roof edge",
   "winter cabin with warm window light",
   "snow drift with a wind pattern",
   "frozen bubbles in ice macro",
   "bare birch trunks standing in snow",
   "snowy field with a fence line",
   "mountain hut in blowing snow",
   "cold morning fog over snow"]),
 "wp-15-autumn": ("Autumn landscape photograph, warm foliage, low golden light", [
   "pumpkin patch in warm light",
   "acorns and leaves on the ground",
   "autumn lake with reflected color",
   "red vine wall on a stone house",
   "wet leaves on dark asphalt",
   "chestnuts in their husks",
   "autumn branch against a gray sky",
   "hay bales in a harvested field",
   "foggy orchard at sunrise",
   "single leaf floating on water"]),
 "wp-16-tropical": ("Tropical photograph, lush greens and turquoise water, bright natural light", [
   "jungle waterfall over wet rocks",
   "palm trees leaning over white sand",
   "coconut resting on sand",
   "tropical rain on broad leaves",
   "shallow reef with coral shapes from above",
   "sunset over a calm tropical bay",
   "bamboo grove with filtered sun",
   "hammock between palms at the beach",
   "turquoise water meeting volcanic rocks",
   "fern and moss in humid shade"]),
 "wp-17-watercolor": ("Abstract watercolor artwork, soft pigment blooms on paper, organic edges", [
   "loose blue brushstrokes on cream",
   "wet-on-wet green washes",
   "terracotta pigment pool on paper",
   "fine ink lines over a wash",
   "watercolor horizon with a soft bleed",
   "salt texture watercolor effect",
   "layered indigo washes",
   "ochre and cream watercolor blend",
   "soft floral watercolor shapes",
   "abstract watercolor clouds in gray"]),
 "wp-18-silk-fabric": ("Fabric and silk photograph, folds and sheen, studio lighting", [
   "ribbed knit wool close-up",
   "chiffon fabric floating in air",
   "denim weave macro in blue",
   "quilted fabric with soft shadow",
   "organza layers in pastel light",
   "knotted rope texture on canvas",
   "burlap texture in natural tones",
   "silk scarf edge with fringe",
   "pleated fabric fanning out",
   "embroidered floral detail on cloth"]),
 "wp-19-terrazzo-confetti": ("Terrazzo and confetti pattern artwork, playful chips and speckles, flat studio light", [
   "colorful paper confetti flat lay",
   "marble chips in a dark matrix",
   "pastel terrazzo floor pattern",
   "glitter scatter on a matte surface",
   "mosaic tiles with grout lines",
   "cork texture with flecks",
   "speckled ceramic surface",
   "cut paper shapes overlapping",
   "seeds scattered on light fabric",
   "stone chips suspended in resin"]),
 "wp-20-aurora-light-leak": ("Aurora and film light-leak artwork, glowing color gradients, cinematic grain", [
   "aurora over a frozen lake",
   "green aurora curtain above peaks",
   "film burn edges in warm orange",
   "lens flare streaks across a dark sky",
   "purple aurora reflected on water",
   "double exposed light leak over a landscape",
   "soft red leak across a night sky",
   "out of focus violet bokeh lights",
   "sunset flare through tree branches",
   "light streak across a gradient sky"]),
}

REF_CACHE: dict = {}


def api(method, url, payload=None, timeout=60):
    data = None
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def pack_refs(pack_id, limit=4):
    if pack_id in REF_CACHE:
        return REF_CACHE[pack_id]
    refs = []
    for n in range(1, 6):
        src = REPO_IMAGE / pack_id / f"{n:02d}.webp"
        if not src.is_file() or len(refs) >= limit:
            continue
        im = Image.open(src).convert("RGB")
        im.thumbnail((512, 512), Image.LANCZOS)
        buf = BytesIO()
        im.save(buf, "JPEG", quality=92)
        refs.append("data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode())
    REF_CACHE[pack_id] = refs
    return refs


def download(item):
    if "b64_json" in item:
        return base64.b64decode(item["b64_json"])
    with urllib.request.urlopen(item["url"], timeout=120) as r:
        return r.read()


def save_wallpaper(raw_bytes, pack_id, i):
    out_dir = OUT_ROOT / pack_id
    out_dir.mkdir(parents=True, exist_ok=True)
    im = Image.open(BytesIO(raw_bytes)).convert("RGB")
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
    im = im.resize((BEST, BEST), Image.LANCZOS)
    im.save(out_dir / f"{i:02d}.webp", "WEBP", quality=QUALITY, method=METHOD)
    im.resize((THUMB, THUMB), Image.LANCZOS).save(
        out_dir / f"{i:02d}_thumb.webp", "WEBP", quality=QUALITY, method=METHOD)


def run_job(pack_id, style, shot, i):
    out_dir = OUT_ROOT / pack_id
    best = out_dir / f"{i:02d}.webp"
    thumb = out_dir / f"{i:02d}_thumb.webp"
    if best.exists() and thumb.exists():
        return True
    prompt = BASE_PROMPT.format(style=style, shot=shot)
    refs = pack_refs(pack_id, REF_LIMIT) if REF_LIMIT > 0 else []
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
                    save_wallpaper(download(t["result"]["data"][0]), pack_id, i)
                    print(f"  OK   {pack_id} {i:02d} {shot[:44]}", flush=True)
                    return True
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
    print(f"  GAVEUP {pack_id} {i:02d} {shot[:44]}", flush=True)
    return False


def main():
    args = sys.argv[1:]
    if not args or args == ["all"]:
        args = list(P)
    jobs = []
    for pid in args:
        if pid not in P:
            print(f"unknown pack {pid}", flush=True)
            continue
        style, shots = P[pid]
        for i, shot in enumerate(shots, 1):
            jobs.append((pid, style, shot, i))
    print(f"packs={len(args)} jobs={len(jobs)} concurrency={MAX_WORKERS}", flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(run_job, *j) for j in jobs]
        for f in futs:
            if f.result():
                ok += 1
    print(f"GROUP DONE ok={ok}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    main()
