from tests.support import terminal, FakeClient, rates
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, Mock

from config import settings
from core.gold_session import GoldSession
from core.data_fetcher import DataFetcher
from core.data_pipeline import DataPipeline
from core.mt5_worker import MT5Client
from strategies.registry import configured_strategies, require_strategy


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.session=GoldSession(str(Path(self.tmp.name)/'gold.db'),client_factory=FakeClient)
    def tearDown(self):
        self.session.close()
        self.tmp.cleanup()

    def test_tradlab_files_are_unchanged(self):
        root=Path(__file__).resolve().parents[1]
        manifest=json.loads((root/'TRADLAB_PROVENANCE.json').read_text())
        for name, digest in manifest['unchanged_files'].items():
            self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),digest,name)

    def test_only_gold_and_four_intervals(self):
        self.assertEqual(settings.SYMBOL_LIST,[settings.GOLD_SYMBOL])
        self.assertEqual(settings.TIMEFRAME_LIST,[5,16385,16387,16408])
        with self.assertRaises(ValueError): settings.require_gold('EURUSD')

    def test_initialize_snapshot_filters_other_positions(self):
        snap=self.session.initialize()
        self.assertTrue(snap['account']['ok'])
        self.assertEqual([p.symbol for p in snap['positions']],[settings.GOLD_SYMBOL])

    def test_sync_collects_closed_bars_and_replaces_duplicates(self):
        self.session.initialize()
        self.session.collect()
        self.session.collect()
        for tf in settings.TIMEFRAME_LIST:
            frame=self.session.db.load_bars(settings.GOLD_SYMBOL,tf)
            self.assertEqual(len(frame),1)
        self.assertEqual(self.session.db.conn.execute('SELECT COUNT(DISTINCT symbol) FROM bars').fetchone()[0],1)

    def test_backfill_window_bounds_and_all_timeframes(self):
        self.session.initialize()
        end=datetime.now(timezone.utc)-timedelta(seconds=1)
        start=end-timedelta(days=21)
        self.session.collect(start,end)
        calls=[c for c in self.session.client.calls if isinstance(c,tuple) and c[0]=='range']
        self.assertEqual({c[2] for c in calls},set(settings.TIMEFRAME_LIST))
        self.assertEqual(len([c for c in calls if c[2]==5]),3)
        self.assertTrue(all(c[3].tzinfo==timezone.utc and c[4]<end for c in calls))

    def test_session_strategy_is_registered_and_gold_guard_remains(self):
        self.assertEqual([s.name for s in configured_strategies()], ['GOLD_SESSION_BREAKOUT'])
        from trade_executor import TradeExecutor
        executor=TradeExecutor(FakeClient())
        with self.assertRaises(ValueError):
            executor.execute(dict(symbol='EURUSD',action='BUY',lot_size=.01))

    def test_pipeline_rejects_non_gold(self):
        with self.assertRaises(ValueError):
            DataPipeline(Mock(),self.session.db).update_symbol('EURUSD',[5])

    def test_failed_connection_is_shutdown(self):
        client=FakeClient()
        client.symbol_select=lambda *args: False
        self.session.client_factory=lambda **kw: client
        with self.assertRaises(RuntimeError): self.session.initialize()
        self.assertTrue(client.closed)
        self.assertIsNone(self.session.client)

    def test_keyring_service_mapping_and_live_gate(self):
        for profile,service in [('DEMO','mt5'),('LIVE','mt5_live')]:
            with patch.dict('os.environ',{'MT5_ALLOW_LIVE':'1'}), patch('keyring.get_password',side_effect=['123','Broker','test-secret']) as get:
                self.assertEqual(settings.get_mt5_credentials(profile),(123,'Broker','test-secret',profile))
                self.assertEqual([c.args for c in get.call_args_list],[(service,'login'),(service,'server'),(service,'password')])
        with patch.dict('os.environ',{'MT5_ALLOW_LIVE':'0'}):
            with self.assertRaises(ValueError): settings.get_mt5_credentials('LIVE')

    def test_original_mt5_calls_remain_on_worker_thread(self):
        threads=[]
        def track(*args,**kwargs): threads.append(threading.get_ident()); return True
        with patch('core.mt5_worker.get_mt5_credentials',return_value=(123,'Broker','test-secret','DEMO')):
            with patch.object(terminal,'initialize',track,create=True), patch.object(terminal,'symbol_select',track,create=True), patch.object(terminal,'shutdown',track,create=True):
                client=MT5Client()
                try:
                    client.start()
                    self.assertTrue(client.symbol_select(settings.GOLD_SYMBOL))
                finally: client.shutdown()
                self.assertEqual(len(set(threads)),1)
                self.assertNotEqual(threads[0],threading.get_ident())

    def test_legacy_database_is_rejected_before_schema_changes(self):
        import sqlite3
        path=Path(self.tmp.name)/'legacy.db'
        with sqlite3.connect(path) as con:
            con.execute('CREATE TABLE bars (symbol TEXT, source TEXT)')
        with self.assertRaisesRegex(ValueError,'legacy goldenboy'):
            GoldSession(str(path))
        with sqlite3.connect(path) as con:
            self.assertEqual([r[1] for r in con.execute('PRAGMA table_info(bars)')],['symbol','source'])

    def test_retained_backend_modules_import_without_strategy_implementations(self):
        import importlib
        for name in ('core.orchestrator','core.bot_controller','backtest.engine','backtest.preparation','backtest.broker','backtest.risk','risk_manager','trade_executor'):
            importlib.import_module(name)

    def test_h3_adapter_retains_closed_tail_and_excludes_forming_bar(self):
        from core.gold_fetcher import GoldDataFetcher
        import pandas as pd
        now = 1000000
        frame = pd.DataFrame({'time': [now - 21600, now - 10800, now - 500]})
        with patch('core.gold_fetcher.time.time', return_value=now):
            result = GoldDataFetcher(FakeClient())._drop_unclosed_tail(frame, 16387)
        self.assertEqual(result['time'].tolist(), [now - 21600, now - 10800])
