"""Gold-only settings; keyring profiles use tradlab's credential names."""
import os
from pathlib import Path
import re
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / '.env')
GOLD_SYMBOL = os.getenv('MT5_SYMBOL', 'XAUUSD').strip()
if not re.fullmatch(r'(?:XAUUSD|GOLD)(?:[._-]?[A-Za-z0-9]+)?', GOLD_SYMBOL, re.IGNORECASE):
    raise ValueError('MT5_SYMBOL must be a gold symbol such as XAUUSD, XAUUSDm or GOLD')
SYMBOL_LIST = [GOLD_SYMBOL]
TIMEFRAME_LIST = [5, 16385, 16408]  # MT5 M5, H1, D1 enums, unchanged at terminal boundary.
TIMEFRAME_NAMES = {5: '5 minutes', 16385: 'Hourly', 16408: 'Daily'}
PRIMARY_TIMEFRAME = 5
DB_PATH = str(Path(os.getenv('GOLD_DB_PATH', str(PROJECT_ROOT / 'data' / 'gold_tradlab.db'))))
LOOP_SLEEP_SECONDS = 300
FEATURE_SET_VERSION = 1
ACTIVE_ACCOUNT_PROFILE = os.getenv('MT5_ACCOUNT_PROFILE', 'DEMO').strip().upper()
ALLOW_LIVE_TRADING = os.getenv('MT5_ALLOW_LIVE', '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def is_live_trading_allowed():
    return os.getenv('MT5_ALLOW_LIVE', '1' if ALLOW_LIVE_TRADING else '0').strip().lower() in {'1', 'true', 'yes', 'on'}


def set_live_trading_allowed(enabled):
    os.environ['MT5_ALLOW_LIVE'] = '1' if enabled else '0'


def get_mt5_credentials(profile=None):
    # Same profile/service mapping and LIVE gate as tradlab. Load on connection
    # rather than import so offline database/chart viewing does not need keyring.
    import keyring as kr
    resolved_profile = (profile or ACTIVE_ACCOUNT_PROFILE).strip().upper()
    if resolved_profile not in ('DEMO', 'LIVE'):
        raise ValueError('Unknown MT5 profile. Valid profiles: DEMO, LIVE')
    if resolved_profile == 'LIVE' and not is_live_trading_allowed():
        raise ValueError('LIVE profile is blocked by default. Set MT5_ALLOW_LIVE=1 to enable.')
    service = 'mt5' if resolved_profile == 'DEMO' else 'mt5_live'
    try:
        login = kr.get_password(service, 'login')
        server = kr.get_password(service, 'server')
        password = kr.get_password(service, 'password')
    except Exception:
        raise ValueError('Cannot read MT5 keyring credentials. Unlock/configure the OS keyring.') from None
    if not login or not server or not password:
        raise ValueError(f'Incomplete credentials for MT5 profile {resolved_profile}; configure keyring service {service}.')
    try:
        login = int(login)
        if login <= 0:
            raise ValueError()
    except ValueError:
        raise ValueError('Keyring login must be a positive account number') from None
    return login, str(server), str(password), resolved_profile


def require_gold(symbol):
    if symbol != GOLD_SYMBOL:
        raise ValueError(f'Only the configured gold symbol {GOLD_SYMBOL} is supported')
