"""Fetch official English subtitles for a YouTube video.

Usage:
    python -m scripts.fetch_subs <video_url> --out-dir path/to/video_dir

On success: writes `transcript_en.txt` in out-dir, prints
    {"status": "ok", "source": "official"}
On no-subs: exits 2, prints
    {"status": "no_subs", "source": null, "reason": "no_official_en"}
Other failure: exits 1 with human message on stderr.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts._common import vtt_to_plain_text


def download_official_en_vtt(video_url: str, workdir: Path) -> Path | None:
    """Ask yt-dlp for official English subs. Returns the VTT path or None if absent.

    We deliberately do NOT enable --write-auto-subs: auto-captions are skipped.
    """
    out_template = str(workdir / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--sub-langs", "en",
        "--sub-format", "vtt",
        "-o", out_template,
        video_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return None
    vtts = list(workdir.glob("*.en.vtt"))
    return vtts[0] if vtts else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video_url")
    p.add_argument("--out-dir", required=True)
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "transcript_en.txt"
    if target.exists():
        print(json.dumps({"status": "skipped", "source": "cached"}))
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        vtt_path = download_official_en_vtt(args.video_url, Path(tmp))
        if vtt_path is None:
            print(json.dumps({
                "status": "no_subs",
                "source": None,
                "reason": "no_official_en",
            }))
            return 2
        text = vtt_to_plain_text(vtt_path.read_text(encoding="utf-8"))

    target.write_text(text, encoding="utf-8")
    print(json.dumps({"status": "ok", "source": "official"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
