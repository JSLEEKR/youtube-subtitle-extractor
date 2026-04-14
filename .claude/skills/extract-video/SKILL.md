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
