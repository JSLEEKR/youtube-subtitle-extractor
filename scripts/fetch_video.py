"""Download the source YouTube video as mp4.

Usage:
    python -m scripts.fetch_video <video_url> --out-dir <dir>

On success: writes `video.mp4` in out-dir, prints
    {"status": "ok", "path": "<abs path>"}
If `video.mp4` already exists, prints
    {"status": "skipped", "source": "cached"}
and exits 0.

Exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def download_video(video_url: str, out_dir: Path) -> Path:
    out_template = str(out_dir / "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f", "bv*+ba/b",
        "--merge-output-format", "mp4",
        "-o", out_template,
        video_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp video download failed: {proc.stderr.strip()}")
    mp4 = out_dir / "video.mp4"
    if not mp4.exists():
        raise RuntimeError("yt-dlp reported success but video.mp4 was not produced")
    return mp4


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video_url")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "video.mp4"
    if target.exists():
        print(json.dumps({"status": "skipped", "source": "cached"}))
        return 0

    try:
        path = download_video(args.video_url, out_dir)
    except Exception as e:
        print(f"fetch_video failed: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"status": "ok", "path": str(path.resolve())}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
