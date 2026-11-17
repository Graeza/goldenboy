"""Gold application boundary around tradlab's unchanged MT5 services."""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config.settings import DB_PATH, GOLD_SYMBOL, TIMEFRAME_LIST, TIMEFRAME_NAMES
from core.database import MarketDatabase
from strategies.registry import require_strategy

logger = logging.getLogger('goldenboy.session')


class GoldSession:
    def __init__(self, db_path=DB_PATH, client_factory=None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        if Path(db_path).exists():
            import sqlite3
            with sqlite3.connect(db_path) as existing:
                columns = {row[1] for row in existing.execute('PRAGMA table_info(bars)')}
            if 'source' in columns:
                raise ValueError('This is a legacy goldenboy database. Choose a new GOLD_DB_PATH; legacy files are not migrated or overwritten.')
        self.db = MarketDatabase(db_path)
        self.client_factory = client_factory
        self.client = None

    def initialize(self, profile='DEMO'):
        from core.mt5_worker import MT5Client
        client = self.client
        try:
            if client is not None:
                if not client.switch_profile(profile):
                    raise RuntimeError('MT5 profile switch failed')
            else:
                client = (self.client_factory or MT5Client)(profile=profile)
                client.start()
            if not client.symbol_select(GOLD_SYMBOL, True):
                raise RuntimeError(f'MT5 symbol_select failed for {GOLD_SYMBOL}')
            info = client.symbol_info(GOLD_SYMBOL)
            if info is None:
                raise RuntimeError('Gold symbol information is unavailable')
            base = getattr(info, 'currency_base', '')
            if base and base.upper() != 'XAU':
                raise RuntimeError('Configured broker symbol does not have gold (XAU) as base currency')
            self.client = client
            logger.info('MT5 connected: %s, %s', profile, GOLD_SYMBOL)
            return self.snapshot()
        except Exception:
            self.client = None
            if client is not None:
                client.shutdown()
            raise

    def require_connection(self):
        if self.client is None:
            raise RuntimeError('Initialize MetaTrader first')
        return self.client

    def collect(self, start=None, end=None):
        from core.data_fetcher import DataFetcher
        from core.data_pipeline import DataPipeline
        client = self.require_connection()
        fetcher = DataFetcher(client)
        if start is None:
            DataPipeline(fetcher, self.db).update_symbol(GOLD_SYMBOL, TIMEFRAME_LIST, n_bars=3000)
            logger.info('Refreshed gold M5, H1 and D1 candles')
        else:
            now = datetime.now(timezone.utc)
            if start.tzinfo is None or end is None or end.tzinfo is None or not start < end <= now:
                raise ValueError('Choose timezone-aware start < end <= now (end is exclusive)')
            for tf in TIMEFRAME_LIST:
                cursor = start
                days = {5: 10, 16385: 100, 16408: 365}[tf]
                while cursor < end:
                    upper = min(cursor + timedelta(days=days), end)
                    bars = fetcher.fetch_range(GOLD_SYMBOL, tf, int(cursor.timestamp()), int(upper.timestamp()) - 1)
                    if not bars.empty:
                        self.db.upsert_bars(bars, GOLD_SYMBOL, tf)
                    logger.info('%s: %s to %s: %s closed bars', TIMEFRAME_NAMES[tf], cursor.date(), upper.date(), len(bars))
                    if bars.empty:
                        logger.warning('No bars returned; broker history and terminal Max. bars in chart may limit coverage')
                    cursor = upper
        return self.snapshot()

    def snapshot(self):
        from utils.mt5_account import get_account_summary
        from utils.mt5_positions import list_positions
        client = self.require_connection()
        account = get_account_summary(client)
        if not account.get('ok'):
            raise RuntimeError('MT5 account information is unavailable')
        tick = client.symbol_info_tick(GOLD_SYMBOL)
        positions = [p for p in list_positions(client, GOLD_SYMBOL) if p.symbol == GOLD_SYMBOL]
        return {'account': account, 'positions': positions, 'tick': tick}

    def run_backtest(self, **kwargs):
        strategies = require_strategy()
        from backtest.engine import run_backtest_next_open
        from backtest.data_source import load_bars_from_db
        from core.ensemble import EnsembleEngine
        data = load_bars_from_db(self.db, GOLD_SYMBOL, TIMEFRAME_LIST)
        return run_backtest_next_open(symbol=GOLD_SYMBOL, bars_by_tf=data.bars_by_tf,
                                      timeframes=TIMEFRAME_LIST, primary_tf=5,
                                      ensemble=EnsembleEngine(strategies), **kwargs)

    def close(self):
        if self.client is not None:
            try:
                self.client.shutdown()
            finally:
                self.client = None
        self.db.close_thread_connection()
