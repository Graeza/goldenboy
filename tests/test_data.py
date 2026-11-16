import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.database import connect, upsert_bars, stats
from core.provider import normalize
from core.pipeline import backfill, sync

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

def candle(dt):
    return {"datetime": dt, "open": "2000", "high": "2010", "low": "1995", "close": "2002"}

class FakeProvider:
    def __init__(self):
        self.requests = []
    def fetch(self, symbol, timeframe, start=None, end=None, outputsize=None):
        self.requests.append((symbol,timeframe,start,end))
        return [candle("2026-11-13 11:50:00"), candle("2026-11-13 11:55:00")]

class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = connect(Path(self.tmp.name)/"db.sqlite")
    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()
    def test_closed_and_open_bars(self):
        raw = [candle("2026-11-16 11:50:00"), candle("2026-11-16 11:55:00")]
        result = normalize(raw,"XAU/USD","5min", now=datetime(2026,11,16,11,57,tzinfo=timezone.utc))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["time"],"2026-11-16T11:50:00Z")
    def test_upsert_is_idempotent(self):
        bar = normalize([candle("2026-11-13 11:50:00")], "XAU/USD", "5min",now=NOW)
        upsert_bars(self.con,bar)
        upsert_bars(self.con,bar)
        self.assertEqual(stats(self.con,"XAU/USD")[0]["bars"],1)
    def test_backfill_and_sync(self):
        provider = FakeProvider()
        count = backfill(provider,self.con,"XAU/USD","5min",NOW-timedelta(days=2),NOW,now=NOW)
        self.assertEqual(count,2)
        self.assertEqual(stats(self.con,"XAU/USD")[0]["bars"],2)
        self.assertEqual(sync(provider,self.con,"XAU/USD","5min",now=NOW),2)
        self.assertEqual(stats(self.con,"XAU/USD")[0]["bars"],2)
    def test_daily_conservatively_excludes_today(self):
        raw = [candle("2026-11-15"),candle("2026-11-16")]
        self.assertEqual(len(normalize(raw,"XAU/USD","1day",now=NOW)),1)
    def test_invalid_bar(self):
        bar = candle("2026-11-13 11:50:00")
        bar["high"]="1990"
        with self.assertRaises(Exception):
            normalize([bar], "XAU/USD", "5min",now=NOW)

if __name__ == "__main__":
    unittest.main()
