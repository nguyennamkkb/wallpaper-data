#!/usr/bin/env python3
"""Batch-generate extra stickers for packs: gen via muse2api -> cut out -> keep only final PNG.

Rules (AGENTS.md): after background removal keep ONLY the final transparent PNG.
Resumable: skips packs/stickers whose final PNG already exists.
Concurrency is capped (default 3) and failed generations are retried with backoff,
because the gateway returns 'all accounts are busy' under load.

Usage: python3 gen_stickers.py [pack_id ...]
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "http://127.0.0.1:18610"
KEY = "dummy"
REMOVE_BG = ".claude/skills/app-asset-generator/scripts/remove_bg.py"
OUTROOT = Path("out/sticker-new")
POLL = 3.0
TIMEOUT = 420.0
MAX_WORKERS = int(os.environ.get("STICKER_CONCURRENCY", "3"))
MAX_ATTEMPTS = 4

PACKS = [
    {
        "id": "st-01-kawaii-3d", "keyName": "green", "keyHex": "#00FF00",
        "style": "Soft 3D clay kawaii sticker",
        "subjects": ["star", "moon", "mushroom", "strawberry", "bunny",
                     "cat", "bear", "donut", "balloon", "butterfly"],
    },
    {
        "id": "st-02-retro-70s", "keyName": "green", "keyHex": "#00FF00",
        "style": "Flat vector retro 70s groovy sticker with bold rounded shapes and a warm sunset palette",
        "subjects": ["groovy heart", "peace sign", "rainbow", "flower power", "smiley face",
                     "mushroom", "sun", "daisy", "vinyl record", "retro van"],
    },
    {
        "id": "st-03-y2k-chrome", "keyName": "green", "keyHex": "#00FF00",
        "style": "Glossy Y2K chrome metallic 3D sticker with liquid silver reflective surface and iridescent highlights",
        "subjects": ["star", "butterfly", "heart", "flame", "alien face",
                     "smiley face", "dice", "lightning bolt", "compact disc", "yin yang"],
    },
    {
        "id": "st-04-botanical", "keyName": "magenta", "keyHex": "#FF00FF",
        "style": "Delicate flat botanical illustration sticker with fine clean line work and muted sage green tones",
        "subjects": ["leaf", "fern frond", "rose", "tulip", "monstera leaf",
                     "olive branch", "mushroom", "acorn", "pinecone", "wildflower"],
    },
    {
        "id": "st-05-celestial", "keyName": "green", "keyHex": "#00FF00",
        "style": "Dreamy 3D clay celestial sticker with soft gradients and tiny sparkles",
        "subjects": ["crescent moon", "star", "sun", "ringed planet", "comet",
                     "galaxy spiral", "constellation", "crystal", "mystic eye", "shooting star"],
    },
]


def api(method, url, payload=None, timeout=60):
    data = None
    headers = {"Authorization": f"Bearer {KEY}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def build(pack, subj):
    return (
        f"{pack['style']} of a cute {subj}, single subject centered and fully visible with a clean "
        f"12 percent empty margin on every side, crisp clean edges, solid flat uniform pure "
        f"{pack['keyName']} {pack['keyHex']} background filling the entire frame, seamless clean render"
    )


def download(item):
    if "b64_json" in item:
        return base64.b64decode(item["b64_json"])
    with urllib.request.urlopen(item["url"], timeout=120) as r:
        return r.read()


def run_job(pack, job):
    """Generate one sticker with retries; keep only final PNG."""
    i = job["i"]
    final = job["final"]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if final.exists():
            return True
        try:
            tid = api("POST", f"{BASE}/v1/images/generations",
                      {"prompt": job["prompt"], "size": "1:1", "n": 1, "async": True})["id"]
            started = time.monotonic()
            while True:
                t = api("GET", f"{BASE}/v1/images/generations/{tid}")
                status = t.get("status")
                if status == "succeeded":
                    data = download(t["result"]["data"][0])
                    raw = Path(f"/tmp/raw_{pack['id']}_{i:02d}_{attempt}.webp")
                    raw.write_bytes(data)
                    subprocess.run([sys.executable, REMOVE_BG, str(raw), "-o", str(final)],
                                   capture_output=True, text=True)
                    for p in final.parent.glob(final.stem + "_*.png"):
                        p.unlink(missing_ok=True)
                    raw.unlink(missing_ok=True)
                    if final.exists():
                        print(f"  OK   {pack['id']} {i:02d} {job['subj']} (try {attempt})", flush=True)
                        return True
                    print(f"  CUTFAIL {pack['id']} {i:02d} (try {attempt})", flush=True)
                    break
                if status in ("failed", "cancelled"):
                    print(f"  GENFAIL {pack['id']} {i:02d} try{attempt}: {t.get('error')}", flush=True)
                    break
                if time.monotonic() - started > TIMEOUT:
                    print(f"  TIMEOUT {pack['id']} {i:02d} try{attempt}", flush=True)
                    break
                time.sleep(POLL)
        except Exception as e:
            print(f"  ERR {pack['id']} {i:02d} try{attempt}: {e}", flush=True)
        time.sleep(4 * attempt)
    print(f"  GAVEUP {pack['id']} {i:02d} {job['subj']}", flush=True)
    return False


def main():
    selected = sys.argv[1:]
    packs = [p for p in PACKS if not selected or p["id"] in selected]
    OUTROOT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for pack in packs:
        pdir = OUTROOT / pack["id"]
        pdir.mkdir(parents=True, exist_ok=True)
        for i, subj in enumerate(pack["subjects"], 1):
            final = pdir / f"{i:02d}.png"
            if final.exists():
                continue
            jobs.append((pack, {"i": i, "subj": subj, "final": final,
                                "prompt": build(pack, subj)}))
    print(f"to generate: {len(jobs)} (concurrency {MAX_WORKERS})", flush=True)
    ok = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = [ex.submit(run_job, pack, job) for pack, job in jobs]
        for f in futs:
            if f.result():
                ok += 1
    total = sum(1 for _ in OUTROOT.rglob("*.png"))
    print(f"ALL DONE. this run ok={ok}/{len(jobs)} | total final PNG={total}", flush=True)


if __name__ == "__main__":
    main()
