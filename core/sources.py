"""Source selection without importing the Windows-only MT5 package on startup."""
from config import settings
from .provider import TwelveDataProvider

SOURCES = ('twelvedata', 'mt5')


def database_path(source):
    if source not in SOURCES:
        raise ValueError(f'Unknown source: {source}')
    path = settings.MT5_DB_PATH if source == 'mt5' else settings.DB_PATH
    if settings.MT5_DB_PATH.resolve() == settings.DB_PATH.resolve():
        raise ValueError('GOLD_MT5_DB_PATH must differ from GOLD_DB_PATH to keep source histories separate')
    return path


def create_provider(source, api_key=None):
    if source == 'mt5':
        from .mt5_provider import MT5Provider
        return MT5Provider()
    if source == 'twelvedata':
        return TwelveDataProvider(settings.API_KEY if api_key is None else api_key)
    raise ValueError(f'Unknown source: {source}')


def close_provider(provider):
    if hasattr(provider, 'close'):
        provider.close()
    else:
        provider.session.close()
