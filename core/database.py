import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS BARS (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL CHECK (timeframe IN ('5min','1h','1day')),
    time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    source TEXT NOT NULL DEFAULT 'twelvedata',
    is_closed INTEGER NOT NULL DEFAULT 1 CHECK (is_closed IN (0,1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY(symbol, timeframe, time),
    CHECK(high >= open AND high >= close AND high >= low),
    CHECK(low <= open AND low <= close AND low <= high),
    CHECK(open > 0 AND high > 0 AND low > 0 AND close > 0)
);
CREATE INDEX IF NOT EXISTS idx_bars_tf_time ON BARS(timeframe, time);
"""

def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    con.executescript(SCHEMA)
    return con


def upsert_bars(con: sqlite3.Connection, bars: list[dict]) -> int:
    if not bars:
        return 0
    fields = ("symbol", "timeframe", "time", "open", "high", "low", "close", "volume", "source", "is_closed", "updated_at")
    sql = """INSERT INTO BARS
    (symbol,timeframe,time,open,high,low,close,volume,source,is_closed,updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(symbol,timeframe,time) DO UPDATE SET
      open=excluded.open, high=excluded.high, low=excluded.low,
      close=excluded.close, volume=excluded.volume,
      source=excluded.source, is_closed=excluded.is_closed,
      updated_at=excluded.updated_at
    """
    with con:
        con.executemany(sql, [tuple(bar.get(f) for f in fields) for bar in bars])
    return len(bars)


def latest_time(con: sqlite3.Connection, symbol: str, timeframe: str) -> Optional[str]:
    row = con.execute(
        "SELECT MAX(time) AS t FROM BARS WHERE symbol=? AND timeframe=? AND is_closed=1",
        (symbol, timeframe),
    ).fetchone()
    return row["t"] if row else None


def stats(con: sqlite3.Connection, symbol: str) -> list[dict]:
    rows = con.execute("""SELECT timeframe, COUNT(*) AS bars, MIN(time) AS first_bar,
        MAX(time) AS last_bar FROM BARS WHERE symbol=? GROUP BY timeframe
        ORDER BY CASE timeframe WHEN '5min' THEN 1 WHEN '1h' THEN 2 ELSE 3 END""", (symbol,))
    return [dict(r) for r in rows]
