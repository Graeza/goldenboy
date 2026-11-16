from datetime import datetime, timedelta, timezone
from typing import Optional
from config.settings import WINDOW_DAYS
from .database import latest_time, upsert_bars
from .provider import normalize, SECONDS, ProviderError


def utc_dt(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def backfill(provider, con, symbol: str, timeframe: str, start: datetime,
             end: datetime, now: Optional[datetime] = None) -> int:
    """Query nonoverlapping UTC time windows, each safely below the 5000 row limit."""
    if start >= end:
        raise ValueError("start must precede end")
    if timeframe not in WINDOW_DAYS:
        raise ValueError(timeframe)
    total = 0
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=WINDOW_DAYS[timeframe]), end)
        # Range ends inclusive on provider: use a one-second decrement to avoid overlap.
        request_end = window_end - timedelta(seconds=1)
        values = provider.fetch(symbol, timeframe, start=cursor, end=request_end)
        if len(values) >= 5000:
            raise ProviderError("Window returned >= 5000 rows; reduce WINDOW_DAYS to prevent truncation")
        bars = normalize(values, symbol, timeframe, now=now)
        total += upsert_bars(con, bars)
        print(f"{timeframe}: {cursor.date()} -> {window_end.date()}, fetched={len(values)}, stored={len(bars)}")
        cursor = window_end
    return total


def sync(provider, con, symbol: str, timeframe: str, now: Optional[datetime] = None) -> int:
    """Incremental refresh from the most recent closed bar, allowing overlap.

    For large gaps, use backfill. Does not silently discard gaps >5000 bars.
    """
    now = now or datetime.now(timezone.utc)
    last = latest_time(con, symbol, timeframe)
    if not last:
        raise ValueError(f"No existing {timeframe} bars. Run backfill first.")
    last_dt = utc_dt(last)
    overlap = timedelta(seconds=SECONDS[timeframe] * 2)
    start = last_dt - overlap
    if (now - start).total_seconds() / SECONDS[timeframe] >= 4900:
        print(f"{timeframe}: large gap detected, switching to windowed backfill")
        return backfill(provider, con, symbol, timeframe, start, now, now=now)
    rows = provider.fetch(symbol, timeframe, start=start, end=now)
    if len(rows) >= 5000:
        raise ProviderError("Sync response hit 5000-row limit, use backfill")
    bars = normalize(rows, symbol, timeframe, now=now)
    count = upsert_bars(con, bars)
    print(f"{timeframe}: refreshed {count} closed bars")
    return count
