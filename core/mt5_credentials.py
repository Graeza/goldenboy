"""Load credentials using tradlab's keyring service and entry names."""
import importlib

from config import settings
from .provider import ProviderError


def get_mt5_credentials():
    profile = settings.MT5_ACCOUNT_PROFILE.strip().upper()
    services = {'DEMO': 'mt5', 'LIVE': 'mt5_live'}
    if profile not in services:
        raise ProviderError('MT5_ACCOUNT_PROFILE must be DEMO or LIVE')
    service = services[profile]
    try:
        keyring = importlib.import_module('keyring')
        login, server, password = (keyring.get_password(service, entry)
                                   for entry in ('login', 'server', 'password'))
    except ImportError:
        raise ProviderError('MT5 keyring support requires pip install -r requirements-mt5.txt') from None
    except Exception:
        # Backend errors may include private details; do not forward them into logs.
        raise ProviderError('Cannot access MT5 credentials in the OS keyring; unlock or configure your keyring backend') from None
    if not login or not server or not password:
        raise ProviderError(f'Missing MT5 credentials: store login, server and password under keyring service {service}')
    try:
        account = int(login)
        if account <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ProviderError(f'The login entry under keyring service {service} must be a positive integer') from None
    return account, server, password, profile
