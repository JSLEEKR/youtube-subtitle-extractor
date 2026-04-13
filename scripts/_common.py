import re
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


_TIMESTAMP_RE = re.compile(r"\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}.*")
_TAG_RE = re.compile(r"<[^>]+>")


def vtt_to_plain_text(vtt: str) -> str:
    """Strip WEBVTT headers, cue timestamps, and inline tags; join cue text.

    Consecutive duplicate lines (common in auto-generated subs that repeat cues)
    are collapsed. Returns a newline-joined paragraph-ish text.
    """
    cues: list[list[str]] = []  # Track cue boundaries
    current_cue: list[str] = []

    for raw in vtt.splitlines():
        line = raw.strip()

        # Blank lines mark cue boundaries
        if not line:
            if current_cue:
                cues.append(current_cue)
                current_cue = []
            continue

        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if _TIMESTAMP_RE.match(line):
            continue
        if line.isdigit():  # cue number
            continue

        line = _TAG_RE.sub("", line)

        # Add line to current cue
        current_cue.append(line)

    # Don't forget the last cue if it exists
    if current_cue:
        cues.append(current_cue)

    # Merge lines within each cue and join cues with newlines
    merged: list[str] = []
    for cue_lines in cues:
        # Join lines within a cue with space when previous doesn't end with punctuation
        cue_text: list[str] = []
        for line in cue_lines:
            if cue_text and not cue_text[-1].endswith((".", "!", "?", ":", ";", ",")):
                cue_text[-1] = cue_text[-1] + " " + line
            else:
                cue_text.append(line)
        merged.extend(cue_text)

    # Deduplicate consecutive lines globally (handles cues that repeat)
    deduped: list[str] = []
    for line in merged:
        if not deduped or deduped[-1] != line:
            deduped.append(line)

    return "\n".join(deduped)
