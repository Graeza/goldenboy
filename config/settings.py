import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SYMBOL = os.getenv("GOLD_SYMBOL", "XAU/USD")
DB_PATH = Path(os.getenv("GOLD_DB_PATH", "data/market_data.db"))
API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
TIMEFRAMES = ("5min", "1h", "1day")
# Max 2,880 5m bars per 10 calendar days; avoids Twelve Data's 5,000-row cap.
WINDOW_DAYS = {"5min": 10, "1h": 100, "1day": 365}