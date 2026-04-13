"""List recent videos from a YouTube channel.

Usage:
    python -m scripts.list_videos <channel> --days 30 --output path/to/videos.json

Prints one JSON line to stdout on success:
    {"status": "ok", "channel_handle": "...", "count": N, "output": "..."}

Exits non-zero on failure, with a human-readable message on stderr.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from scripts._common import filter_by_date_window


def run_yt_dlp_flat(channel: str) -> list[dict]:
    """Call yt-dlp in flat-playlist metadata mode; return one dict per video."""
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--ignore-errors",
        channel,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(f"yt-dlp failed: {proc.stderr.strip()}")
    videos: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return videos


def normalize(video: dict) -> dict:
    """Project yt-dlp's flat-playlist entry into our minimal schema."""
    vid = video.get("id") or ""
    return {
        "video_id": vid,
        "title": video.get("title") or "",
        "upload_date": video.get("upload_date"),  # may be None in flat mode
        "duration": video.get("duration"),
        "url": video.get("url") or f"https://www.youtube.com/watch?v={vid}",
        "channel": video.get("channel") or video.get("uploader") or "",
        "channel_handle": video.get("uploader_id") or "",
    }


def backfill_upload_dates(videos: list[dict]) -> list[dict]:
    """Flat-playlist mode often omits upload_date. Fetch it per video.

    Uses `yt-dlp --skip-download --print upload_date` which is cheap (metadata only).
    """
    for v in videos:
        if v.get("upload_date"):
            continue
        try:
            proc = subprocess.run(
                ["yt-dlp", "--skip-download", "--print", "upload_date", v["url"]],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            ud = proc.stdout.strip()
            if ud and len(ud) == 8 and ud.isdigit():
                v["upload_date"] = ud
        except Exception:
            pass
    return videos


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("channel")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--output", required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    try:
        raw = run_yt_dlp_flat(args.channel)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1

    normalized = [normalize(v) for v in raw if v.get("id")]
    normalized = backfill_upload_dates(normalized)
    filtered = filter_by_date_window(normalized, days=args.days, today=date.today())
    filtered.sort(key=lambda v: v.get("upload_date", ""), reverse=True)
    if args.limit:
        filtered = filtered[: args.limit]

    channel_handle = ""
    for v in normalized:
        if v.get("channel_handle"):
            channel_handle = v["channel_handle"]
            break

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "status": "ok",
        "channel_handle": channel_handle,
        "count": len(filtered),
        "output": str(out_path),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
