"""The supplied gold session strategy, evaluated on live ticks."""
from strategies.session_breakout import SessionBreakout


def configured_strategies():
    return [SessionBreakout()]


def require_strategy():
    return configured_strategies()
