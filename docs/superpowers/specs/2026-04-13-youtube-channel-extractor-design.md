# YouTube Channel Extractor — Design

**Date:** 2026-04-13
**Status:** Approved (brainstorming phase)
**Location:** `C:\claude\youtube-subtitle-extractor\`

## 1. Goal

Given a YouTube channel (or a single video), produce a Korean-language knowledge artifact for each recent video: transcript, translation, blog-style article with external research, and an adversarial debate document. Reusable as Claude Code slash commands.

## 2. User Interface

Two Claude Code skills (slash commands):

```
/extract-channel <channel>              # all recent videos in a channel
/extract-channel <channel> --days 14    # custom window
/extract-channel <channel> --skip-debate
/extract-channel <channel> --limit 3    # cap for testing

/extract-video <video_url>              # single video
```

**Channel argument** accepts: full URL (`https://www.youtube.com/@name`), `@handle`, or channel ID.
**Default window:** 30 days from today.

## 3. Architecture

Deterministic work (downloading, transcribing) lives in Python scripts. Language work (translation, writing, debate, web research) is performed in-session by Claude itself via the skill orchestration.

```
[User]
  │  /extract-channel <url>
  ▼
[Skill: SKILL.md orchestration — Claude reads and executes]
  │
  ├─ scripts/list_videos.py        (channel mode only)
  ├─ scripts/fetch_subs.py         (per video, try official EN subs)
  ├─ scripts/transcribe.py         (fallback: audio → faster-whisper)
  ├─ Claude: translate EN → KO
  ├─ Claude: write document.md + WebSearch research
  ├─ Claude: 3-round adversarial debate + synthesis
  └─ Claude: update channel README.md index
```

**Skill files:**
- `.claude/skills/extract-channel/SKILL.md`
- `.claude/skills/extract-video/SKILL.md`

Both skills share the per-video pipeline (steps after video list is known). The channel skill adds the `list_videos.py` step at the front; the video skill resolves the channel handle from the video metadata and drops straight into the pipeline.

## 4. Directory Layout

```
youtube-subtitle-extractor\
├── .claude\skills\
│   ├── extract-channel\SKILL.md
│   └── extract-video\SKILL.md
├── scripts\
│   ├── list_videos.py
│   ├── fetch_subs.py
│   └── transcribe.py
├── requirements.txt
├── output\
│   └── <channel_handle>\
│       ├── README.md                        # channel index
│       └── <YYYY-MM-DD>_<video_id>\
│           ├── meta.json
│           ├── transcript_en.txt
│           ├── transcript_ko.md
│           ├── document.md
│           └── debate.md
└── docs\superpowers\specs\
    └── 2026-04-13-youtube-channel-extractor-design.md
```

The dated prefix on video folders gives natural chronological sort.

## 5. Python Scripts

Each script does one thing and prints a single JSON line to stdout. Idempotent: if the target file already exists, skip and exit 0 with `{"status": "skipped"}`. On failure, print human-readable message to stderr and exit non-zero.

### 5.1 `list_videos.py`
```
python scripts/list_videos.py <channel> --days 30 --output output/<handle>/videos.json
```
- Uses `yt-dlp --flat-playlist --dump-json` (metadata only, no downloads).
- Filters by upload date within the window.
- Output JSON: `[{video_id, title, upload_date, duration, url}, ...]`
- Also prints resolved `channel_handle` so the skill knows the output directory.

### 5.2 `fetch_subs.py`
```
python scripts/fetch_subs.py <video_url> --out-dir <video_dir>
```
- Runs `yt-dlp --skip-download --write-subs --sub-langs en --sub-format vtt`.
- If English official subs exist: strips VTT tags/timestamps, writes `transcript_en.txt`, prints `{"source": "official"}`.
- If not: exits 2 with `{"source": null, "reason": "no_official_en"}`. Skill falls through to transcribe.

Note: auto-generated subtitles are **not** used (quality inconsistency). Fall through to Whisper instead.

