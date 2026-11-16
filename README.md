# Gold market data foundation

A single-symbol (`XAU/USD`) Python + SQLite data collector for 5-minute, hourly and daily OHLC candles from Twelve Data. No trade execution.

## Install (Windows PowerShell)

```powershell
py -3.9 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`, inserting your own `TWELVE_DATA_API_KEY` (do not commit `.env`). Requires Python 3.9+.

## Desktop app

Run `python -m gui.app` after installing requirements. The Qt desktop app offers:

- Backfill and sync for one interval or all intervals, with UTC date controls.
- Background collection while the interface remains responsive. One job runs at a time; wait for it to finish before closing.
- A queue-based log pump displaying live application logs, plus rotating files in `logs/goldenboy.log` (2 MB each, three backups).
- Candlestick charts from SQLite with interval selection, latest-bar limits, pan, zoom, and image export through the chart toolbar.

The API key comes from `.env` or the masked input and is never saved by the GUI. Backfill before the first sync. Charts show stored data; use Sync to fetch updates, then charts refresh automatically. No automatic collection schedule is enabled. Daily candles retain the session-date limitations below.

On Linux, Qt needs desktop display libraries; for headless tests set `QT_QPA_PLATFORM=offscreen`. CLI commands remain available.

## Start

```powershell
python main.py init
python main.py backfill --start 2026-11-01 --end 2026-11-16
python main.py status
python main.py sync
python -m unittest discover -s tests -v
```

`--end` is **exclusive** and UTC; e.g., `--end 2026-11-16` means dates before Nov 16. If `--start` and `--end` are omitted, `backfill` collects the past 30 calendar days. Narrow the timeframe with `--timeframe 5min`, `--timeframe 1h`, or `--timeframe 1day`.

### Inspect stored bars

```python
import sqlite3
con = sqlite3.connect('data/market_data.db')
rows = con.execute("SELECT * FROM BARS WHERE timeframe='5min' ORDER BY time DESC LIMIT 10").fetchall()
for row in rows: print(row)
con.close()
```

### Scheduling

Use Windows Task Scheduler to run `python main.py sync` once every 5 minutes after the expected bar close (e.g. minute 1, 6, 11...) rather than starting a busy polling loop. On each sync, the app refreshes all three intervals, costing ~3 calls each cycle (~864/day at 5-minute cadence); **this exceeds the free plan**. For the Basic plan, instead schedule separate commands:
- `python main.py sync --timeframe 5min` every 5 minutes after close (~288 calls/day on a 24-hour day)
- `python main.py sync --timeframe 1h` hourly after close (~24 calls/day)
- `python main.py sync --timeframe 1day` once daily after provider's daily close (~1 call/day)

Scheduling setup is not included in this project. Ensure the API plan permits the instrument/timeframe and use rates within plan quotas.

## Notes and limitations

- Twelve Data Basic plan has 8 credits/min and 800/day; `XAU/USD` access may be trial-limited. Check actual access with your API key.
- Rows are *closed bars only*. Intraday timestamps are UTC bar **open** times; daily timestamps are provider **session dates** (`YYYY-MM-DD`), not UTC close instants. Current UTC calendar-day daily bars are withheld conservatively. Validate daily session close semantics before creating signals.
- Backfill uses bounded 10-day (5m), 100-day (1h), 365-day (daily) windows, with no `outputsize` cap in date-bound requests. A defensive check fails if 5,000 rows appear.
- `sync` overlaps two bars to safely replace late updates; after a long outage it switches to windowed backfill.
- Missing gold trading-session periods are not necessarily data gaps. Session-aware gap detection and provider/broker OHLC comparison are next milestones.
- No API keys are shipped. No sample prices are represented as real market data.
- Failure of any request exits nonzero; existing DB rows remain committed. Retry later. API error handling is intentionally conservative (no unattended rate-limit retries).
- `BARS` is intended for a single symbol. It keeps a symbol column to avoid changing the schema later.
