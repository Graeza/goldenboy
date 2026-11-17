from tests.support import FakeClient
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, Mock
import pandas as pd

from strategies.session_breakout import SessionBreakout
from backtest.session_breakout import replay_signals
from core.gold_session import GoldSession


def at(hour, minute=0, second=0):
    # Input is SAST; return the actual UTC timestamp.
    return datetime(2026, 11, 17, hour, minute, second, tzinfo=timezone(timedelta(hours=2))).astimezone(timezone.utc)


def previous(now, high=2010, low=1990):
    return dict(time=int(now.timestamp())//300*300-300, high=high, low=low, open=2000, close=2000)


class BreakoutTests(unittest.TestCase):
    def setUp(self): self.strategy=SessionBreakout()

    def test_all_sast_third_hours_and_exclusive_ends(self):
        for start in (4,12,16):
            for now in (at(start), at(start,59,59)):
                self.assertEqual(self.strategy.evaluate_tick(previous(now),2011,now).signal.value,'BUY')
            for now in (at(start)-timedelta(seconds=1),at(start+1)):
                self.assertEqual(self.strategy.evaluate_tick(previous(now),2011,now).signal.value,'HOLD')

    def test_immediate_buy_sell_hold_and_equal_threshold(self):
        now=at(4,2,1)  # Before the current M5 candle closes.
        for price,side in ((2010.01,'BUY'),(1989.99,'SELL'),(2000,'HOLD'),(2010,'HOLD'),(1990,'HOLD')):
            self.assertEqual(self.strategy.evaluate_tick(previous(now),price,now).signal.value,side)

    def test_stale_reference_missing_and_invalid_prices_hold(self):
        now=at(12)
        bad=previous(now);bad['time']-=300
        for reference,price in ((None,2000),(bad,2011),(previous(now),float('nan')),(previous(now),-1)):
            self.assertEqual(self.strategy.evaluate_tick(reference,price,now).signal.value,'HOLD')

    def test_generic_next_open_engine_does_not_fake_immediate_entries(self):
        self.assertEqual(self.strategy.evaluate({}).meta['reason'],'live_tick_required')

    def test_replay_single_and_double_breakouts(self):
        now=at(4)
        bars=pd.DataFrame([
            previous(now),
            dict(time=int(now.timestamp()),open=2000,high=2011,low=1995,close=2005),
            dict(time=int(now.timestamp())+300,open=2005,high=2012,low=1994,close=2000)])
        result=replay_signals(bars)
        self.assertEqual(result.iloc[0]['signal'],'BUY')
        self.assertEqual(result.iloc[1]['signal'],'HOLD')
        self.assertEqual(result.iloc[1]['reason'],'ambiguous_intrabar_order')

    def test_replay_gap_open_has_known_first_break(self):
        now=at(16)
        bars=pd.DataFrame([previous(now),dict(time=int(now.timestamp()),open=2015,high=2020,low=1980,close=2000)])
        self.assertEqual(replay_signals(bars).iloc[0]['signal'],'BUY')


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.session=GoldSession(str(Path(self.tmp.name)/'gold.db'))
        self.client=FakeClient()
        self.session.client=self.client
        self.now=at(4,2,1)
        self.session._reference=previous(self.now)
        self.client.symbol_info_tick=lambda symbol: SimpleNamespace(bid=2011,ask=2012,time=self.now.timestamp())
        self.client.positions_get=lambda **kw: []
        self.clock=patch('core.gold_session.datetime',wraps=datetime)
        self.dt=self.clock.start();self.dt.now.return_value=self.now
    def tearDown(self):
        self.clock.stop();self.session.close();self.tmp.cleanup()

    def test_monitor_does_not_execute_and_opt_in_attempts_once_per_bar(self):
        with patch('risk_manager.RiskManager') as risk,patch('trade_executor.TradeExecutor') as executor:
            risk.return_value.assess.return_value={'symbol':'XAUUSD','action':'BUY','lot_size':.01}
            executor.return_value.execute.return_value={'ok':True}
            self.assertEqual(self.session.evaluate_market()['decision']['signal'],'BUY')
            executor.assert_not_called()
            self.session.evaluate_market(execute=True)
            self.session.evaluate_market(execute=True)
            executor.return_value.execute.assert_called_once()

    def test_existing_gold_position_prevents_order(self):
        from config.settings import GOLD_SYMBOL
        self.client.positions_get=lambda **kw:[SimpleNamespace(symbol=GOLD_SYMBOL)]
        with patch('trade_executor.TradeExecutor') as executor:
            result=self.session.evaluate_market(execute=True)
            self.assertEqual(result['execution']['reason'],'gold_position_already_open')
            executor.assert_not_called()

    def test_stale_tick_never_executes(self):
        self.client.symbol_info_tick=lambda symbol: SimpleNamespace(bid=2011,time=self.now.timestamp()-6)
        result=self.session.evaluate_market(execute=True)
        self.assertEqual(result['decision']['signal'],'HOLD')
        self.assertEqual(result['decision']['meta']['reason'],'stale_or_missing_tick')
