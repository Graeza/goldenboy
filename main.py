"""CLI: python main.py init|backfill|sync|status"""
import argparse
import logging
from core.logging_setup import configure_logging
from datetime import datetime, timezone, timedelta

from config.settings import SYMBOL, TIMEFRAMES
from core.database import connect, stats
from core.pipeline import backfill, sync
from core.provider import ProviderError
from core.sources import SOURCES, create_provider, close_provider, database_path
from config.settings import DATA_SOURCE


def parse_datetime(text):
    if not text:
        return None
    val = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val.astimezone(timezone.utc)


def main():
    configure_logging()
    console = logging.StreamHandler()
    logging.getLogger("goldenboy").addHandler(console)
    p = argparse.ArgumentParser(description="Gold XAU/USD SQLite market data collector")
    p.add_argument("command", choices=["init", "backfill", "sync", "status"])
    p.add_argument("--start", help="UTC start date YYYY-MM-DD (backfill only)")
    p.add_argument("--end", help="Exclusive UTC end date YYYY-MM-DD (backfill only)")
    p.add_argument("--timeframe", choices=["all", *TIMEFRAMES], default="all")
    p.add_argument("--source", choices=SOURCES, default=DATA_SOURCE)
    args = p.parse_args()
    con = connect(database_path(args.source))
    provider = None
    try:
        if args.command == "init":
            print(f"Initialized {database_path(args.source)}")
            return
        if args.command == "status":
            for row in stats(con, SYMBOL):
                print(row)
            return
        provider = create_provider(args.source)
        frames = TIMEFRAMES if args.timeframe == "all" else (args.timeframe,)
        now = datetime.now(timezone.utc)
        if args.command == "backfill":
            start = parse_datetime(args.start) or now - timedelta(days=30)
            end = parse_datetime(args.end) or now
            if end > now:
                raise ValueError("end may not be in the future")
            for tf in frames:
                backfill(provider, con, SYMBOL, tf, start, end, now=now)
        elif args.command == "sync":
            for tf in frames:
                sync(provider, con, SYMBOL, tf, now=now)
    except (ProviderError, ValueError) as exc:
        p.exit(1, f"Error: {exc}\n")
    finally:
        con.close()
        if provider is not None:
            close_provider(provider)

if __name__ == "__main__":
    main()
