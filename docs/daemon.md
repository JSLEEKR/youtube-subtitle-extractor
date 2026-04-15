# daemon.py — queue drainer

`scripts/daemon.py` is a stdlib-only background worker that drains a git-backed
work queue and runs the `extract-video` pipeline for each submission. It is
separate from the interactive Claude Code workflow: the daemon is how an
external system (e.g. a web submit form) gets the pipeline to run without a
human at the REPL.

The daemon does NOT touch this repo's own `output/_queue.txt` file — that is an
unused historical artifact. The queue the daemon reads from lives in a
**different** repository (the "site repo"), specified by `IDEA_SITE_REPO`.

## Architecture

```
site_repo/                       pipeline_repo (this repo)
├── _queue/<id>.json      <───── daemon polls
├── _state/
│   ├── processing/              ┌── runs `claude -p "/extract-video <url>"`
│   ├── done/                    │
│   └── failed/                  └── verifies output/<handle>/<dated>/*
└── content/<handle>/    <───── copies the 5 text files into site_repo
    └── <dated_id>/
```

Each queue submission is a single JSON file. State is encoded by which
directory the file lives in — no separate state store. Every state transition
is a `git mv` + commit + push.

The 5 files the daemon copies (never `video.mp4`):

- `meta.json`
- `transcript_en.txt`
- `transcript_ko.md`
- `document.md`
- `debate.md`

## Required environment

| Variable             | Purpose                                                       |
| -------------------- | ------------------------------------------------------------- |
| `IDEA_SITE_REPO`     | Absolute path to the site repo clone (contains `_queue/`)     |
| `IDEA_PIPELINE_REPO` | Absolute path to this repo (youtube-subtitle-extractor)       |

Required tools on `PATH`: `git`, `claude` (Claude Code CLI), `yt-dlp`, Python 3.10+.

The daemon inherits Claude Code's existing login — run `claude --version`
first to confirm it is logged in. If auth fails during a tick, the daemon
will automatically drop a `.pause` file in the site repo and stop claiming new
work until an operator intervenes.

## Optional tuning

| Variable                           | Default  | Meaning                                          |
| ---------------------------------- | -------- | ------------------------------------------------ |
| `DAEMON_TICK_SECONDS`              | 90       | Poll interval                                    |
| `DAEMON_STUCK_AGE_SECONDS`         | 900      | When to reclaim entries stuck in `_state/processing/` |
| `DAEMON_MAX_ATTEMPTS`              | 3        | Transient-failure attempt cap before terminal fail |
| `DAEMON_RETRY_COOLDOWN_SECONDS`    | 600      | Cooldown before a transient failure is re-eligible |
| `DAEMON_CLAUDE_TIMEOUT_SECONDS`    | 2700     | `claude -p` subprocess timeout (45 minutes)      |
| `DAEMON_CLAUDE_MAX_BUDGET_USD`     | 5        | `--max-budget-usd` value per invocation          |
| `DAEMON_GIT_REMOTE`                | origin   | Git remote name                                  |
| `DAEMON_GIT_BRANCH`                | main     | Git branch                                       |

## Running

One-shot (handy for verification):

```cmd
set IDEA_SITE_REPO=C:\claude\idea-site
set IDEA_PIPELINE_REPO=C:\claude\youtube-subtitle-extractor
python scripts\daemon.py --once
```

Continuous:

```cmd
scripts\daemon.cmd
```

`daemon.cmd` activates `.venv\Scripts\activate.bat` if present, then runs the
Python script. Use `Ctrl+C` to request a graceful shutdown — the daemon
finishes the current tick before exiting.

## Operator controls

**Pause** — drop an empty `.pause` file in the site repo:

```cmd
echo paused > %IDEA_SITE_REPO%\.pause
```

Delete the file to resume. Paused ticks only skip work claims — the daemon
continues to fetch and recover stuck entries so that a long pause does not
orphan anything.

**Single lock** — the daemon writes its PID to `%IDEA_SITE_REPO%\.daemon.lock`.
If a previous run crashed without cleaning up, the next startup checks whether
the recorded PID is still alive and reclaims the lock if not.

**Force-retry a failed entry** — move the JSON from `_state/failed/` back into
`_queue/`, reset `attempts` to 0, and commit + push. The daemon will pick it
up on the next tick.

**Re-run an already-done entry** — delete the entry from `_state/done/` and
submit the URL again through the queue.

## Failure classes

The daemon distinguishes transient and terminal failures:

- **Transient** — yt-dlp 429, `git push` connection reset, `claude` subprocess
  timeout. These increment `attempts` and go back to `_queue/` with a
  `next_attempt_at` cooldown. After `DAEMON_MAX_ATTEMPTS`, they become
  terminal.
- **Terminal** — pipeline returned 0 but no output files, "Video unavailable",
  auth error, copy-step exception. These move to `_state/failed/` with an
  `error` field in the JSON.

Auth errors additionally trigger automatic pause.

## Slash-command fallback

The daemon first invokes:

```
claude -p --permission-mode bypassPermissions --max-budget-usd 5 "/extract-video <url>"
```

If after the subprocess exits the 5 expected files are not all present, the
daemon retries once with a plain-English prompt that references the skill file
directly:

```
Follow .claude/skills/extract-video/SKILL.md exactly on this URL: <url>.
Skip step 8 (channel README).
```

Both attempts inherit `SKIP_CHANNEL_README=1`, which tells the skill to leave
the per-channel README alone — dashboards are a concept the interactive repo
uses but the daemon does not need.

## Logs

All output goes to stdout (daemon and subprocesses alike). Redirect to a file
in production:

```cmd
scripts\daemon.cmd > logs\daemon.log 2>&1
```

For a Windows service, use `nssm install idea-daemon "C:\claude\youtube-subtitle-extractor\scripts\daemon.cmd"`
and configure it to redirect stdout/stderr to your log directory. This is
outside the scope of the daemon itself — the daemon only requires that its
stdout is captured somewhere readable.
