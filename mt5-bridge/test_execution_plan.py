import unittest

from execution_plan import build_execution_plan, evaluate_plan


def bars_from_closes(closes):
    return [{"time": i + 1, "open": x, "high": x + 0.5, "low": x - 0.5, "close": x, "tick_volume": 100} for i, x in enumerate(closes)]


class ExecutionPlanTests(unittest.TestCase):
    def test_ema_crossover_is_deterministic(self):
        spec = {"strategy_id": "s1", "symbol": "BTCUSD", "timeframe": "15m", "direction": "BOTH", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
        plan = build_execution_plan(spec)
        signal = evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "buy")
        self.assertEqual(signal.signal_key, "s1:6:buy")

    def test_direction_short_blocks_long(self):
        spec = {"strategy_id": "s2", "symbol": "EURUSD", "timeframe": "15m", "direction": "SHORT", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
        plan = build_execution_plan(spec)
        signal = evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5)
        self.assertIsNone(signal)

    def test_existing_position_blocks_new_entry(self):
        spec = {"strategy_id": "s3", "symbol": "BTCUSD", "timeframe": "15m", "direction": "BOTH", "strategy_type": "ema_crossover", "runtime": {"ema_fast": 2, "ema_slow": 3}}
        plan = build_execution_plan(spec)
        self.assertIsNone(evaluate_plan(plan, bars_from_closes([1, 1, 1, 2, 3, 4]), 5, has_long=True))

    def test_breakout_uses_completed_candle_and_lookback(self):
        closes = [100] * 20 + [101]
        spec = {"strategy_id": "s4", "symbol": "XAUUSD", "timeframe": "15m", "direction": "LONG", "strategy_type": "breakout", "runtime": {"breakout_lookback": 20}}
        plan = build_execution_plan(spec)
        signal = evaluate_plan(plan, bars_from_closes(closes), 20)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.side, "buy")


if __name__ == "__main__":
    unittest.main()
