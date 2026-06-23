def analyze_regimes(trades,benchmark=None):
    if benchmark is None or getattr(benchmark,"empty",True):return [],{"available":False,"warnings":["Benchmark data unavailable; regime analysis was not fabricated"]}
    return [],{"available":False,"warnings":["Regime classifier requires audited benchmark alignment before use"]}
