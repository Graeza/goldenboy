"""Run headlessly with QT_QPA_PLATFORM=offscreen."""
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent, QDate
from gui.app import Window, Collector
from core.database import connect, upsert_bars
from core.provider import normalize
from datetime import datetime, timezone


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'test.db'
        self.patch = patch('gui.app.database_path', return_value=self.db)
        self.patch.start()
        logging.getLogger('goldenboy').setLevel(logging.INFO)
        self.window = Window()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.window = None
        self.patch.stop()
        self.tmp.cleanup()

    def test_log_pump_and_empty_chart(self):
        logging.getLogger('goldenboy.test').info('queued message')
        self.window.pump.drain()
        self.assertIn('queued message', self.window.logs.toPlainText())
        self.assertIn('No stored candles', self.window.summary.text())

    def test_chart_renders_stored_candle(self):
        con = connect(self.db)
        try:
            upsert_bars(con, normalize([dict(datetime='2026-01-01 10:00:00',
                        open='2000', high='2010', low='1990', close='2005')],
                        'XAU/USD', '5min', now=datetime(2026, 1, 2, tzinfo=timezone.utc)))
        finally:
            con.close()
        self.window.refresh()
        self.window.display_from.setDate(QDate(2026, 1, 1))
        self.app.processEvents()
        self.assertEqual(len(self.window.chart.rows), 1)
        self.assertEqual(self.window.chart.rows[0]['close'], 2005)
        self.window.display_from.setDate(QDate(2026, 1, 2))
        self.assertEqual(self.window.chart.rows, [])
        self.assertEqual(self.window.chart.price.listDataItems(), [])
        self.assertIn('1 bars', self.window.summary.text())

    def test_worker_error_always_finishes(self):
        worker = Collector('sync', '', ('5min',), None, None)
        messages = []
        worker.finished.connect(messages.append)
        worker.run()
        self.assertEqual(messages, ['Collection failed — see logs'])

    def test_background_job_finishes_and_reenables_controls(self):
        import time
        with patch('gui.app.API_KEY', 'fake-key'), patch('gui.app.sync', return_value=0):
            self.window.collect('sync')
            self.assertFalse(self.window.sync_button.isEnabled())
            deadline = time.monotonic() + 5
            while self.window.thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIsNone(self.window.thread)
            self.assertTrue(self.window.sync_button.isEnabled())

    def test_missing_key_directs_user_to_env_without_starting_worker(self):
        for key in ('', 'your_api_key_here'):
            with self.subTest(key=key), patch('gui.app.API_KEY', key):
                self.window.collect('sync')
                self.assertIsNone(self.window.thread)
                self.assertIn('.env', self.window.statusBar().currentMessage())
        self.assertFalse(hasattr(self.window, 'key'))

    def test_mt5_does_not_require_twelve_data_key(self):
        import time
        from unittest.mock import Mock
        self.window.source.setCurrentText('mt5')
        with patch('gui.app.API_KEY', ''), patch('gui.app.create_provider', return_value=Mock()) as factory, patch('gui.app.sync', return_value=0):
            self.window.collect('sync')
            deadline = time.monotonic() + 5
            while self.window.thread is not None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.01)
            self.assertIsNone(self.window.thread)
            factory.assert_called_once_with('mt5', '')
            self.assertTrue(self.window.source.isEnabled())

    def wait_for_job(self):
        import time
        deadline = time.monotonic() + 5
        while self.window.thread is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.window.thread)

    def test_initialize_retains_connection_reuses_it_and_closes_on_exit(self):
        from unittest.mock import Mock
        provider = Mock()
        with patch('gui.app.create_provider', return_value=provider) as factory:
            self.window.initialize_button.click()
            self.assertFalse(self.window.initialize_button.isEnabled())
            self.wait_for_job()
            factory.assert_called_once_with('mt5')
        self.assertIs(self.window.mt5_provider, provider)
        self.assertEqual(self.window.source.currentText(), 'mt5')
        self.assertFalse(self.window.initialize_button.isEnabled())
        provider.close.assert_not_called()
        with patch('gui.app.create_provider') as factory, patch('gui.app.sync', return_value=0) as sync:
            self.window.collect('sync')
            self.wait_for_job()
            factory.assert_not_called()
            self.assertIs(sync.call_args.args[0], provider)
        provider.close.assert_not_called()
        self.window.close()
        provider.close.assert_called_once()

    def test_initialize_failure_allows_retry(self):
        from core.provider import ProviderError
        with patch('gui.app.create_provider', side_effect=ProviderError('Connection unavailable')):
            self.window.initialize_button.click()
            self.wait_for_job()
        self.assertIsNone(self.window.mt5_provider)
        self.assertTrue(self.window.initialize_button.isEnabled())
        self.assertTrue(self.window.sync_button.isEnabled())
        self.window.pump.drain()
        self.assertIn('Connection unavailable', self.window.logs.toPlainText())
