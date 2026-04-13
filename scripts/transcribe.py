"""Transcribe a YouTube video's audio with faster-whisper.

Usage:
    python -m scripts.transcribe <video_url> --out-dir <dir>
        [--model large-v3] [--device cuda] [--compute-type float16]

On success: writes `transcript_en.txt` in out-dir, prints
    {"status": "ok", "source": "whisper", "model": "...", "device": "..."}
Exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def download_audio(video_url: str, workdir: Path) -> Path:
    out_template = str(workdir / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format", "mp3",
        "-o", out_template,
        video_url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp audio download failed: {proc.stderr.strip()}")
    mp3s = list(workdir.glob("*.mp3"))
    if not mp3s:
        raise RuntimeError("yt-dlp reported success but no mp3 was produced")
    return mp3s[0]


def load_model(model: str, device: str, compute_type: str):
    """Try the requested device; on CUDA failure fall back to CPU/int8."""
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(model, device=device, compute_type=compute_type), device, compute_type
    except Exception as e:
        if device == "cuda":
            print(f"[transcribe] CUDA init failed ({e}); falling back to CPU int8", file=sys.stderr)
            return WhisperModel(model, device="cpu", compute_type="int8"), "cpu", "int8"
        raise


def transcribe_to_text(model_obj, audio_path: Path) -> str:
    segments, _info = model_obj.transcribe(str(audio_path), language="en", vad_filter=True)
    return "\n".join(seg.text.strip() for seg in segments if seg.text.strip())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video_url")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--model", default="large-v3")
    p.add_argument("--device", default="cuda")
    p.add_argument("--compute-type", default="float16")
    args = p.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "transcript_en.txt"
    if target.exists():
        print(json.dumps({"status": "skipped", "source": "cached"}))
        return 0

    try:
        with tempfile.TemporaryDirectory() as tmp:
            audio = download_audio(args.video_url, Path(tmp))
            model_obj, used_device, used_ctype = load_model(args.model, args.device, args.compute_type)
            text = transcribe_to_text(model_obj, audio)
    except Exception as e:
        print(f"transcribe failed: {e}", file=sys.stderr)
        return 1

    target.write_text(text, encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "source": "whisper",
        "model": args.model,
        "device": used_device,
        "compute_type": used_ctype,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
