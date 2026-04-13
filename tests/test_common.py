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
