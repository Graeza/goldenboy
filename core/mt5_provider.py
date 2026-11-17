"""Read-only MT5 source, following tradlab's serialized terminal-call model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
import logging
import threading

from config import settings
from .provider import ProviderError, normalize

logger = logging.getLogger('goldenboy.mt5')
# The terminal bridge is process-global: serialize entire sessions as well as calls.
_terminal_lock = threading.Lock()


class MT5Provider:
    source = 'mt5'

    def __init__(self, module=None):
        self._executor = None
        self._owns_terminal = False
        self._closed = False
        try:
            self.mt5 = module or importlib.import_module('MetaTrader5')
        except ImportError:
            raise ProviderError('MT5 requires Windows, an installed terminal, and pip install -r requirements-mt5.txt') from None
        if not _terminal_lock.acquire(blocking=False):
            raise ProviderError('An MT5 collection session is already running')
        self._owns_terminal = True
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='goldenboy-mt5')
        try:
            self._call(self._initialize)
        except Exception:
            self.close()
            raise

    def _call(self, fn, *args, **kwargs):
        return self._executor.submit(fn, *args, **kwargs).result()

    def _initialize(self):
        creds = (settings.MT5_LOGIN, settings.MT5_PASSWORD, settings.MT5_SERVER)
        if any(creds) and not all(creds):
            raise ProviderError('Set MT5_LOGIN, MT5_PASSWORD and MT5_SERVER together in .env, or leave all empty to use the logged-in terminal')
        kwargs = {'timeout': 30000}
        if all(creds):
            try:
                kwargs.update(login=int(creds[0]), password=creds[1], server=creds[2])
            except ValueError:
                raise ProviderError('MT5_LOGIN must be an integer') from None
        args = (settings.MT5_PATH,) if settings.MT5_PATH else ()
        if not self.mt5.initialize(*args, **kwargs):
            raise ProviderError('MT5 initialization failed; check terminal installation and .env credentials')
        if not self.mt5.symbol_select(settings.MT5_SYMBOL, True):
            raise ProviderError('MT5 symbol unavailable; set MT5_SYMBOL to the exact broker symbol')
        logger.info('Connected to MT5; broker symbol %s', settings.MT5_SYMBOL)

    def fetch(self, symbol, timeframe, start=None, end=None, outputsize=None):
        if self._closed:
            raise ProviderError('MT5 provider is closed')
        names = {'5min': 'TIMEFRAME_M5', '1h': 'TIMEFRAME_H1', '1day': 'TIMEFRAME_D1'}
        if timeframe not in names:
            raise ValueError(f'Unsupported interval: {timeframe}')
        if start is None or end is None or start.tzinfo is None or end.tzinfo is None:
            raise ValueError('MT5 range requires timezone-aware start and end')
        rates = self._call(self.mt5.copy_rates_range, settings.MT5_SYMBOL,
                           getattr(self.mt5, names[timeframe]),
                           start.astimezone(timezone.utc), end.astimezone(timezone.utc))
        if rates is None:
            raise ProviderError('MT5 history request failed; check terminal connection and available broker history')
        rows = []
        for rate in rates:
            stamp = datetime.fromtimestamp(int(rate['time']), timezone.utc)
            if not start <= stamp <= end:
                continue
            rows.append({'datetime': stamp.isoformat(),
                         **{key: float(rate[key]) for key in ('open', 'high', 'low', 'close')},
                         'volume': float(rate['tick_volume'])})
        if not rows:
            logger.warning('MT5 returned no bars for %s (%s to %s); check broker sessions and terminal history', timeframe, start, end)
        return rows

    def normalize(self, rows, symbol, timeframe, now=None):
        # MT5 daily bars retain their actual UTC open; determine closure from open + duration.
        if timeframe != '1day':
            bars = normalize(rows, symbol, timeframe, now=now)
        else:
            from .provider import SECONDS
            current = now or datetime.now(timezone.utc)
            closed = [r for r in rows if datetime.fromisoformat(r['datetime']).timestamp() + SECONDS['1day'] <= current.timestamp()]
            # Reuse price validation without Twelve Data's session-date transformation.
            bars = normalize(closed, symbol, '1h', now=current)
            for bar in bars:
                bar['timeframe'] = '1day'
        for bar in bars:
            bar['source'] = self.source
        return bars

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self._executor is not None:
                self._call(self.mt5.shutdown)
        finally:
            if self._executor is not None:
                self._executor.shutdown(wait=True)
            if self._owns_terminal:
                self._owns_terminal = False
                _terminal_lock.release()
