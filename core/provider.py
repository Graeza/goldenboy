from datetime import datetime, timezone, timedelta
from typing import Optional
import math
import time

import requests

SECONDS = {"5min": 300, "1h": 3600, "1day": 86400}

class ProviderError(RuntimeError):
    pass

class TwelveDataProvider:
    BASE_URL = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key: str, session=None, min_interval_seconds: float = 8.0):
        if not api_key or api_key == "your_api_key_here":
            raise ValueError("Set TWELVE_DATA_API_KEY in your .env file")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.min_interval_seconds = min_interval_seconds
        self._last_request = None

    def fetch(self, symbol: str, timeframe: str, start=None, end=None, outputsize=None) -> list[dict]:
        if timeframe not in SECONDS:
            raise ValueError(f"Unsupported interval: {timeframe}")
        if self._last_request is not None:
            remaining = self.min_interval_seconds - (time.monotonic() - self._last_request)
            if remaining > 0:
                time.sleep(remaining)
        params = {"apikey": self.api_key, "symbol": symbol, "interval": timeframe,
                  "format": "JSON", "order": "asc"}
        if timeframe != "1day":
            params["timezone"] = "UTC"
        if start is not None:
            params["start_date"] = format_api_date(start, timeframe)
        if end is not None:
            params["end_date"] = format_api_date(end, timeframe)
        if outputsize is not None:
            if not 1 <= outputsize <= 5000:
                raise ValueError("outputsize must be between 1 and 5000")
            params["outputsize"] = outputsize
        self._last_request = time.monotonic()
        try:
            response = self.session.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"Twelve Data HTTP/JSON error: {exc}") from exc
        if data.get("status") == "error" or "values" not in data:
            raise ProviderError(f"Twelve Data API error: {data.get('message', str(data)[:250])}")
        return data["values"]


def format_api_date(value: datetime, timeframe: str) -> str:
    if value.tzinfo is None:
        raise ValueError("Datetime must have timezone information")
    utc = value.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%d" if timeframe == "1day" else "%Y-%m-%dT%H:%M:%S")


def normalize(raw_rows: list[dict], symbol: str, timeframe: str,
              now: Optional[datetime] = None, include_open=False) -> list[dict]:
    """Retain closed candles only by default. Daily bars use conservative UTC day boundary.

    The provider's daily candle has a session-date label, not necessarily a UTC
    midnight close; until its finalization semantics are verified, today's daily
    candle is withheld. Never treat bar timestamp as a close timestamp.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out = []
    seen = set()
    for item in raw_rows:
        if timeframe == "1day":
            candle_date = datetime.strptime(item["datetime"][:10], "%Y-%m-%d").date()
            stamp = candle_date.isoformat()
            closed = candle_date < now.date()
        else:
            t = datetime.fromisoformat(item["datetime"].replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)  # Request asks for UTC response.
            t = t.astimezone(timezone.utc)
            stamp = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            closed = t + timedelta(seconds=SECONDS[timeframe]) <= now
        if not closed and not include_open:
            continue
        if stamp in seen:
            continue
        seen.add(stamp)
        try:
            prices = [float(item[x]) for x in ("open", "high", "low", "close")]
            if not all(math.isfinite(p) and p > 0 for p in prices):
                raise ValueError("non-positive or non-finite price")
            op, hi, lo, cl = prices
            if hi < max(op, cl, lo) or lo > min(op, cl, hi):
                raise ValueError("invalid OHLC range")
            volume = item.get("volume")
            volume = float(volume) if volume not in (None, "") else None
            if volume is not None and (not math.isfinite(volume) or volume < 0):
                raise ValueError("invalid volume")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError(f"Bad {timeframe} candle at {stamp}: {exc}") from exc
        out.append({"symbol": symbol, "timeframe": timeframe, "time": stamp,
                    "open": op, "high": hi, "low": lo, "close": cl,
                    "volume": volume, "source": "twelvedata", "is_closed": int(closed),
                    "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return sorted(out, key=lambda r: r["time"])
