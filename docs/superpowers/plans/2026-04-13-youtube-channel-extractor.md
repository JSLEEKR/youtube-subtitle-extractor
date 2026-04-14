# YouTube Channel Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Python scripts + two Claude Code slash-command skills that turn a YouTube channel (or single video) into Korean-language artifacts: transcript, translation, researched blog article, and 3-round adversarial debate.

**Architecture:** Deterministic work (channel listing, subtitle fetch, Whisper transcription) lives in three small Python scripts that each print a single JSON line to stdout and are idempotent. Language work (translation, documentation, debate, web research) happens in-session: the skills' `SKILL.md` files tell Claude how to orchestrate the pipeline and write the Korean outputs directly. Two skills share one per-video pipeline: `extract-video` resolves one video, `extract-channel` lists many and loops.

**Tech Stack:** Python 3.10+, `yt-dlp`, `faster-whisper` (CUDA large-v3 default), `pytest` for unit tests, ffmpeg (system), Claude Code skills (markdown + orchestration).

---

## File Structure

### Created files

| Path | Responsibility |
|---|---|
| `requirements.txt` | Runtime deps: `yt-dlp`, `faster-whisper` |
| `requirements-dev.txt` | Dev deps: `pytest` |
| `scripts/__init__.py` | Package marker so tests can import helpers |
| `scripts/list_videos.py` | Channel → filtered video list JSON |
| `scripts/fetch_subs.py` | Try official English subs → `transcript_en.txt` |
| `scripts/transcribe.py` | Audio download + faster-whisper → `transcript_en.txt` |
| `scripts/_common.py` | Pure helpers shared across scripts (date filtering, VTT parsing, dirname formatter) |
| `tests/__init__.py` | Test package marker |
| `tests/test_common.py` | Unit tests for pure helpers in `_common.py` |
| `tests/fixtures/sample.vtt` | Real VTT fixture for parser tests |
| `.claude/skills/extract-video/SKILL.md` | Single-video orchestration instructions |
| `.claude/skills/extract-channel/SKILL.md` | Channel-mode orchestration instructions |
| `README.md` | Project overview + setup steps |

### Modified files
None — this is a greenfield project. `.gitignore` and the design spec already exist.

### Design principles
- Each script does one thing and prints one JSON line to stdout on success. Stderr carries human-readable progress/errors. Non-zero exit = failure.
- All side-effecting logic (subprocess, file I/O to outputs) lives in the script's `main()`. All branching logic that needs tests lives in `_common.py` as pure functions.
- Skills are the orchestration layer; they read script output, make decisions, and do language work. Scripts never call Claude.

---

## Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `scripts/__init__.py`
- Create: `tests/__init__.py`
- Create: `README.md`

- [ ] **Step 1: Create `requirements.txt`**

```
yt-dlp>=2024.1.1
faster-whisper>=1.0.0
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest>=8.0.0
```

- [ ] **Step 3: Create empty package markers**

`scripts/__init__.py`:
```python
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Create `README.md`**

```markdown
# youtube-subtitle-extractor

Turn a YouTube channel (or single video) into a Korean-language knowledge bundle:
English transcript, Korean translation, researched blog article, and a 3-round
adversarial debate document. Orchestrated as Claude Code slash commands.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements-dev.txt
```

`ffmpeg` must be on PATH (for yt-dlp audio extraction). For GPU Whisper,
CUDA toolkit with cuBLAS + cuDNN is required; otherwise the script falls
back to CPU automatically.

## Usage (from a Claude Code session)

```
/extract-video <video_url>
/extract-channel <channel_url> [--days 30] [--limit N] [--skip-debate]
```

Output lands in `output/<channel_handle>/`. See
`docs/superpowers/specs/2026-04-13-youtube-channel-extractor-design.md`
for the full design.

## Running tests

```bash
pytest -v
```
```

- [ ] **Step 5: Install dev deps and confirm pytest runs**

Run:
```bash
pip install -r requirements-dev.txt
pytest -v
```

