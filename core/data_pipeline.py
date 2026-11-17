"""Tradlab raw-bar collection; no features or strategy indicators."""
from config.settings import GOLD_SYMBOL, TIMEFRAME_LIST, require_gold


class DataPipeline:
    def __init__(self, fetcher, db):
        self.fetcher, self.db = fetcher, db

    def update_symbol(self, symbol, timeframes, n_bars=2000):
        require_gold(symbol)
        out = {}
        for tf in timeframes:
            if tf not in TIMEFRAME_LIST:
                raise ValueError('Only M5, H1 and D1 are supported')
            # Use tradlab fetch_window, with overlap to refresh broker corrections.
            frame = self.fetcher.fetch_window(symbol, tf, n_bars)
            if not frame.empty:
                self.db.upsert_bars(frame, symbol, tf)
            out[tf] = self.db.load_bars(symbol, tf, limit=3000)
        return out
