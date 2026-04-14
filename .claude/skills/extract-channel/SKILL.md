---
name: extract-channel
description: Process all recent videos from a YouTube channel — lists videos within a date window, then runs the per-video extract pipeline (subs → translate → research → debate) for each. Output lands in `output/<channel_handle>/`.
---

# extract-channel

You run the full channel pipeline: list recent videos, then loop the per-video extract pipeline over them. The per-video pipeline is defined in `.claude/skills/extract-video/SKILL.md` — steps 1–9 of that skill are the "per-video pipeline" referenced below.

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
2. Run the **per-video pipeline** (steps 1–9 from `.claude/skills/extract-video/SKILL.md`) using the video's URL.
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
