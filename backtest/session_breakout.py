"""M5 OHLC signal replay. Intrabar ordering and actual fills require tick history."""
from datetime import datetime, timezone
import pandas as pd
from strategies.session_breakout import SessionBreakout


def replay_signals(bars):
    if bars is None or len(bars) < 2:
        raise ValueError('At least two stored M5 candles are required')
    frame = bars.sort_values('time').drop_duplicates('time').reset_index(drop=True)
    strategy = SessionBreakout()
    records = []
    for i in range(1, len(frame)):
        bar, previous = frame.iloc[i], frame.iloc[i-1]
        now = datetime.fromtimestamp(int(bar['time']), timezone.utc)
        # Validate time/window and reference via the exact live evaluator.
        baseline = strategy.evaluate_tick(previous, float(bar['open']), now)
        reason, side = baseline.meta['reason'], 'HOLD'
        if reason in ('inside_previous_range', 'high_break', 'low_break'):
            if baseline.signal.value != 'HOLD':
                side = baseline.signal.value  # A gap beyond a threshold is known at open.
            else:
                up, down = bar['high'] > previous['high'], bar['low'] < previous['low']
                if up and down:
                    reason = 'ambiguous_intrabar_order'
                elif up:
                    side, reason = 'BUY', 'high_break'
                elif down:
                    side, reason = 'SELL', 'low_break'
        records.append({'time': int(bar['time']), 'signal': side, 'reason': reason,
                        'previous_high': float(previous['high']), 'previous_low': float(previous['low'])})
    return pd.DataFrame(records)