### 5.3 `transcribe.py`
```
python scripts/transcribe.py <video_url> --out-dir <dir> \
    --model large-v3 --device cuda --compute-type float16
```
- Downloads audio only via `yt-dlp -x --audio-format mp3` to a temp file.
- Runs `faster-whisper` with `language="en"`.
- Writes `transcript_en.txt`, deletes temp audio, prints `{"source": "whisper", "model": "large-v3"}`.
- Defaults: `large-v3` on CUDA with `float16` (assumes GPU available ~5GB VRAM).
- If CUDA init fails, auto-fallback to `device=cpu, compute_type=int8` with a warning.

## 6. In-Session Processing (Claude)

For each video after `transcript_en.txt` exists:

### 6.1 Translation → `transcript_ko.md`
- Natural Korean rendering (not literal). Long transcripts are chunked to preserve context.
- Proper nouns and technical terms keep original in parentheses: `강화학습(reinforcement learning)`.
- Filler words removed; paragraphs formed for readability.

### 6.2 Document → `document.md`
Blog-article style:
```markdown
# <Korean title>
> 원본: [YouTube](<url>) · 업로드: YYYY-MM-DD · 길이: Nm

## 서론
## 본론 (3–5 topic sections)
## 핵심 인사이트 (3–7 bullets)
## 더 알아보기
```
- Use `WebSearch` to verify/enrich claims: papers, products, people, concepts mentioned in the video.
- Cross-check factual claims against external sources; link them in "더 알아보기".

### 6.3 Debate → `debate.md`
3-round adversarial loop + synthesis:
```markdown
# 토론: <주제>

## Round 1
### 🟢 Pro
### 🔴 Con

## Round 2
### 🟢 Pro (재반론)
### 🔴 Con (재반박)

## Round 3
### 🟢 Pro
### 🔴 Con

## 🧭 종합
- 합의 지점
- 열린 질문
- 더 나아간 관점 (영상이 다루지 않은 새로운 프레임·후속 질문·실천적 제언)
```
Each later round must actually rebut the previous round — no paraphrasing. WebSearch used for evidence where relevant.

### 6.4 Channel README → `output/<handle>/README.md`
Regenerated after each video is finished. Table of video cards sorted by upload date (newest first): title · date · duration · 1-line summary · links to the four files in the video folder. Acts as a dashboard.

## 7. Execution Flow

**Channel mode (`/extract-channel`):**
1. Verify prerequisites (`yt-dlp`, `faster-whisper` installed).
2. Run `list_videos.py`. Show count + titles. Ask user to confirm before bulk processing.
3. For each video, create a task (TaskCreate) for progress visibility.
4. Per-video loop:
   - `fetch_subs.py` → if fail, `transcribe.py`.
   - Translate → document → debate (skip any step whose output file exists).
   - Write `meta.json` with title/url/upload_date/duration/subtitle_source.
5. Regenerate channel `README.md`.
6. Report: N succeeded, M skipped, K failed (with reasons).

**Single-video mode (`/extract-video`):**
1. Resolve channel handle from video metadata (`yt-dlp --dump-json`).
2. Create `output/<handle>/<dated_id>/` if absent.
3. Run per-video pipeline (identical to step 4 above).
4. Update channel `README.md` (create if absent, add/update this video's card).

## 8. Idempotency & Failure Handling

- Every output file is checked before (re)generation. Re-running the command after partial failure picks up where it left off.
- Per-video failure does not abort the batch. Error is recorded in `meta.json` under `error`, the video is counted as failed, the loop continues.
- Prerequisites missing → skill stops with install instructions; no partial state is written.

## 9. Out of Scope

- Automatic captions from YouTube (intentionally skipped).
- Video file retention (audio is temp-deleted; video is never downloaded).
- Non-English source languages (only English transcripts are produced, then translated to Korean). Videos in other languages will surface as transcription artifacts and can be addressed later.
- GUI / web server. Slash command only.

## 10. Dependencies

`requirements.txt`:
```
yt-dlp
faster-whisper
```

System: Python 3.10+, ffmpeg on PATH (yt-dlp audio extraction), CUDA toolkit with cuBLAS/cuDNN for GPU Whisper.
