"""No bundled strategies. Register the supplied gold strategy here later."""
def configured_strategies():
    return []


def require_strategy():
    strategies = configured_strategies()
    if not strategies:
        raise RuntimeError("No strategy installed. Provide the gold strategy before trading or running a backtest.")
    return strategies
