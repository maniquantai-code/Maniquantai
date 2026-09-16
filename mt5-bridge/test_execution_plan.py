from execution_plan import build_execution_plan, evaluate_plan


def bars_from_closes(closes):
    return [{"time": i + 1, "open": x, "high": x + 0.5, "low": x - 0.5, "close": x, "tick_volume": 100} for i, x in enumerate(closes)]


def test_ema_crossover_is_deterministic():
    spec = {"strategy_id": "s1", "symbol": "BTCUSD", "timeframe": "15m", "direction": "BOTH", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
    plan = build_execution_plan(spec)
    signal = evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5)
    assert signal is not None
    assert signal.side == "buy"
    assert signal.signal_key == "s1:6:buy"


def test_direction_short_blocks_long():
    spec = {"strategy_id": "s2", "symbol": "EURUSD", "timeframe": "15m", "direction": "SHORT", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
    plan = build_execution_plan(spec)
    signal = evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5)
    assert signal is None


def test_existing_position_blocks_new_entry():
    spec = {"strategy_id": "s3", "symbol": "BTCUSD", "timeframe": "15m", "direction": "BOTH", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
    plan = build_execution_plan(spec)
    assert evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5, has_long=True) is None


def test_breakout_uses_completed_candle_and_lookback():
    closes = [100] * 20 + [101]
    spec = {"strategy_id": "s4", "symbol": "XAUUSD", "timeframe": "15m", "direction": "LONG", "strategy_type": "breakout", "runtime": {"breakout_lookback": 20}}
    plan = build_execution_plan(spec)
    signal = evaluate_plan(plan, bars_from_closes(closes), 20)
    assert signal is not None
    assert signal.side == "buy"
