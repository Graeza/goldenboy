"""SAST third-hour breakout of the immediately preceding completed M5 candle."""
from datetime import datetime, timezone
import math
from zoneinfo import ZoneInfo

from strategies.base import Strategy, StrategyResult, Signal

SAST = ZoneInfo('Africa/Johannesburg')
SESSIONS = ((2, 11), (10, 19), (14, 23))


class SessionBreakout(Strategy):
    name = 'GOLD_SESSION_BREAKOUT'

    def _evaluate(self, data_by_tf):
        # The generic next-open kernel cannot reproduce immediate tick entries.
        return self.result('HOLD', 'live_tick_required')

    def result(self, side, reason, **meta):
        return StrategyResult(self.name, Signal(side), 1.0 if side != 'HOLD' else 0.0,
                              {'reason': reason, **meta})

    def session(self, now):
        if now.tzinfo is None:
            raise ValueError('Strategy time must be timezone-aware')
        local = now.astimezone(SAST)
        for start, end in SESSIONS:
            if start + 2 <= local.hour < start + 3:
                return f'{start:02d}:00–{end:02d}:00 SAST'
        return None

    def evaluate_tick(self, previous, bid, now):
        session = self.session(now)
        if session is None:
            return self.result('HOLD', 'outside_third_hour')
        if previous is None:
            return self.result('HOLD', 'missing_previous_m5')
        expected = int(now.timestamp()) // 300 * 300 - 300
        try:
            stamp = int(previous['time'])
            high, low = float(previous['high']), float(previous['low'])
            bid = float(bid)
            if stamp != expected:
                return self.result('HOLD', 'stale_previous_m5')
            if not all(math.isfinite(v) and v > 0 for v in (high, low, bid)) or low > high:
                return self.result('HOLD', 'invalid_prices')
        except (TypeError, ValueError, KeyError):
            return self.result('HOLD', 'invalid_prices')
        side = 'BUY' if bid > high else 'SELL' if bid < low else 'HOLD'
        return self.result(side, 'high_break' if side == 'BUY' else 'low_break' if side == 'SELL' else 'inside_previous_range',
                           session=session, reference_time=stamp, high=high, low=low, bid=bid)
