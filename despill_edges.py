#!/usr/bin/env python3
"""Remove chroma-key spill from the semi-transparent edge band of cut-out stickers.

For every PNG: if the subject is NOT green-dominant (interior alpha=255 green
fraction < 5%), desaturate the green cast on edge pixels (0 < alpha < 255) where
green dominates. Green subjects (leaf/frog/graffiti drips) are skipped so their
own colour survives; opaque artwork is never touched.

Usage:
  python3 despill_edges.py --report         # analyse only, print flagged files
  python3 despill_edges.py                  # fix in place
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOTS = [Path("out/sticker-figma"), Path("out/sticker-new")]
GREEN_INTERIOR_LIMIT = 0.05


def analyse(path):
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.int16)
    a, r, g, b = im[:, :, 3], im[:, :, 0], im[:, :, 1], im[:, :, 2]
    gd = (g > r + 30) & (g > b + 30)
    interior = a >= 250
    band = (a > 0) & (a < 250)
    interior_frac = float(gd[interior].sum()) / max(int(interior.sum()), 1)
    band_frac = float(gd[band].sum()) / max(int(band.sum()), 1)
    return interior_frac, band_frac


def despill(path):
    im = np.asarray(Image.open(path).convert("RGBA")).astype(np.int16)
    r, g, b, a = im[:, :, 0], im[:, :, 1], im[:, :, 2], im[:, :, 3]
    band = (a > 0) & (a < 250) & (g > np.maximum(r, b))
    before = int(band.sum())
    g[band] = np.maximum(r[band], b[band])
    out = np.dstack([r, g, b, a]).clip(0, 255).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(path, optimize=True)
    return before


def main():
    report = "--report" in sys.argv
    files = sorted(p for root in ROOTS if root.exists() for p in root.rglob("*.png"))
    flagged, skipped, fixed = [], 0, 0
    for p in files:
        try:
            in_frac, band_frac = analyse(p)
        except Exception as e:
            print(f"  ERR {p}: {e}")
            continue
        if in_frac >= GREEN_INTERIOR_LIMIT:
            skipped += 1
            continue
        if band_frac > 0.08:
            flagged.append((p, band_frac))
            if not report:
                n = despill(p)
                fixed += 1
    print(f"files={len(files)} flagged={len(flagged)} fixed={fixed} skipped_green_subject={skipped}")
    for p, f in flagged:
        print(f"  {p}  edge_green={f*100:.1f}%")


if __name__ == "__main__":
    main()
