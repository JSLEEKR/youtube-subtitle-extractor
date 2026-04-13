from datetime import date
from pathlib import Path
from scripts._common import filter_by_date_window, vtt_to_plain_text

FIXTURES = Path(__file__).parent / "fixtures"


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
