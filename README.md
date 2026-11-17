# Goldenboy · Gold trading workspace

A gold-only adaptation of tradlab with the compact Qt controls, candlestick chart and live log panel used in goldenboy. The previous Twelve Data application has been replaced. The supplied strategy is the SAST third-hour M5 breakout described below. There is no ML training or synthetic-index functionality. Order execution is off by default.

## Install and launch

Use Python 3.10+ on Windows with your broker's MetaTrader 5 terminal installed:

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
# Equivalent:
python -m gui.app
```

Linux/macOS can inspect local data and charts, but the MetaTrader5 Python bridge requires Windows. An offline launch does not import MT5 or read keyring credentials. For headless tests use `QT_QPA_PLATFORM=offscreen`.

## MetaTrader and keyring

The terminal implementation is copied directly from [tradlab](https://github.com/Graeza/tradlab). `TRADLAB_PROVENANCE.json` records the source commit and hashes of the unchanged files:

- `core/mt5_worker.py`: original MT5Worker and MT5Client, including initialization, profile switching, all terminal wrappers and shutdown.
- `core/mt5_init.py`: original initializer.
- `core/data_fetcher.py`: original closed-candle window/range fetching and UTC conversion.
- `utils/mt5_account.py` and `utils/mt5_positions.py`: original account/position helpers.
- `core/database.py`: original thread-local SQLite database, bars and trade-session tables.
- `core/ensemble.py` and `strategies/base.py`: original generic strategy contract and ensemble. The SAST breakout is the sole registered strategy.

Generic risk/execution and backtest modules also come from tradlab, with instrument-specific behavior removed and gold-only boundaries added. The application service calls the original MT5Client rather than the earlier goldenboy provider adapter. No live terminal calls are made by startup or by tests.

Tradlab's existing OS keyring entries work under the same OS user/backend:

```powershell
python -m keyring set mt5 login
python -m keyring set mt5 server
python -m keyring set mt5 password
```

Values are entered at hidden prompts. DEMO uses service `mt5`; LIVE uses `mt5_live`. Pick the profile in the header or set `MT5_ACCOUNT_PROFILE` in `.env`. Tradlab's LIVE gate is retained: `MT5_ALLOW_LIVE=1` is required before connecting to LIVE. There is no API-key field or alternative credential store. The terminal is auto-detected by the original client; sign in/open the intended broker terminal first.

Set `MT5_SYMBOL` to the exact gold broker symbol, e.g. `XAUUSD`, `XAUUSDm`, `XAUUSD.a`, or `GOLD`. There is one configured symbol only. Connection verifies the broker's base currency is XAU when provided. Other currency bases and other symbol names are rejected; positions shown in the UI are filtered to that configured gold symbol.

## Workspace

- **Dashboard:** connection status, gold bid/ask, per-interval storage coverage and strategy status.
- **Data:** date-range backfill, sync, and optional collection every five minutes. All operations collect M5, H1, H3 and D1 only. Scheduling starts only when clicked and skips cycles while a job is busy.
- **Portfolio:** account balance/equity/margin and open gold positions. Other account positions are not displayed or managed.
- **Backtesting:** indicator-free candle chart with M5/H1/H3/D1 selection, display-start date, latest-bar limit, pan/zoom and right-click export. Replay session signals from stored M5 OHLC data; ambiguous intrabar order is marked, and no trade P&L is simulated.
- **Logs:** log controls plus a bounded live log panel visible across every tab; rotating files in `logs/goldenboy.log`.

Click **Initialize MetaTrader** to initialize or switch profile in the background. Sync/backfill use that connection. The UI allows one operation at a time, keeps terminal work off the GUI thread, and waits for the current operation before closing. Shutdown uses the original client. The strategy monitor and order-execution checkbox are both off at startup. No manual order buttons or profit-close automation are enabled.

### Data collection

The database uses tradlab's integer MT5 timeframe enums and UTC epoch-second candle-open times. Store only closed candles, retaining broker OHLC, tick volume, spread and real volume. Sync refreshes the latest 3,000 bars per interval and upserts overlaps. Date backfill uses bounded windows and an exclusive UTC end date. Use backfill for longer outages.

Coverage is limited by broker history and terminal **Max. bars in chart**. Empty windows are logged; they do not prove complete coverage. Daily bars use tradlab's existing `open + timeframe seconds` closure check, including broker-session limitations. No indicator features are generated or charted.

### Existing databases

The default is a **new** `data/gold_tradlab.db`. Previous `data/market_data.db` and `data/mt5_market_data.db` files and `.env` are left untouched. Their older schema is incompatible with tradlab; pointing `GOLD_DB_PATH` at one is rejected before schema changes. Recollect into the new database. Automatic migration is not included. Twelve Data dependencies, API configuration and CLI collection commands are removed.

## SAST session breakout

Sessions are **02:00–11:00, 10:00–19:00, and 14:00–23:00 South African time** (`Africa/Johannesburg`, UTC+2). Only each session's third hour is eligible: **04:00–05:00, 12:00–13:00, 16:00–17:00 SAST**, with exclusive end boundaries. Stored candle timestamps remain UTC.

During an eligible hour, compare the **current live bid** (MT5 chart price) with the **immediately previous completed M5 candle**. Bid strictly above its high means BUY; bid strictly below its low means SELL; equality, an inside price, or an ineligible time means HOLD. No M5 close confirmation, H3-candle breakout, indicator, or extra higher-timeframe filter is applied. H1/H3/D1 are collected for inspection only. The reference rolls every five minutes; missing/gapped reference candles and ticks older than five seconds produce HOLD.

After initializing MT5, click **Start strategy monitor**. It polls the latest tick every 250 ms, subject to terminal/network latency; this is polling rather than a guaranteed tick stream and brief excursions between polls can be missed. It does not wait for the current candle to close. Monitoring pauses collection/profile switches so long backfills do not delay entries. Stop monitoring before collecting other intervals.

**Execute orders** is a separate unchecked checkbox. Without it, BUY/SELL signals are displayed/logged but no orders are sent. With it, the app uses tradlab's existing risk/execution mechanics: risk default 0.75%, fallback stop distance 0.3% of price, TP 1.8R, broker stop/volume normalization and spread checks. These are inherited defaults, not new session exit rules. Buy execution uses ask and sell execution uses bid through tradlab. No forced session-end exit is introduced.

The application allows at most one existing gold position and one order attempt per M5 candle, including failures or risk rejection, to avoid resending at each poll. Stopping the monitor disables future polls and clears order opt-in; an already-running operation finishes. LIVE still requires tradlab's profile gate. No live account actions are run by tests or development verification.

### Historical replay

**Replay session signals** uses stored M5 candles and the same SAST windows/reference bounds. If a candle opens beyond a boundary, that direction is known first. Otherwise a candle crossing only the high is BUY, only the low is SELL, and one crossing both is marked `ambiguous_intrabar_order` / HOLD. OHLC cannot establish first-touch order, spread/tick timing or executable fills; replay summarizes signals, not simulated trades or P&L. The old next-open simulation kernel is not used for this immediate-entry strategy. Its generic strategy adapter returns HOLD with `live_tick_required` to prevent delayed close-confirmation entries being represented as this rule.

## Validation

```powershell
python -m unittest discover -s tests -v
```

Tests use an explicit fake terminal and mocked keyring. They check source-file hashes, serialized calls through tradlab's MT5 worker, keyring profiles, gold isolation, closed M5/H1/H3/D1 candles, backfill bounds, database upserts and the Qt lifecycle. A real Windows terminal/account must still be used to validate live connectivity and broker-specific behavior.

H3 collection uses a small `GoldDataFetcher` subclass to supply the 10,800-second duration missing from tradlab. The original terminal client and fetcher files remain unchanged. Broker H3 candles use the broker's standard bar alignment; session-specific windows are a separate strategy concept.
