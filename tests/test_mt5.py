import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from config import settings
from core.mt5_provider import MT5Provider
from core.provider import ProviderError
from core.sources import database_path


class Terminal:
    TIMEFRAME_M5 = 5
    TIMEFRAME_H1 = 16385
    TIMEFRAME_D1 = 16408

    def __init__(self):
        self.calls = []
        self.rates = []
        self.ok = True

    def record(self, name, *args):
        self.calls.append((name, threading.get_ident(), args))

    def initialize(self, *args, **kwargs):
        self.record('initialize', args, kwargs)
        return self.ok

    def symbol_select(self, *args):
        self.record('select', *args)
        return True

    def copy_rates_range(self, *args):
        self.record('rates', *args)
        return self.rates

    def shutdown(self):
        self.record('shutdown')


def rate(stamp):
    return dict(time=int(datetime.fromisoformat(stamp).timestamp()), open=2000,
                high=2010, low=1990, close=2005, tick_volume=42)


class MT5Tests(unittest.TestCase):
    def setUp(self):
        self.credentials = patch('core.mt5_provider.get_mt5_credentials', return_value=(12345, 'Broker-Demo', 'test-password', 'DEMO'))
        self.credentials.start()
        self.terminal = Terminal()

    def tearDown(self):
        self.credentials.stop()

    def test_serialized_calls_utc_bounds_closed_bars_and_source(self):
        self.terminal.rates = [rate('2026-11-16T11:50:00+00:00'),
                               rate('2026-11-16T11:55:00+00:00')]
        provider = MT5Provider(self.terminal)
        try:
            start = datetime(2026, 11, 16, 11, 50, tzinfo=timezone.utc)
            end = datetime(2026, 11, 16, 11, 57, tzinfo=timezone.utc)
            rows = provider.fetch('XAU/USD', '5min', start, end)
            bars = provider.normalize(rows, 'XAU/USD', '5min', now=end)
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0]['source'], 'mt5')
            self.assertEqual(bars[0]['volume'], 42)
            self.assertEqual(bars[0]['time'], '2026-11-16T11:50:00Z')
            call = next(c for c in self.terminal.calls if c[0] == 'rates')
            self.assertEqual(call[2][1], self.terminal.TIMEFRAME_M5)
        finally:
            provider.close()
        self.assertEqual(len({c[1] for c in self.terminal.calls}), 1)
        self.assertNotEqual(self.terminal.calls[0][1], threading.get_ident())
        self.assertEqual(self.terminal.calls[-1][0], 'shutdown')

    def test_daily_retains_actual_open_and_excludes_unfinished(self):
        provider = MT5Provider(self.terminal)
        try:
            rows = [dict(datetime='2026-11-15T22:00:00+00:00', open=2000, high=2010, low=1990, close=2005),
                    dict(datetime='2026-11-16T22:00:00+00:00', open=2000, high=2010, low=1990, close=2005)]
            bars = provider.normalize(rows, 'XAU/USD', '1day', datetime(2026, 11, 17, 12, tzinfo=timezone.utc))
            self.assertEqual(len(bars), 1)
            self.assertEqual(bars[0]['time'], '2026-11-15T22:00:00Z')
            self.assertEqual(bars[0]['timeframe'], '1day')
        finally:
            provider.close()

    def test_failed_initialize_cleans_up_and_releases_session(self):
        self.terminal.ok = False
        with self.assertRaises(ProviderError):
            MT5Provider(self.terminal)
        self.assertEqual(self.terminal.calls[-1][0], 'shutdown')
        self.terminal.ok = True
        MT5Provider(self.terminal).close()

    def test_none_history_is_error(self):
        self.terminal.rates = None
        provider = MT5Provider(self.terminal)
        try:
            now = datetime.now(timezone.utc)
            with self.assertRaises(ProviderError):
                provider.fetch('XAU/USD', '1h', now, now)
        finally:
            provider.close()

    def test_source_databases_must_differ(self):
        self.assertNotEqual(database_path('mt5'), database_path('twelvedata'))
        with patch.object(settings, 'MT5_DB_PATH', settings.DB_PATH):
            with self.assertRaises(ValueError):
                database_path('mt5')

    def test_pipeline_persists_mt5_source(self):
        from core.database import connect
        from core.pipeline import backfill
        from pathlib import Path
        import tempfile
        self.terminal.rates = [rate('2026-11-16T11:50:00+00:00')]
        provider = MT5Provider(self.terminal)
        with tempfile.TemporaryDirectory() as folder:
            con = connect(Path(folder) / 'bars.db')
            try:
                start = datetime(2026, 11, 16, tzinfo=timezone.utc)
                end = datetime(2026, 11, 17, tzinfo=timezone.utc)
                backfill(provider, con, 'XAU/USD', '5min', start, end, now=end)
                self.assertEqual(con.execute('SELECT source FROM BARS').fetchone()[0], 'mt5')
            finally:
                con.close()
                provider.close()
