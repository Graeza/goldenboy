from tests.support import FakeClient
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
import unittest
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication,QEvent
from core.gold_session import GoldSession
from gui.app import Window


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.window=Window(GoldSession(str(Path(self.tmp.name)/'gold.db'),client_factory=FakeClient))
    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.tmp.cleanup()
    def wait(self):
        end=time.monotonic()+5
        while self.window.thread is not None and time.monotonic()<end:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(self.window.thread)
    def test_tabs_and_strategy_controls(self):
        self.assertEqual([self.window.tabs.tabText(i) for i in range(self.window.tabs.count())],['Dashboard','Data','Portfolio','Backtesting','Logs'])
        self.assertTrue(self.window.run_backtest.isEnabled())
        self.assertEqual(len(self.window.chart.widget.ci.items),1)
        self.assertFalse(self.window.sync.isEnabled())
    def test_connect_collect_chart_and_shutdown(self):
        self.window.initialize.click()
        self.assertFalse(self.window.initialize.isEnabled())
        self.wait()
        self.assertIn('Connected',self.window.connection.text())
        self.assertEqual(self.window.positions.rowCount(),1)
        self.window.sync.click()
        self.wait()
        self.assertEqual(len(self.window.chart.rows),1)
        self.assertEqual(self.window.coverage.item(0,1).text(),'1')
        client=self.window.session.client
        self.window.close()
        self.assertTrue(client.closed)
    def test_failed_init_allows_retry(self):
        self.window.session.client_factory=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('unavailable'))
        self.window.initialize.click()
        self.wait()
        self.assertTrue(self.window.initialize.isEnabled())
        self.assertFalse(self.window.sync.isEnabled())

    def test_monitor_defaults_to_signals_only_and_stop_disarms_orders(self):
        from unittest.mock import patch
        self.window.initialize.click()
        self.wait()
        result={'decision':{'signal':'HOLD','meta':{'reason':'outside_third_hour'}},'execution':None}
        with patch.object(self.window.session,'evaluate_market',return_value=result) as poll:
            self.assertFalse(self.window.allow_orders.isChecked())
            self.window.monitor.click()
            self.wait()
            self.window.strategy_timer.stop()
            poll.assert_called_with(execute=False)
            self.assertIn('HOLD',self.window.strategy_status.text())
            self.window.allow_orders.setChecked(True)
            self.window.monitor.click()
            self.assertFalse(self.window.allow_orders.isChecked())
            self.assertFalse(self.window.strategy_timer.isActive())
