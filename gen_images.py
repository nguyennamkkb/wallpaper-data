#!/usr/bin/env python3
"""Generate one image per aspect ratio through a running muse2api gateway.

Examples:
    python scripts/gen_images.py "A red fox sitting, studio photo"
    python scripts/gen_images.py "A red fox" --sizes 1:1,16:9
    python scripts/gen_images.py "A red fox" --ref ./ref.png --out out/fox
    python scripts/gen_images.py "A red fox" --sync --n 2

Local reference images are inlined as data URLs, so the gateway never has to
reach back to this machine. Remote references must be public http(s) URLs.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SIZES = ("1:1", "3:4", "4:3", "16:9", "9:16")
DEFAULT_BASE = "http://127.0.0.1:18610"
TERMINAL = {"succeeded", "failed", "cancelled"}


# --------------------------------------------------------------------------- HTTP


def api(method: str, url: str, key: str, payload: dict | None = None,
        timeout: float = 60.0) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {key}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("error") or body
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
        except ValueError:
            detail = body
        raise SystemExit(f"{method} {url} -> HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"{method} {url} failed: {exc.reason}") from None


def download(url: str, timeout: float = 120.0) -> tuple[bytes, str]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read(), response.headers.get_content_type()


# ----------------------------------------------------------------- image probing


def probe_size(data: bytes) -> tuple[int, int] | None:
    """Read width/height from a PNG, JPEG or WebP header without Pillow."""
    if len(data) < 32:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_size(data)
    if data[:2] == b"\xff\xd8":
        return _jpeg_size(data)
    return None


def _webp_size(data: bytes) -> tuple[int, int] | None:
    chunk = data[12:16]
    if chunk == b"VP8X":
        return (int.from_bytes(data[24:27], "little") + 1,
                int.from_bytes(data[27:30], "little") + 1)
    if chunk == b"VP8 ":
        return (int.from_bytes(data[26:28], "little") & 0x3FFF,
                int.from_bytes(data[28:30], "little") & 0x3FFF)
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB):
            return int.from_bytes(data[pos + 7:pos + 9], "big"), int.from_bytes(
                data[pos + 5:pos + 7], "big")
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        pos += 2 + int.from_bytes(data[pos + 2:pos + 4], "big")
    return None


# ------------------------------------------------------------------- references


def resolve_ref(ref: str) -> str:
    """Pass URLs/data URLs through; inline a local file as a data URL."""
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    path = Path(ref).expanduser()
    if not path.is_file():
        raise SystemExit(f"reference image not found: {ref}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


# ------------------------------------------------------------------------ sizes


def parse_sizes(raw: str) -> list[str]:
    if raw.strip().lower() == "all":
        return list(SIZES)
    sizes = []
    for item in raw.split(","):
        size = item.strip().replace("x", ":").replace("×", ":")
        if not size:
            continue
        if size not in SIZES:
            raise SystemExit(f"unsupported size '{item}', pick from {', '.join(SIZES)}")
        if size not in sizes:
            sizes.append(size)
    return sizes


def find_key(explicit: str | None, data_dir: Path) -> str:
    key = explicit or os.environ.get("MUSE2API_API_KEY")
    if key:
        return key.strip()
    key_file = data_dir / "api_key"
    if key_file.is_file():
        return key_file.read_text().strip()
    raise SystemExit("no API key: pass --key, set MUSE2API_API_KEY or create data/api_key")


# ------------------------------------------------------------------------- main


def generate(base: str, key: str, prompt: str, size: str, *, model: str | None,
             n: int, refs: list[str], background: str | None, use_async: bool,
             timeout: float, interval: float) -> tuple[dict | None, float, str]:
    payload: dict = {"prompt": prompt, "size": size, "n": n}
    if model:
        payload["model"] = model
    if refs:
        payload["image"] = refs[0] if len(refs) == 1 else refs
    if background:
        payload["background"] = background

    started = time.monotonic()
    if not use_async:
        task = api("POST", f"{base}/v1/images/generations", key, payload,
                   timeout=timeout)
        return task, time.monotonic() - started, ""

    payload["async"] = True
    task = api("POST", f"{base}/v1/images/generations", key, payload)
    task_id = task["id"]
    while True:
        if task["status"] in TERMINAL:
            break
        if time.monotonic() - started > timeout:
            return None, time.monotonic() - started, f"timed out after {timeout:.0f}s"
        print(f"    {size} {task['status']:<9} {time.monotonic() - started:5.0f}s",
              end="\r", flush=True)
        time.sleep(interval)
        task = api("GET", f"{base}/v1/images/generations/{task_id}", key)
    elapsed = time.monotonic() - started
    print(" " * 46, end="\r")
    if task["status"] != "succeeded":
        return None, elapsed, str(task.get("error") or task["status"])
    return task["result"], elapsed, ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate images at several aspect ratios via muse2api.")
    parser.add_argument("prompt", help="image prompt (shared by every size)")
    parser.add_argument("--sizes", default="all",
                        help=f"comma list or 'all' (default) from {', '.join(SIZES)}")
    parser.add_argument("--ref", action="append", default=[],
                        help="reference image: local path or public URL (repeatable, max 4)")
    parser.add_argument("--model", default="muse-image")
    parser.add_argument("--n", type=int, default=1, help="images per size (1-4)")
    parser.add_argument("--background", choices=("auto", "opaque", "transparent"))
    parser.add_argument("--base", default=os.environ.get("MUSE2API_BASE", DEFAULT_BASE))
    parser.add_argument("--key", help="API key (default: $MUSE2API_API_KEY or data/api_key)")
    parser.add_argument("--out", default="out", help="output directory (default: out)")
    parser.add_argument("--sync", action="store_true",
                        help="wait inside the POST instead of polling a task")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-image timeout")
    parser.add_argument("--interval", type=float, default=3.0, help="poll interval")
    args = parser.parse_args()

    if len(args.ref) > 4:
        raise SystemExit("at most 4 reference images are supported")
    if not 1 <= args.n <= 4:
        raise SystemExit("--n must be between 1 and 4")

    base = args.base.rstrip("/")
    key = find_key(args.key, Path(__file__).resolve().parent.parent / "data")
    sizes = parse_sizes(args.sizes)
    refs = [resolve_ref(ref) for ref in args.ref]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{base}  model={args.model}  n={args.n}  refs={len(refs)}"
          f"  sizes={','.join(sizes)}")
    print(f'prompt: "{args.prompt}"')

    stamp = time.strftime("%Y%m%d-%H%M%S")
    report: list[dict] = []
    failures = 0

    for size in sizes:
        slug = size.replace(":", "x")
        print(f"[{size}]", flush=True)
        result, elapsed, error = generate(
            base, key, args.prompt, size, model=args.model, n=args.n, refs=refs,
            background=args.background, use_async=not args.sync,
            timeout=args.timeout, interval=args.interval)
        items: list[dict] = []
        if error or not result:
            failures += 1
            print(f"  FAILED {elapsed:.1f}s  {error}")
            report.append({"size": size, "status": "failed", "seconds": round(elapsed, 1),
                           "error": error})
            continue

        for index, item in enumerate(result.get("data", []), start=1):
            if "b64_json" in item:
                data = base64.b64decode(item["b64_json"])
                mime = "image/png"
            else:
                data, mime = download(item["url"])
            ext = mimetypes.guess_extension(mime) or ".img"
            name = f"{slug}_{stamp}_{index}{ext}"
            (out_dir / name).write_bytes(data)
            dims = probe_size(data)
            want = [int(part) for part in size.split(":")]
            ratio_ok = bool(dims) and abs(dims[0] / dims[1] - want[0] / want[1]) < 0.02
            flag = "ok" if ratio_ok else "ratio?"
            if not ratio_ok:
                failures += 1
            dims_text = f"{dims[0]}x{dims[1]}" if dims else "?x?"
            print(f"  {flag:<6} {elapsed:5.1f}s  {dims_text:<11}  {len(data) // 1024} KB"
                  f"  -> {out_dir / name}")
            items.append({"file": str(out_dir / name), "url": item.get("url"),
                          "width": dims[0] if dims else None,
                          "height": dims[1] if dims else None,
                          "ratio_ok": ratio_ok, "bytes": len(data)})
        report.append({"size": size, "status": "succeeded", "seconds": round(elapsed, 1),
                       "items": items})

    report_path = out_dir / f"report-{stamp}.json"
    report_path.write_text(json.dumps(
        {"base": base, "model": args.model, "prompt": args.prompt,
         "references": args.ref, "results": report}, indent=2))
    print(f"\nreport: {report_path}")
    ok = sum(1 for row in report if row["status"] == "succeeded")
    print(f"done: {ok}/{len(report)} sizes succeeded")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
