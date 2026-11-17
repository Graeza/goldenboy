"""Explicit test terminal. Never connects to a real account."""
import sys
import types
import time
import numpy as np

terminal = types.ModuleType('MetaTrader5')
for key, value in {'TIMEFRAME_M5':5,'TIMEFRAME_H1':16385,'TIMEFRAME_D1':16408,
    'POSITION_TYPE_BUY':0,'POSITION_TYPE_SELL':1,'ORDER_TYPE_BUY':0,'ORDER_TYPE_SELL':1}.items():
    setattr(terminal,key,value)
sys.modules['MetaTrader5'] = terminal


def rates(tf=5):
    duration={5:300,16385:3600,16408:86400}[tf]
    stamp=int(time.time()) // duration * duration
    return np.array([(stamp-duration,2000,2010,1990,2005,42,12,0),
                     (stamp,2005,2012,2000,2007,12,11,0)],
        dtype=[('time','i8'),('open','f8'),('high','f8'),('low','f8'),('close','f8'),('tick_volume','f8'),('spread','f8'),('real_volume','f8')])


class FakeClient:
    profile='DEMO'
    def __init__(self, profile='DEMO'):
        self.profile=profile
        self.calls=[]
        self.closed=False
    def start(self): self.calls.append('start')
    def shutdown(self): self.closed=True
    def switch_profile(self, profile): self.profile=profile; return True
    def symbol_select(self, symbol, enabled): self.calls.append(('symbol',symbol)); return True
    def symbol_info(self, symbol): return types.SimpleNamespace(currency_base='XAU')
    def account_info(self): return types.SimpleNamespace(login=123,currency='USD',balance=1000,equity=1000)
    def symbol_info_tick(self, symbol): return types.SimpleNamespace(bid=2000,ask=2001)
    def positions_get(self, **kwargs):
        from config.settings import GOLD_SYMBOL
        return [types.SimpleNamespace(symbol=s,ticket=i,type=0,volume=.01,price_open=2000,price_current=2001,profit=1) for i,s in enumerate((GOLD_SYMBOL,'EURUSD'))]
    def copy_rates_from_pos(self, symbol, tf, start, count): self.calls.append(('rates',symbol,tf)); return rates(tf)
    def copy_rates_range(self, symbol, tf, start, end):
        self.calls.append(('range',symbol,tf,start,end))
        frame=rates(tf)
        return frame[(frame['time']>=start.timestamp()) & (frame['time']<=end.timestamp())]
