"""Add the H3 duration missing from tradlab, leaving its MT5 implementation intact."""
import time
from core.data_fetcher import DataFetcher


class GoldDataFetcher(DataFetcher):
    def _drop_unclosed_tail(self, frame, timeframe):
        if int(timeframe) != 16387 or frame is None or frame.empty:
            return super()._drop_unclosed_tail(frame, timeframe)
        return frame[frame['time'].astype('int64') + 10800 <= int(time.time())].copy()
