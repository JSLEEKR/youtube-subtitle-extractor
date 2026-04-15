"""Background daemon that drains a git-backed work queue.

It expects two repository checkouts on disk:
- IDEA_SITE_REPO: a private repo with `_queue/`, `_state/{processing,done,failed}/`,
  and `content/` directories. Submissions land in `_queue/<id>.json`.
- IDEA_PIPELINE_REPO: this repo (youtube-subtitle-extractor), where the actual
  extract-video skill runs.

Each tick:
  1. fast-forward IDEA_SITE_REPO from origin/main
  2. recover stuck `_state/processing/` entries that exceeded MAX_PROCESSING_AGE
  3. claim the oldest queued entry (skip duplicates already in `_state/done/`)
  4. run `claude -p "/extract-video <url>"` from IDEA_PIPELINE_REPO
  5. verify the 5 expected output files
  6. copy them into IDEA_SITE_REPO/content/<handle>/<dated_id>/
  7. move the queue entry to `_state/done/` and push

Stdlib only. No third-party deps. Works on Windows + Unix.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# ---------- configuration ---------------------------------------------------

TICK_SECONDS = int(os.environ.get("DAEMON_TICK_SECONDS", "90"))
MAX_PROCESSING_AGE_S = int(os.environ.get("DAEMON_STUCK_AGE_SECONDS", str(15 * 60)))
MAX_ATTEMPTS = int(os.environ.get("DAEMON_MAX_ATTEMPTS", "3"))
RETRY_COOLDOWN_S = int(os.environ.get("DAEMON_RETRY_COOLDOWN_SECONDS", str(10 * 60)))
CLAUDE_TIMEOUT_S = int(os.environ.get("DAEMON_CLAUDE_TIMEOUT_SECONDS", str(45 * 60)))
CLAUDE_MAX_BUDGET = os.environ.get("DAEMON_CLAUDE_MAX_BUDGET_USD", "5")
GIT_REMOTE = os.environ.get("DAEMON_GIT_REMOTE", "origin")
GIT_BRANCH = os.environ.get("DAEMON_GIT_BRANCH", "main")

EXPECTED_FILES = (
    "meta.json",
    "transcript_en.txt",
    "transcript_ko.md",
    "document.md",
    "debate.md",
)
COPY_FILES = EXPECTED_FILES  # video.mp4 is intentionally excluded


# ---------- logging ---------------------------------------------------------


def log(msg: str, *, level: str = "info") -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [{level}] {msg}", flush=True)


def fatal(msg: str) -> None:
    log(msg, level="fatal")
    sys.exit(2)


# ---------- exceptions ------------------------------------------------------


class PipelineError(RuntimeError):
    """Raised when the pipeline produced no usable output."""

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class AuthError(PipelineError):
    """Claude CLI reported an auth failure — pause until operator intervenes."""


# ---------- env helpers -----------------------------------------------------


def required_env(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        fatal(f"missing required env var {name}")
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        fatal(f"{name}={p} does not exist")
    return p


def find_executable(name: str) -> str:
    """Resolve a CLI by name. On Windows, also try the .cmd suffix."""
    found = shutil.which(name)
    if found:
        return found
    if os.name == "nt":
        found = shutil.which(name + ".cmd")
        if found:
            return found
    fatal(f"{name} not found on PATH")
    return ""  # unreachable


# ---------- git -------------------------------------------------------------


def git(repo: Path, *args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "-C", str(repo), *args]
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
    )


def git_sync(repo: Path) -> None:
    git(repo, "fetch", GIT_REMOTE, GIT_BRANCH)
    git(repo, "reset", "--hard", f"{GIT_REMOTE}/{GIT_BRANCH}")


def git_commit(repo: Path, message: str, paths: Iterable[Path]) -> bool:
    """Stage and commit. Returns True if a commit was created."""
    rel_paths: list[str] = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(repo.resolve())
        except ValueError:
            log(f"skip non-repo path: {p}", level="warn")
            continue
        rel_paths.append(str(rel).replace("\\", "/"))
    if not rel_paths:
        return False
    # Only `git add` paths that still exist on disk. Paths removed by a prior
    # `git mv` (the source side of a rename) are already staged as deletions
    # and would cause "pathspec did not match any files" here.
    existing_rel = [p for p in rel_paths if (repo / p).exists()]
    if existing_rel:
        git(repo, "add", "--", *existing_rel)
    res = git(repo, "status", "--porcelain", capture=True)
    if not res.stdout.strip():
        return False
    git(repo, "commit", "-m", message)
    return True


def git_push(repo: Path) -> None:
    # Push with retries — transient network blips shouldn't kill the daemon.
    for attempt in range(3):
        try:
            git(repo, "push", GIT_REMOTE, GIT_BRANCH)
            return
        except subprocess.CalledProcessError as e:
            log(f"git push attempt {attempt + 1} failed: {e}", level="warn")
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


# ---------- queue model -----------------------------------------------------


@dataclass
class Entry:
    id: str
    url: str
    video_id: str
    submitted_at: str
    attempts: int = 0
    status: str = "queued"
    error: Optional[str] = None
    failed_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    handle: Optional[str] = None
    dated_id: Optional[str] = None
    completed_at: Optional[str] = None

    @classmethod
    def load(cls, path: Path) -> "Entry":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**{k: data.get(k) for k in cls.__dataclass_fields__})

    def dump(self, path: Path) -> None:
        path.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------- pipeline plumbing ----------------------------------------------


def yt_dlp_metadata(pipeline_repo: Path, url: str) -> tuple[str, str, str]:
    """Return (video_id, upload_date_YYYYMMDD, channel_handle).

    Used to predict the output directory before invoking Claude.
    """
    res = subprocess.run(
        [
            "yt-dlp",
            "--skip-download",
            "--print",
            "%(id)s|%(upload_date)s|%(uploader_id)s|%(channel)s",
            url,
        ],
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=str(pipeline_repo),
        timeout=120,
    )
    line = res.stdout.strip().splitlines()[-1]
    parts = line.split("|", 3)
    if len(parts) < 4:
        raise PipelineError(f"yt-dlp returned unexpected line: {line!r}")
    video_id, upload_date, uploader_id, channel = parts
    handle = uploader_id or sanitize_handle(channel)
    if not handle:
        handle = "@unknown"
    if not handle.startswith("@"):
        handle = "@" + handle
    return video_id, upload_date or "00000000", handle


def sanitize_handle(channel: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "", channel or "")
    return safe[:40]


def predicted_output_dir(pipeline_repo: Path, handle: str, upload_date: str, video_id: str) -> Path:
    if len(upload_date) == 8:
        dated = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}_{video_id}"
    else:
        dated = f"0000-00-00_{video_id}"
    return pipeline_repo / "output" / handle / dated


def all_files_present(directory: Path) -> bool:
    return directory.is_dir() and all((directory / f).is_file() for f in EXPECTED_FILES)


# ---------- claude invocation -----------------------------------------------


AUTH_ERROR_MARKERS = (
    "not logged in",
    "authentication required",
    "401 unauthorized",
    "invalid api key",
    "claude login",
)


def run_claude(
    claude_bin: str,
    pipeline_repo: Path,
    url: str,
    *,
    plain_fallback: bool,
) -> subprocess.CompletedProcess[str]:
    if plain_fallback:
        prompt = (
            f"Follow .claude/skills/extract-video/SKILL.md exactly on this URL: {url}. "
            "Skip step 8 (channel README)."
        )
    else:
        prompt = f"/extract-video {url}"

    cmd = [
        claude_bin,
        "-p",
        "--permission-mode",
        "bypassPermissions",
        "--max-budget-usd",
        CLAUDE_MAX_BUDGET,
        prompt,
    ]
    env = os.environ.copy()
    env["SKIP_CHANNEL_README"] = "1"
    log(f"claude invocation ({'plain' if plain_fallback else 'slash'}): {' '.join(cmd)}")

    return subprocess.run(
        cmd,
        cwd=str(pipeline_repo),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=CLAUDE_TIMEOUT_S,
        check=False,
    )


def detect_auth_error(*streams: str) -> bool:
    blob = " ".join(s or "" for s in streams).lower()
    return any(marker in blob for marker in AUTH_ERROR_MARKERS)


def execute_pipeline(
    claude_bin: str,
    pipeline_repo: Path,
    entry: Entry,
) -> Path:
    """Run the pipeline twice if needed. Return the verified output directory."""
    video_id, upload_date, handle = yt_dlp_metadata(pipeline_repo, entry.url)
    expected = predicted_output_dir(pipeline_repo, handle, upload_date, video_id)
    expected.parent.mkdir(parents=True, exist_ok=True)

    # Attempt 1 — slash command
    res = run_claude(claude_bin, pipeline_repo, entry.url, plain_fallback=False)
    if detect_auth_error(res.stdout, res.stderr):
        raise AuthError("claude reported auth failure during attempt 1")
    if not all_files_present(expected):
        log(
            f"attempt 1 produced no complete output (exit={res.returncode}); "
            f"falling back to plain prompt",
            level="warn",
        )
        # Attempt 2 — plain English instruction
        res = run_claude(claude_bin, pipeline_repo, entry.url, plain_fallback=True)
        if detect_auth_error(res.stdout, res.stderr):
            raise AuthError("claude reported auth failure during attempt 2")

    if not all_files_present(expected):
        tail = (res.stderr or res.stdout or "").strip().splitlines()[-20:]
        raise PipelineError(
            "expected output files missing after both attempts. "
            f"dir={expected} exit={res.returncode} tail={tail!r}"
        )

    entry.handle = handle
    dated_name = expected.name
    entry.dated_id = dated_name
    return expected


# ---------- queue ops -------------------------------------------------------


class QueueRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.queue = root / "_queue"
        self.processing = root / "_state" / "processing"
        self.done = root / "_state" / "done"
        self.failed = root / "_state" / "failed"
        for d in (self.queue, self.processing, self.done, self.failed):
            d.mkdir(parents=True, exist_ok=True)

    def list_queued(self) -> list[Path]:
        items = sorted(p for p in self.queue.glob("*.json") if p.is_file())
        return [p for p in items if self._is_eligible(p)]

    def _is_eligible(self, p: Path) -> bool:
        try:
            entry = Entry.load(p)
        except Exception:
            return True  # unparseable, let claim_next surface the error
        if entry.next_attempt_at:
            try:
                if datetime.now(timezone.utc) < parse_iso(entry.next_attempt_at):
                    return False
            except Exception:
                pass
        return True

    def video_id_in_done(self, video_id: str) -> Optional[Path]:
        for p in self.done.glob("*.json"):
            if video_id in p.name:
                return p
        return None

    def recover_stuck(self) -> int:
        recovered = 0
        cutoff = time.time() - MAX_PROCESSING_AGE_S
        for p in self.processing.glob("*.json"):
            if p.stat().st_mtime < cutoff:
                try:
                    entry = Entry.load(p)
                    entry.attempts += 1
                    entry.status = "queued"
                    entry.error = "recovered after stuck in processing"
                    target = self.queue / p.name
                    entry.dump(p)
                    git(self.root, "mv", str(p.relative_to(self.root)).replace("\\", "/"),
                        str(target.relative_to(self.root)).replace("\\", "/"))
                    recovered += 1
                    log(f"recovered stuck entry {p.name} (attempt {entry.attempts})")
                except Exception as e:
                    log(f"failed to recover {p.name}: {e}", level="warn")
        return recovered

    def claim_next(self) -> Optional[tuple[Entry, Path]]:
        for src in self.list_queued():
            try:
                entry = Entry.load(src)
            except Exception as e:
                log(f"unparseable queue entry {src.name}: {e}", level="warn")
                self._move_to_failed(src, error=f"invalid json: {e}")
                continue

            existing = self.video_id_in_done(entry.video_id)
            if existing:
                log(f"skip duplicate {entry.video_id} (already in done as {existing.name})")
                self._git_remove(src, message=f"queue: drop duplicate {entry.video_id}")
                continue

            dst = self.processing / src.name
            entry.status = "processing"
            entry.next_attempt_at = None
            entry.dump(src)
            git(self.root, "mv",
                str(src.relative_to(self.root)).replace("\\", "/"),
                str(dst.relative_to(self.root)).replace("\\", "/"))
            git_commit(self.root, f"queue: claim {entry.video_id}", [dst])
            try:
                git_push(self.root)
            except subprocess.CalledProcessError as e:
                log(f"push after claim failed; will rely on next tick to resync: {e}", level="warn")
            return entry, dst
        return None

    def mark_done(self, entry: Entry, src: Path) -> None:
        entry.status = "done"
        entry.completed_at = now_iso()
        dst = self.done / src.name
        entry.dump(src)
        git(self.root, "mv",
            str(src.relative_to(self.root)).replace("\\", "/"),
            str(dst.relative_to(self.root)).replace("\\", "/"))

    def mark_failed_terminal(self, entry: Entry, src: Path, error: str) -> None:
        entry.status = "failed"
        entry.error = error
        entry.failed_at = now_iso()
        dst = self.failed / src.name
        entry.dump(src)
        git(self.root, "mv",
            str(src.relative_to(self.root)).replace("\\", "/"),
            str(dst.relative_to(self.root)).replace("\\", "/"))

    def requeue_transient(self, entry: Entry, src: Path, error: str) -> None:
        entry.attempts += 1
        entry.error = error
        if entry.attempts >= MAX_ATTEMPTS:
            self.mark_failed_terminal(entry, src, error=f"max attempts: {error}")
            return
        entry.status = "queued"
        entry.next_attempt_at = (
            datetime.now(timezone.utc).fromtimestamp(time.time() + RETRY_COOLDOWN_S, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        dst = self.queue / src.name
        entry.dump(src)
        git(self.root, "mv",
            str(src.relative_to(self.root)).replace("\\", "/"),
            str(dst.relative_to(self.root)).replace("\\", "/"))

    def _move_to_failed(self, src: Path, *, error: str) -> None:
        dst = self.failed / src.name
        try:
            git(self.root, "mv",
                str(src.relative_to(self.root)).replace("\\", "/"),
                str(dst.relative_to(self.root)).replace("\\", "/"))
            payload = {"error": error, "failed_at": now_iso()}
            dst.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            git(self.root, "add", str(dst.relative_to(self.root)).replace("\\", "/"))
        except subprocess.CalledProcessError:
            pass

    def _git_remove(self, src: Path, message: str) -> None:
        git(self.root, "rm", str(src.relative_to(self.root)).replace("\\", "/"))
        git_commit(self.root, message, [src])
        with contextlib.suppress(subprocess.CalledProcessError):
            git_push(self.root)


# ---------- copy outputs ----------------------------------------------------


def copy_into_content(site_repo: Path, output_dir: Path, handle: str) -> Path:
    dated = output_dir.name
    target = site_repo / "content" / handle / dated
    target.mkdir(parents=True, exist_ok=True)
    for name in COPY_FILES:
        src_file = output_dir / name
        if src_file.is_file():
            shutil.copy2(src_file, target / name)
    return target


# ---------- locking ---------------------------------------------------------


class LockHeld(RuntimeError):
    pass


def acquire_lock(repo: Path) -> Path:
    lock = repo / ".daemon.lock"
    if lock.exists():
        try:
            other_pid = int(lock.read_text(encoding="utf-8").strip())
        except Exception:
            other_pid = 0
        if other_pid and pid_alive(other_pid):
            raise LockHeld(f"daemon already running as pid {other_pid}")
        log(f"removing stale lock from pid {other_pid or '?'}", level="warn")
        lock.unlink()
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        res = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return str(pid) in res.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def release_lock(lock: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        lock.unlink()


# ---------- pause switch ----------------------------------------------------


def is_paused(repo: Path) -> bool:
    return (repo / ".pause").exists()


# ---------- main loop -------------------------------------------------------


def tick(
    queue: QueueRepo,
    pipeline_repo: Path,
    claude_bin: str,
) -> bool:
    """One iteration. Returns True if a job was processed."""
    if is_paused(queue.root):
        log("paused (.pause file present); skipping tick")
        return False

    git_sync(queue.root)
    queue.recover_stuck()

    claimed = queue.claim_next()
    if not claimed:
        return False
    entry, processing_path = claimed
    log(f"claimed {entry.id} (video_id={entry.video_id} url={entry.url})")

    try:
        output_dir = execute_pipeline(claude_bin, pipeline_repo, entry)
    except AuthError as e:
        log(f"AUTH ERROR — pausing daemon: {e}", level="fatal")
        queue.mark_failed_terminal(entry, processing_path, error=f"auth: {e}")
        git_commit(queue.root, f"queue: auth-fail {entry.video_id}", [processing_path, queue.failed / processing_path.name])
        with contextlib.suppress(subprocess.CalledProcessError):
            git_push(queue.root)
        (queue.root / ".pause").write_text(f"auto-paused at {now_iso()}: {e}\n", encoding="utf-8")
        return True
    except subprocess.TimeoutExpired:
        queue.requeue_transient(entry, processing_path, error="claude subprocess timeout")
        git_commit(queue.root, f"queue: requeue (timeout) {entry.video_id}",
                   [processing_path, queue.queue / processing_path.name])
        with contextlib.suppress(subprocess.CalledProcessError):
            git_push(queue.root)
        return True
    except PipelineError as e:
        if e.transient:
            queue.requeue_transient(entry, processing_path, error=str(e))
            git_commit(queue.root, f"queue: requeue (transient) {entry.video_id}",
                       [processing_path, queue.queue / processing_path.name])
        else:
            queue.mark_failed_terminal(entry, processing_path, error=str(e))
            git_commit(queue.root, f"queue: fail {entry.video_id}",
                       [processing_path, queue.failed / processing_path.name])
        with contextlib.suppress(subprocess.CalledProcessError):
            git_push(queue.root)
        return True
    except Exception as e:
        log(f"unexpected error: {e}\n{traceback.format_exc()}", level="error")
        queue.requeue_transient(entry, processing_path, error=f"unexpected: {e}")
        git_commit(queue.root, f"queue: requeue (error) {entry.video_id}",
                   [processing_path, queue.queue / processing_path.name])
        with contextlib.suppress(subprocess.CalledProcessError):
            git_push(queue.root)
        return True

    target = copy_into_content(queue.root, output_dir, entry.handle or "@unknown")
    queue.mark_done(entry, processing_path)
    paths_to_commit = [target, processing_path, queue.done / processing_path.name]
    git_commit(
        queue.root,
        f"content: add {entry.video_id} ({entry.handle})",
        paths_to_commit,
    )
    git_push(queue.root)
    log(f"completed {entry.id} → {target}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="idea-site queue daemon")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    parser.add_argument("--site-repo", help="override IDEA_SITE_REPO")
    parser.add_argument("--pipeline-repo", help="override IDEA_PIPELINE_REPO")
    args = parser.parse_args()

    if args.site_repo:
        os.environ["IDEA_SITE_REPO"] = args.site_repo
    if args.pipeline_repo:
        os.environ["IDEA_PIPELINE_REPO"] = args.pipeline_repo

    site_repo = required_env("IDEA_SITE_REPO")
    pipeline_repo = required_env("IDEA_PIPELINE_REPO")
    claude_bin = find_executable("claude")
    find_executable("git")
    find_executable("yt-dlp")

    log(f"site_repo   = {site_repo}")
    log(f"pipeline    = {pipeline_repo}")
    log(f"claude bin  = {claude_bin}")

    # quick claude auth probe
    try:
        v = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        log(f"claude --version: {v.stdout.strip() or v.stderr.strip()}")
    except Exception as e:
        log(f"claude --version failed: {e}", level="warn")

    queue = QueueRepo(site_repo)

    try:
        lock = acquire_lock(site_repo)
    except LockHeld as e:
        fatal(str(e))

    stopping = {"flag": False}

    def handle_signal(signum, _frame):  # type: ignore[no-untyped-def]
        log(f"signal {signum} received — finishing current tick then exiting")
        stopping["flag"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(Exception):
            signal.signal(sig, handle_signal)

    try:
        if args.once:
            tick(queue, pipeline_repo, claude_bin)
            return 0

        log(f"starting tick loop (interval={TICK_SECONDS}s)")
        while not stopping["flag"]:
            try:
                tick(queue, pipeline_repo, claude_bin)
            except subprocess.CalledProcessError as e:
                log(f"git error in tick: {e}", level="error")
            except Exception as e:
                log(f"tick crashed: {e}\n{traceback.format_exc()}", level="error")
            for _ in range(TICK_SECONDS):
                if stopping["flag"]:
                    break
                time.sleep(1)
        return 0
    finally:
        release_lock(lock)


if __name__ == "__main__":
    sys.exit(main())
