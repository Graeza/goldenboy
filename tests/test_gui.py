"""Run headlessly with QT_QPA_PLATFORM=offscreen."""
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
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
        self.window.canvas.draw()
        self.assertEqual(len(self.window.figure.axes[0].patches), 1)
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
