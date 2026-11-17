"""Raw candle preparation. Strategy-specific features will be supplied later."""
def build_features(bars):
    return bars.copy().drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
