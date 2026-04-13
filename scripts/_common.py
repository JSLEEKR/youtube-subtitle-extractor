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
