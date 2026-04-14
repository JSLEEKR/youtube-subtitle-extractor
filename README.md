# youtube-subtitle-extractor

> A pipeline that turns YouTube videos and channels into **Korean knowledge bundles**.
> From the raw video to an English transcript, a natural Korean translation, a research-backed article, and a 3-round pro/con debate — all generated in one pass.

Built from **Claude Code skills plus four small Python scripts**. Deterministic work (video/subtitle download, Whisper transcription) runs in the scripts; language work (translation, research, debate) is performed directly by Claude Code skills inside the session.

---

## ✨ What you get

For each video, the following six files land in `output/<channel_handle>/<upload_date>_<video_id>/`:

| File | Contents |
|---|---|
| `video.mp4` | Original YouTube video (best quality via yt-dlp) |
| `transcript_en.txt` | Official English subtitles, or a Whisper transcript as fallback |
| `transcript_ko.md` | Natural Korean translation (idiomatic, not literal; proper nouns kept alongside) |
| `document.md` | Blog-article-style research document (sources verified via WebSearch) |
| `debate.md` | 3-round pro/con debate plus synthesis (each round explicitly rebuts the previous one) |
| `meta.json` | Metadata (title, upload date, duration, subtitle source, etc.) |

In channel mode, the bundle above is generated for every video in the time window, and the channel `README.md` is auto-updated as a dashboard.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────┐
│  Claude Code Skills (.claude/skills/)    │
│  ┌────────────────┐  ┌────────────────┐  │
│  │ extract-video  │  │extract-channel │  │
│  └───────┬────────┘  └───────┬────────┘  │
└──────────┼───────────────────┼───────────┘
           │                   │
           ▼                   ▼
┌──────────────────────────────────────────┐
│  Python scripts (scripts/)               │
│  ┌──────────────┐  ┌──────────────────┐  │
│  │ list_videos  │  │ fetch_video      │  │
│  │ fetch_subs   │  │ transcribe       │  │
│  └──────────────┘  └──────────────────┘  │
└──────────────────────────────────────────┘
```

- **Script layer**: deterministic and idempotent. Each script prints a single JSON line to stdout and reports failure via a non-zero exit code. If the output file already exists, it's skipped.
- **Skill layer**: language tasks (translation, research, debate) are performed inside the Claude Code session. Sources are verified and cited via `WebSearch`. The skills themselves are orchestration rather than implementation, so logic changes are easy.

---

## 🚀 Quick start

### Setup

```bash
# Install dependencies
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements-dev.txt
```

System requirements:

- **Python 3.10+**
- **ffmpeg** — must be on PATH (required by yt-dlp for audio/video extraction)
- **yt-dlp** — installed via `pip install`
- **faster-whisper** — uses large-v3 on GPU (CUDA) when available, falls back to CPU int8 otherwise

### Usage (inside a Claude Code session)

Process a single video:
```
/extract-video https://www.youtube.com/watch?v=<id>
```

Channel mode (all videos from the last 30 days):
```
/extract-channel https://www.youtube.com/@<handle> --days 30
```

Options:
- `--days N` — only videos from the last N days (default 30)
- `--limit N` — cap at N videos (for testing)
- `--skip-debate` — skip debate generation

Results accumulate under `output/<channel_handle>/`.

---

## 🔁 Pipeline stages (per video)

The nine stages orchestrated by `.claude/skills/extract-video/SKILL.md`:

1. **Metadata resolution** — parse video_id, title, upload_date, channel_handle via `yt-dlp`
2. **Write `meta.json`** — skipped if it already exists (idempotency)
3. **Video download** — `fetch_video.py` → `video.mp4` (pipeline continues on failure)
4. **Secure English transcript** — try official subtitles via `fetch_subs.py`; on `exit 2`, fall back to `transcribe.py` (Whisper)
5. **Korean translation** — `transcript_ko.md`, idiomatic, proper nouns / technical terms kept alongside
6. **Research document** — `document.md`, with sources verified and cited via WebSearch
7. **Pro/con debate** — `debate.md`, 3 rounds plus synthesis; each round explicitly rebuts the previous one
8. **Channel README refresh** — regenerate the dashboard
9. **Final report** — print generated/skipped files and output path

Failure handling:
- Step 3 (video download) failure is **non-fatal** — log the error and continue
- Step 4 (transcript) failure is fatal — stop and report
- Steps 5–7 failures are recorded in `meta.json`; partial results are preserved
- Every stage is **idempotent** — rerunning picks up only the missing pieces

---

## 🧪 Tests

```bash
pytest -v
```

Unit tests cover only the pure functions in `scripts/_common.py` (date-window filter, VTT parser, directory-name formatter). Script bodies are validated by integration smoke tests.

---

## 📁 Project layout

```
youtube-subtitle-extractor/
├── scripts/
│   ├── _common.py         # Pure helpers (date filter, VTT parser, dir names)
│   ├── list_videos.py     # Channel → filtered list of videos as JSON
│   ├── fetch_video.py     # Download the source video → video.mp4
│   ├── fetch_subs.py      # Official English subtitles → transcript_en.txt
│   └── transcribe.py      # Audio download + Whisper → transcript_en.txt
├── tests/
│   ├── test_common.py     # Unit tests for the pure helpers
│   └── fixtures/sample.vtt
├── .claude/skills/
│   ├── extract-video/SKILL.md
│   └── extract-channel/SKILL.md
├── docs/superpowers/      # Plan / spec documents
├── requirements.txt       # Runtime: yt-dlp, faster-whisper
├── requirements-dev.txt   # Dev: pytest
└── README.md
```

`output/` is gitignored and is not committed to the repository.

---

## 🧠 Design principles

1. **Each script does exactly one thing.** On success, emit a single JSON line on stdout; on failure, stderr plus a non-zero exit code.
2. **Side effects live only inside `main()`.** Branching logic is moved into pure functions in `_common.py` so it stays testable.
3. **Skills orchestrate; scripts are deterministic.** Scripts never call Claude.
4. **Every stage is idempotent.** If the output file exists, skip it. Reruns resume where the previous run left off.
5. **Failure never corrupts partial progress.** A video-download failure doesn't block the transcript; a failure on one video doesn't block the next.

---

## 📝 License

MIT

---

## 🙏 Credits

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube downloading
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Whisper inference on CTranslate2
- [Claude Code](https://claude.com/claude-code) — orchestration runtime