Expected: pytest runs, reports "no tests ran" (exit 5). That's fine — means pytest is installed and can find the `tests/` package.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt scripts/__init__.py tests/__init__.py README.md
git commit -m "chore: scaffold project structure and dev tooling"
```

---

## Task 2: Pure helpers in `_common.py` — date window filter

**Files:**
- Create: `scripts/_common.py`
- Test: `tests/test_common.py`

- [ ] **Step 1: Write the failing test for `filter_by_date_window`**

Append to `tests/test_common.py`:
```python
from datetime import date
from scripts._common import filter_by_date_window


def test_filter_by_date_window_keeps_videos_within_window():
    videos = [
        {"video_id": "a", "upload_date": "20260413"},  # today
        {"video_id": "b", "upload_date": "20260401"},  # 12 days ago
        {"video_id": "c", "upload_date": "20260314"},  # 30 days ago (inclusive)
        {"video_id": "d", "upload_date": "20260313"},  # 31 days ago (excluded)
        {"video_id": "e", "upload_date": "20250413"},  # way out
    ]
    today = date(2026, 4, 13)
    result = filter_by_date_window(videos, days=30, today=today)
    assert [v["video_id"] for v in result] == ["a", "b", "c"]


def test_filter_by_date_window_handles_missing_upload_date():
    videos = [
        {"video_id": "a", "upload_date": "20260413"},
        {"video_id": "b", "upload_date": None},
        {"video_id": "c"},
    ]
    today = date(2026, 4, 13)
    result = filter_by_date_window(videos, days=30, today=today)
    assert [v["video_id"] for v in result] == ["a"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts._common'`

- [ ] **Step 3: Implement `filter_by_date_window`**

Create `scripts/_common.py`:
```python
from datetime import date, datetime, timedelta
from typing import Iterable


def filter_by_date_window(videos: Iterable[dict], days: int, today: date) -> list[dict]:
    """Return videos whose upload_date is within the last `days` days (inclusive).

    `upload_date` is YouTube's YYYYMMDD string. Videos missing the field or with
    a falsy value are dropped.
    """
    cutoff = today - timedelta(days=days)
    kept = []
    for v in videos:
        ud = v.get("upload_date")
        if not ud:
            continue
        try:
            d = datetime.strptime(ud, "%Y%m%d").date()
        except ValueError:
            continue
        if cutoff <= d <= today:
            kept.append(v)
    return kept
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_common.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/_common.py tests/test_common.py
git commit -m "feat(common): add date-window filter for video lists"
```

---

## Task 3: Pure helpers — VTT to plain text

**Files:**
- Create: `tests/fixtures/sample.vtt`
- Modify: `scripts/_common.py`
- Modify: `tests/test_common.py`

- [ ] **Step 1: Create VTT fixture**

Create `tests/fixtures/sample.vtt`:
```
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500
Hello and welcome to the show.

00:00:02.500 --> 00:00:05.000
Today we're <c.yellow>talking</c> about
reinforcement learning.

00:00:05.000 --> 00:00:07.000
Let's dive in.
```

- [ ] **Step 2: Write the failing test for `vtt_to_plain_text`**

Append to `tests/test_common.py`:
```python
from pathlib import Path
from scripts._common import vtt_to_plain_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_vtt_to_plain_text_strips_headers_timestamps_and_tags():
    content = (FIXTURES / "sample.vtt").read_text(encoding="utf-8")
    result = vtt_to_plain_text(content)
    assert "WEBVTT" not in result
    assert "-->" not in result
    assert "<c.yellow>" not in result
    assert "Hello and welcome to the show." in result
    assert "Today we're talking about reinforcement learning." in result
    assert "Let's dive in." in result


def test_vtt_to_plain_text_deduplicates_consecutive_repeats():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:01.000
line one

00:00:01.000 --> 00:00:02.000
line one

00:00:02.000 --> 00:00:03.000
line two
"""
    assert vtt_to_plain_text(vtt).splitlines() == ["line one", "line two"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_common.py::test_vtt_to_plain_text_strips_headers_timestamps_and_tags -v`
Expected: FAIL — `ImportError: cannot import name 'vtt_to_plain_text'`

- [ ] **Step 4: Implement `vtt_to_plain_text`**

Append to `scripts/_common.py`:
```python
import re

_TIMESTAMP_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*")
_TAG_RE = re.compile(r"<[^>]+>")


def vtt_to_plain_text(vtt: str) -> str:
    """Strip WEBVTT headers, cue timestamps, and inline tags; join cue text.

    Consecutive duplicate lines (common in auto-generated subs that repeat cues)
    are collapsed. Returns a newline-joined paragraph-ish text.
    """
    lines: list[str] = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if _TIMESTAMP_RE.match(line):
            continue
        if line.isdigit():  # cue number
            continue
        line = _TAG_RE.sub("", line)
        if lines and lines[-1] == line:
            continue
        lines.append(line)

    # Merge lines that belong to the same cue (we lost cue boundaries; approximate
    # by joining lines with a space when the previous line doesn't end with punctuation).
    merged: list[str] = []
    for line in lines:
        if merged and not merged[-1].endswith((".", "!", "?", ":", ";", ",")):
            merged[-1] = merged[-1] + " " + line
        else:
            merged.append(line)
    return "\n".join(merged)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_common.py -v`
Expected: all 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/_common.py tests/test_common.py tests/fixtures/sample.vtt
git commit -m "feat(common): add VTT-to-plain-text parser"
```

---

## Task 4: Pure helpers — dated dirname formatter

**Files:**
- Modify: `scripts/_common.py`
- Modify: `tests/test_common.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_common.py`:
```python
from scripts._common import format_video_dirname


def test_format_video_dirname_uses_iso_date_and_id():
    assert format_video_dirname("20260413", "dQw4w9WgXcQ") == "2026-04-13_dQw4w9WgXcQ"


def test_format_video_dirname_falls_back_when_date_missing():
    assert format_video_dirname(None, "abc123") == "0000-00-00_abc123"
    assert format_video_dirname("", "abc123") == "0000-00-00_abc123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_common.py -v`
Expected: FAIL on import.

- [ ] **Step 3: Implement `format_video_dirname`**

Append to `scripts/_common.py`:
```python
def format_video_dirname(upload_date: str | None, video_id: str) -> str:
    """Build `<YYYY-MM-DD>_<video_id>` from YouTube's YYYYMMDD string.

    Missing/invalid dates use `0000-00-00` so the video still gets a stable folder.
    """
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        iso = f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    else:
        iso = "0000-00-00"
    return f"{iso}_{video_id}"
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_common.py -v`
Expected: all tests PASS (6 total so far).

- [ ] **Step 5: Commit**

```bash
git add scripts/_common.py tests/test_common.py
git commit -m "feat(common): add dated video-dirname formatter"
```

---

## Task 5: `list_videos.py` — channel listing script

**Files:**
- Create: `scripts/list_videos.py`

This task has no unit tests — it's a thin wrapper over `yt-dlp` subprocess. The pure filtering logic is already tested in Task 2. We'll validate this script with a manual smoke test in Task 9.

- [ ] **Step 1: Implement `list_videos.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add scripts/list_videos.py
git commit -m "feat(scripts): add list_videos.py for channel listing"
```

---

## Task 6: `fetch_subs.py` — official English subtitle fetch

**Files:**
- Create: `scripts/fetch_subs.py`

- [ ] **Step 1: Implement `fetch_subs.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add scripts/fetch_subs.py
git commit -m "feat(scripts): add fetch_subs.py for official EN subtitle fetch"
```

---

## Task 7: `transcribe.py` — faster-whisper fallback

**Files:**
- Create: `scripts/transcribe.py`

- [ ] **Step 1: Implement `transcribe.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add scripts/transcribe.py
git commit -m "feat(scripts): add transcribe.py with faster-whisper + CPU fallback"
```

---

## Task 8: `extract-video` skill

**Files:**
- Create: `.claude/skills/extract-video/SKILL.md`

This is the per-video pipeline. Both skills depend on this logic — the channel skill reuses it per video. Write it here once and have the channel skill reference it.

- [ ] **Step 1: Create `SKILL.md`**

````markdown
---
name: extract-video
description: Process a single YouTube video URL end-to-end — fetch (or transcribe) English subtitles, translate to Korean, write a researched Korean blog article, and run a 3-round adversarial debate. Output lands in `output/<channel_handle>/<YYYY-MM-DD>_<video_id>/`.
---

# extract-video

You run the full per-video pipeline for one YouTube URL. Channel mode reuses this same pipeline inside a loop.

## Input
- A YouTube video URL (required)

## Preconditions
- Working directory is the project root.
- `python`, `yt-dlp`, and `ffmpeg` on PATH. If not, stop and tell the user to install them.
- `scripts/` and `.claude/skills/` exist.

## Step 1 — Resolve channel handle and video metadata

Run:
```bash
yt-dlp --skip-download --print "%(id)s|%(title)s|%(upload_date)s|%(duration)s|%(uploader_id)s|%(channel)s" <video_url>
```

Parse the `|`-separated line into: `video_id`, `title`, `upload_date`, `duration`, `uploader_id`, `channel`.

Compute `channel_handle = uploader_id` (fallback: sanitized `channel`). Compute `dated_id` as `<YYYY-MM-DD>_<video_id>` from `upload_date` (use `0000-00-00` if missing).

Compute the output directory: `output/<channel_handle>/<dated_id>/`. Create it.

## Step 2 — Write `meta.json`

If `meta.json` already exists in the directory, leave it alone.
Otherwise write:
```json
{
  "video_id": "...",
  "title": "...",
  "upload_date": "YYYYMMDD",
  "duration": 1234,
  "url": "https://www.youtube.com/watch?v=...",
  "channel": "...",
  "channel_handle": "...",
  "subtitle_source": null
}
```

## Step 3 — Get the English transcript

If `transcript_en.txt` already exists in the directory, skip to Step 4.

Otherwise try official subs first:
```bash
python -m scripts.fetch_subs <video_url> --out-dir <video_dir>
```
- Exit 0 → update `meta.json`'s `subtitle_source` to `"official"`.
- Exit 2 (no official EN) → fall through to Whisper:
  ```bash
  python -m scripts.transcribe <video_url> --out-dir <video_dir>
  ```
  On success, update `subtitle_source` to `"whisper"` plus the model/device reported by the script.
- Any other non-zero exit → record the error in `meta.json` under `error` and stop processing this video (do not proceed to steps 4–6).

## Step 4 — Korean translation → `transcript_ko.md`

If `transcript_ko.md` already exists, skip.

Otherwise read `transcript_en.txt` and produce a natural Korean translation in-session. Rules:
- Not literal. Rewrite into natural Korean paragraphs. Remove filler words.
- Keep proper nouns, paper titles, product names, and technical terms with the original in parentheses, e.g. `강화학습(reinforcement learning)`.
- For long transcripts, translate in chunks but keep context (read the whole file first, then translate chunk by chunk preserving terminology).
- Prepend a small frontmatter:
  ```markdown
  # <Korean title>
  > 원본: <video_url> · 업로드: YYYY-MM-DD · 길이: Nm
  ```

Write the result to `transcript_ko.md`.

## Step 5 — Researched document → `document.md`

If `document.md` already exists, skip.

Otherwise use `transcript_ko.md` as your source and write a blog-article-style Korean document:
```markdown
# <Korean title>
> 원본: [YouTube](<url>) · 업로드: YYYY-MM-DD · 길이: Nm

## 서론
(무엇을 다루는가, 왜 중요한가)

## 본론
(3~5개의 주제별 섹션)

## 핵심 인사이트
- ...
- ...

## 더 알아보기
- [자료 제목](url) — 한 줄 설명
```

While writing, use the `WebSearch` tool to:
- Verify factual claims in the video (papers, products, people, dates).
- Find linkable sources for concepts the video mentions but doesn't define.
- Surface 3–6 related links for the "더 알아보기" section.

Do NOT invent citations. If WebSearch fails or returns nothing credible, omit the citation rather than guess.

## Step 6 — Adversarial debate → `debate.md`

If `debate.md` already exists or the user passed `--skip-debate`, skip.

Otherwise generate three full rounds plus synthesis. Each Pro/Con entry is 2–4 paragraphs. The two rules that make this valuable:
1. **Each later round must rebut the previous round by name.** No paraphrased re-assertion.
2. **Evidence for non-obvious claims comes from WebSearch**, not imagination.

Structure:
```markdown
# 토론: <영상 주제>

## Round 1
### 🟢 Pro
<strongest steelman of the video's thesis, with cited support>
### 🔴 Con
<sharpest rebuttal, with counter-evidence>

## Round 2
### 🟢 Pro (재반론)
### 🔴 Con (재반박)

## Round 3
### 🟢 Pro
### 🔴 Con

## 🧭 종합
- **합의 지점:** ...
- **열린 질문:** ...
- **더 나아간 관점:** (영상이 다루지 않은 새로운 프레임, 후속 질문, 실천적 제언)
```

Write the result to `debate.md`.

## Step 7 — Update channel README

Regenerate `output/<channel_handle>/README.md` so that this video appears in the index.

Read any existing `meta.json` files under `output/<channel_handle>/*/meta.json`, sort by `upload_date` descending, and render:
```markdown
# <Channel name>

| 날짜 | 제목 | 길이 | 자막 출처 | 파일 |
|---|---|---|---|---|
| 2026-04-13 | <제목> | 23m | official | [번역](2026-04-13_xxx/transcript_ko.md) · [문서](2026-04-13_xxx/document.md) · [토론](2026-04-13_xxx/debate.md) |
| ... | ... | ... | ... | ... |
```

Write the file. Overwrite any previous README.

## Step 8 — Report

Print a short summary for the user:
- Video title
- Subtitle source (official / whisper)
- Which files were written vs skipped
- Output directory path

## Failure handling

- If Step 3 fails, stop and report. Do not touch steps 4–6.
- If Steps 4–6 fail (e.g., WebSearch times out), record the error in `meta.json` under `error`, keep any partial files, report what succeeded.
- Idempotency: re-running the skill picks up where the previous run stopped.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/extract-video/SKILL.md
git commit -m "feat(skills): add extract-video skill"
```

---

## Task 9: `extract-channel` skill

**Files:**
- Create: `.claude/skills/extract-channel/SKILL.md`

- [ ] **Step 1: Create `SKILL.md`**

````markdown
---
name: extract-channel
description: Process all recent videos from a YouTube channel — lists videos within a date window, then runs the per-video extract pipeline (subs → translate → research → debate) for each. Output lands in `output/<channel_handle>/`.
---

# extract-channel

You run the full channel pipeline: list recent videos, then loop the per-video extract pipeline over them. The per-video pipeline is defined in `.claude/skills/extract-video/SKILL.md` — steps 1–8 of that skill are the "per-video pipeline" referenced below.

## Input
- A channel URL, `@handle`, or channel ID (required)
- `--days N` (default 30)
- `--limit N` (optional — cap on number of videos, for testing)
- `--skip-debate` (optional — skip step 6 of the per-video pipeline)

## Preconditions
Same as extract-video: `python`, `yt-dlp`, `ffmpeg` on PATH; `scripts/` exists.

## Step 1 — List recent videos

Run:
```bash
python -m scripts.list_videos <channel> --days <N> --output output/_tmp_videos.json
```
(If `--limit N` was passed, append `--limit N`.)

Read the resulting JSON. Parse the `channel_handle` from the script's stdout JSON line. If `channel_handle` is empty, use the first video's `channel_handle` field; if still empty, ask the user to supply one.

Move/rename `output/_tmp_videos.json` to `output/<channel_handle>/videos.json` (creating the directory if needed).

## Step 2 — Confirm with user

Show the user:
- Channel handle
- Number of videos in the window
- The list of titles with upload dates

Ask: "Proceed with processing N videos? (y/n)" — wait for confirmation before the loop. (If the user already said "just go" when invoking the skill, proceed.)

## Step 3 — Create a task list

Use TaskCreate to create one task per video, subject = `Process: <title>`. This gives the user live progress visibility.

## Step 4 — Per-video loop

For each video in the filtered list:

1. Mark its task `in_progress` via TaskUpdate.
2. Run the **per-video pipeline** (steps 1–8 from `.claude/skills/extract-video/SKILL.md`) using the video's URL.
3. On success: mark the task `completed`.
4. On failure: mark the task `completed` anyway (the failure is already recorded in that video's `meta.json` under `error`), but track it in a local "failed" counter for the final report.
5. Continue to the next video even if this one failed.

Respect `--skip-debate` by skipping the debate step inside the per-video pipeline.

Idempotency: the per-video pipeline already skips any file that exists, so re-running the channel skill picks up where it left off.

## Step 5 — Final report

Print:
```
Channel: <channel_handle>
Window: last <N> days (YYYY-MM-DD to YYYY-MM-DD)
Processed: X succeeded, Y skipped (already done), Z failed
Output: output/<channel_handle>/

Failed videos (if any):
- <title> — <error>
```

Point the user at `output/<channel_handle>/README.md` as the dashboard.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/extract-channel/SKILL.md
git commit -m "feat(skills): add extract-channel skill"
```

---

## Task 10: End-to-end smoke test

This task validates the whole pipeline against real YouTube. No unit tests — it's an integration check. Run with a short, known-good video that has official English subs so the fast path is exercised.

**Files:** none created; this is a validation task.

- [ ] **Step 1: Pick a short test video**

Use a short (< 3 min) video you know has official English subs. If unsure, ask the user for one. A good candidate: any TED-Ed short. The user may supply their own URL.

- [ ] **Step 2: Run `list_videos.py` against a small channel**

```bash
python -m scripts.list_videos "https://www.youtube.com/@TED-Ed" --days 7 --limit 2 --output output/_smoke_videos.json
```

Expected:
- Exits 0
- `output/_smoke_videos.json` contains a JSON array of ≤ 2 video dicts
- stdout has one JSON line with `"status": "ok"` and a nonzero `count`

If it fails, debug `list_videos.py`. Common issues: yt-dlp not installed, channel URL wrong, `upload_date` missing from flat-playlist mode (the backfill step should handle this but may be slow).

- [ ] **Step 3: Run `fetch_subs.py` against the first video from step 2**

Pick any `url` from `output/_smoke_videos.json`. Then:
```bash
mkdir -p output/_smoke_test
python -m scripts.fetch_subs "<url>" --out-dir output/_smoke_test
```

Expected:
- Exits 0 with `{"status": "ok", "source": "official"}`
- `output/_smoke_test/transcript_en.txt` exists and contains human-readable English (no `-->`, no `WEBVTT` header)

- [ ] **Step 4: Run `transcribe.py` on a video that has NO official subs (optional but recommended)**

If you can find such a video, run:
```bash
python -m scripts.transcribe "<url>" --out-dir output/_smoke_whisper
```

Expected:
- On first run: faster-whisper downloads `large-v3` weights (~3GB). This takes time.
- Exits 0 with `{"status": "ok", "source": "whisper", "device": "cuda" or "cpu", ...}`
- `output/_smoke_whisper/transcript_en.txt` exists and is readable

If CUDA fails the script should auto-fallback to CPU. If it crashes instead, fix the fallback in `scripts/transcribe.py`.

- [ ] **Step 5: Clean up smoke test artifacts**

```bash
rm -rf output/_smoke_test output/_smoke_whisper output/_smoke_videos.json
```

- [ ] **Step 6: Run the whole test suite once more**

```bash
pytest -v
```

Expected: all pure-helper tests pass.

- [ ] **Step 7: Final commit (if anything was adjusted)**

```bash
git status
# If clean, nothing to do. If changes, commit with an appropriate message.
```

---

## Done criteria

- `pytest -v` is green.
- `list_videos.py`, `fetch_subs.py`, `transcribe.py` each runnable standalone and print valid JSON to stdout.
- Both `SKILL.md` files exist and are discoverable by Claude Code.
- Smoke test in Task 10 succeeds against a real channel + real video.
- `README.md` tells a new user how to install and invoke the skills.
