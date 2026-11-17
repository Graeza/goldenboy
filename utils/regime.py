"""No built-in regime or indicator strategy."""
def detect_regime(frame):
    return {'trend': 'UNKNOWN', 'vol': 'UNKNOWN'}
