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
- Tradlab-style pyqtgraph candlestick charts with linked price/indicator panels, interval selection, a UTC display-start date, and a latest-bar limit (up to 20,000). Drag to pan, use the wheel to zoom, and right-click for auto-range and export. Toggle EMA10, EMA21, RSI(14), MACD(12,26,9), signal, and histogram.

Configure `TWELVE_DATA_API_KEY` in `.env` before launching the app. The GUI has no API-key input and never displays or saves the key. Restart the app after changing `.env`. Backfill before the first sync. Charts show stored data; use Sync to fetch updates, then charts refresh automatically. No automatic collection schedule is enabled. Daily candles retain the session-date limitations below.

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

## MetaTrader 5 data source

MT5 support follows [tradlab's serialized MT5 client](https://github.com/Graeza/tradlab/blob/main/core/mt5_worker.py) and [closed-candle range fetching](https://github.com/Graeza/tradlab/blob/main/core/data_fetcher.py). It is read-only and does not place orders.

On Windows, install and log in to your broker's MT5 terminal, then run:

```powershell
pip install -r requirements-mt5.txt
python -m gui.app
# Or use the CLI:
python main.py backfill --source mt5 --start 2026-11-01 --end 2026-11-16
python main.py sync --source mt5
python main.py status --source mt5
```

Choose `mt5` in the GUI Source selector, or set `GOLD_DATA_SOURCE=mt5` in `.env` as the default. Set `MT5_SYMBOL` to the exact broker symbol (default `XAUUSD`, including any broker suffix). `GOLD_SYMBOL` remains the canonical database symbol. Optionally set `MT5_PATH` to the terminal executable. Set `MT5_ACCOUNT_PROFILE=DEMO` (default) or `LIVE`. Login credentials come exclusively from the OS keyring using tradlab's existing entries; there is no environment-credential or logged-in-terminal fallback. Credentials are never entered in the GUI. Restart after configuration changes. A Twelve Data key is not needed for MT5.

MT5 uses `GOLD_MT5_DB_PATH` (default `data/mt5_market_data.db`); Twelve Data retains `GOLD_DB_PATH`. Paths must differ so changing source cannot overwrite candles or resume from another provider's history. Charts and status follow the selected source. Existing Twelve Data databases need no migration. MT5 rows carry `source=mt5`; volume is broker tick volume. Daily MT5 bars preserve actual UTC open timestamps and are withheld until open + 24 hours, unlike Twelve Data's session-date labels. Verify broker session semantics before using daily bars for signals.

All terminal calls, including initialization and shutdown, run on one dedicated worker thread. Available history depends on the broker and the terminal's **Max. bars in chart** setting; empty results are logged and are not proof of complete history. Load the required history in the terminal before backfilling. MT5 is optional; Twelve Data and chart viewing still work without its Windows-only package.

### MT5 keyring setup (shared with tradlab)

If tradlab is already configured under the same OS user and keyring backend, its stored credentials work directly. Otherwise run these commands, entering each value at the hidden prompt:

```powershell
python -m keyring set mt5 login
python -m keyring set mt5 server
python -m keyring set mt5 password
```

For `MT5_ACCOUNT_PROFILE=LIVE`, replace service `mt5` with `mt5_live` in all three commands. Goldenboy only reads market data from either profile. `MT5_PATH`, `MT5_SYMBOL`, and profile selection remain in `.env`; remove the old `MT5_LOGIN`, `MT5_PASSWORD`, and `MT5_SERVER` values, which are no longer used. Missing or inaccessible keyring entries stop collection with a setup message. Credentials are loaded when connecting, so updates in the keyring apply to the next collection job. Goldenboy never writes to the keyring or logs credential values.

### Chart behavior

Charting follows [tradlab's candlestick view](https://github.com/Graeza/tradlab/blob/main/gui/app.py): green/red candle bodies, linked price and indicator panels, legends, grid lines, and bar-index spacing that compresses market closures. EMA10, EMA21, and RSI are selected initially; MACD components are opt-in. Indicators use the same TA-Lib EMA/MACD and simple rolling-average RSI calculations as tradlab. Initial warmup values are blank. Calculations use the displayed bars; changing the display date or limit changes their warmup history. RSI and MACD share the lower panel as in tradlab, so their different scales can affect readability when enabled together.

“Display from” filters stored candles from UTC midnight independently of collection dates. Source, interval, date, limit, or indicator changes redraw the chart. The bottom label shows the first and last timestamps; the horizontal axis uses bar numbers. An empty range clears the previous chart. Right-click a panel and choose Export to save an image or data.
