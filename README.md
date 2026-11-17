# Goldenboy · Gold trading workspace

A gold-only adaptation of tradlab with the compact Qt controls, candlestick chart and live log panel used in goldenboy. The previous Twelve Data application has been replaced. There are **no bundled trading strategies**, no ML training, and no synthetic-index features. Trading and backtest execution stay disabled until the gold strategy is supplied.

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
- `core/ensemble.py` and `strategies/base.py`: original generic strategy contract and ensemble; no implementations are registered.

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
- **Data:** date-range backfill, sync, and optional collection every five minutes. All operations collect M5, H1 and D1 only. Scheduling starts only when clicked and skips cycles while a job is busy.
- **Portfolio:** account balance/equity/margin and open gold positions. Other account positions are not displayed or managed.
- **Backtesting:** indicator-free candle chart with M5/H1/D1 selection, display-start date, latest-bar limit, pan/zoom and right-click export. Backtest execution is disabled until a strategy exists.
- **Logs:** log controls plus a bounded live log panel visible across every tab; rotating files in `logs/goldenboy.log`.

Click **Initialize MetaTrader** to initialize or switch profile in the background. Sync/backfill use that connection. The UI allows one operation at a time, keeps terminal work off the GUI thread, and waits for the current operation before closing. Shutdown uses the original client. No start-up trading, manual order buttons, profit-close automation or strategy signals are enabled.

### Data collection

The database uses tradlab's integer MT5 timeframe enums and UTC epoch-second candle-open times. Store only closed candles, retaining broker OHLC, tick volume, spread and real volume. Sync refreshes the latest 3,000 bars per interval and upserts overlaps. Date backfill uses bounded windows and an exclusive UTC end date. Use backfill for longer outages.

Coverage is limited by broker history and terminal **Max. bars in chart**. Empty windows are logged; they do not prove complete coverage. Daily bars use tradlab's existing `open + timeframe seconds` closure check, including broker-session limitations. No indicator features are generated or charted.

### Existing databases

The default is a **new** `data/gold_tradlab.db`. Previous `data/market_data.db` and `data/mt5_market_data.db` files and `.env` are left untouched. Their older schema is incompatible with tradlab; pointing `GOLD_DB_PATH` at one is rejected before schema changes. Recollect into the new database. Automatic migration is not included. Twelve Data dependencies, API configuration and CLI collection commands are removed.

## Strategy to be supplied

`strategies/base.py` is tradlab's original abstract contract, and `strategies/registry.py` intentionally returns an empty list. The generic ensemble, risk sizing, execution mechanics, deterministic next-open backtest kernel and metrics are retained for the supplied strategy. No concrete strategy, indicator signal, model, or default BUY/SELL decision ships in this app.

Trading and backtest entry points must explicitly require a configured strategy. Execution also rejects non-gold symbols. The UI deliberately cannot start trading or a simulation yet; adding your strategy and wiring its controls is a subsequent change, not an automatic account action.

## Validation

```powershell
python -m unittest discover -s tests -v
```

Tests use an explicit fake terminal and mocked keyring. They check source-file hashes, serialized calls through tradlab's MT5 worker, keyring profiles, gold isolation, closed M5/H1/D1 candles, backfill bounds, database upserts and the Qt lifecycle. A real Windows terminal/account must still be used to validate live connectivity and broker-specific behavior.
